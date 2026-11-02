"""Recall: find what a creature has lived (and shared lore) by keywords, plus embeddings when cached.

Search never waits on the network. Docs and queries that lack vectors are listed in `pending()`; a
background task embeds them (`embed_pending`) and hands the vectors back with `set_vectors`.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Awaitable, Callable, Iterable

import numpy as np


K1 = 1.2
B = 0.75
HALF_LIFE = 2400
MAX_QUERY_CACHE = 256
BATCH = 128
VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"

STOP_WORDS = frozenset(
    "a an and are as at be but by for from has have i in is it its me my of on or so that the "
    "their there this to was we were what when where which who with you your".split()
)
_WORD = re.compile(r"[a-z0-9']+")


def tokenize(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in STOP_WORDS]


@dataclass
class Doc:
    key: str
    kind: str
    text: str
    tick: int
    importance: int


class RecallIndex:
    def __init__(self, cap: int = 2000) -> None:
        self.cap = cap
        self._docs: dict[str, list[Doc]] = {}
        self._lore: list[Doc] = []
        self._next = 0
        self._tokens: dict[str, list[str]] = {}
        self._vecs: dict[str, np.ndarray] = {}  # doc key -> unit vector
        self._qvecs: dict[str, np.ndarray] = {}  # normalized query -> unit vector (insertion ordered)
        self._pending_q: dict[str, str] = {}  # normalized query -> query text

    # -- building -----------------------------------------------------------------------------

    def _new_key(self, prefix: str) -> str:
        self._next += 1
        return f"{prefix}:{self._next}"

    def _put(self, doc: Doc) -> None:
        self._tokens[doc.key] = tokenize(doc.text)

    def add(self, cid: str, kind: str, text: str, tick: int, importance: int = 1, skip_repeat: bool = False) -> None:
        text = text.strip()
        if not text:
            return
        docs = self._docs.setdefault(cid, [])
        if skip_repeat and docs and docs[-1].text == text:  # a repeat of the previous doc adds nothing
            return
        doc = Doc(self._new_key(cid), kind, text, tick, importance)
        docs.append(doc)
        self._put(doc)
        if len(docs) > self.cap:
            worst = min(docs, key=lambda d: (d.importance, d.tick))
            docs.remove(worst)
            self._tokens.pop(worst.key, None)
            self._vecs.pop(worst.key, None)

    def add_lore(self, name: str, text: str) -> None:
        text = text.strip()
        if not text:
            return
        doc = Doc(f"lore:{name}", "lore", text, 0, 1)
        self._lore = [d for d in self._lore if d.key != doc.key] + [doc]
        self._vecs.pop(doc.key, None)
        self._put(doc)

    # -- searching ----------------------------------------------------------------------------

    def search(
        self,
        cid: str,
        query: str,
        k: int = 3,
        now: int = 0,
        exclude: Iterable[str] = (),
        extra: Iterable[tuple[str, str]] = (),
        semantic: str | None = None,
        lore: bool = True,
        max_lore: int | None = None,
        weight: Callable[[Doc], float] | None = None,
    ) -> list[Doc]:
        """`query` drives keywords; `semantic` (default: the same text) is what gets embedded, so a caller can
        keep it stable across turns and reuse the cached vector. `lore=False` leaves shared lore out;
        `max_lore` caps how many of the results may be lore; `weight` scales each doc's score."""
        qtokens = tokenize(query)
        sem = query if semantic is None else semantic
        qnorm = " ".join(sem.lower().split())
        skip = set(exclude)
        docs: list[Doc] = [*self._docs.get(cid, ()), *(self._lore if lore else ())]
        docs = [d for d in docs if d.key not in skip and d.text not in skip]
        extras = []
        for kind, text in extra:
            if text.strip() and text not in skip:
                doc = Doc(f"extra:{len(extras)}", kind, text.strip(), now, 1)
                extras.append(doc)
        docs += extras
        if not docs or not (qtokens or qnorm):
            return []

        qvec = self._qvecs.get(qnorm) if qnorm else None
        if qvec is None and qnorm and qnorm not in self._pending_q:
            self._pending_q[qnorm] = sem.strip()
            while len(self._pending_q) > MAX_QUERY_CACHE:  # embedder down: don't queue forever
                self._pending_q.pop(next(iter(self._pending_q)))

        bm25 = self._bm25(qtokens, docs)
        top = bm25.max()
        if top > 0:
            bm25 = bm25 / top
        score = bm25.copy()
        if qvec is not None:
            have = np.array([d.key in self._vecs for d in docs])
            if have.any():
                mat = np.stack([self._vecs[d.key] for d, h in zip(docs, have) if h])
                cos = np.clip(mat @ qvec, 0.0, 1.0)
                score[have] = 0.5 * bm25[have] + 0.5 * cos
        age = np.array([0 if d.kind == "lore" or d.key.startswith("extra:") else max(0, now - d.tick) for d in docs])
        imp = np.array([d.importance for d in docs])
        score = score * (1 + 0.15 * imp) * 0.5 ** (age / HALF_LIFE)
        if weight is not None:
            score = score * np.array([weight(d) for d in docs])

        order = np.argsort(-score, kind="stable")
        out: list[Doc] = []
        seen: set[str] = set()
        lore_left = len(docs) if max_lore is None else max_lore
        for i in order:
            if score[i] <= 0 or len(out) >= k:
                break
            if docs[i].kind == "lore" and lore_left <= 0:
                continue
            if docs[i].text not in seen:  # identical texts: keep the best-scoring one
                seen.add(docs[i].text)
                out.append(docs[i])
                lore_left -= docs[i].kind == "lore"
        return out

    def _bm25(self, qtokens: list[str], docs: list[Doc]) -> np.ndarray:
        n = len(docs)
        scores = np.zeros(n)
        terms = set(qtokens)
        if not terms:
            return scores
        toks = [self._tokens[d.key] if d.key in self._tokens else tokenize(d.text) for d in docs]
        lens = np.array([len(t) for t in toks], dtype=float)
        avg = lens.mean() or 1.0
        counts = [Counter(t) for t in toks]
        for term in terms:
            tf = np.array([c.get(term, 0) for c in counts], dtype=float)
            df = int((tf > 0).sum())
            if not df:
                continue
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            scores += idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * lens / avg))
        return scores

    # -- embeddings ---------------------------------------------------------------------------

    def pending(self, limit: int = 128) -> list[tuple[str, str]]:
        """(key, text) for queries (key "q:<normalized query>"), then docs, still lacking vectors.
        Queries come first: they are few and cheap, and a restart shouldn't wait for every doc batch."""
        out: list[tuple[str, str]] = [(f"q:{q}", t) for q, t in list(self._pending_q.items())[:limit]]
        if len(out) >= limit:
            return out
        for doc in [*self._lore, *(d for docs in self._docs.values() for d in docs)]:
            if doc.key not in self._vecs:
                out.append((doc.key, doc.text))
                if len(out) >= limit:
                    break
        return out

    def set_vectors(self, items: list[tuple[str, list[float]]]) -> None:
        for key, vec in items:
            arr = np.asarray(vec, dtype=np.float32)
            norm = float(np.linalg.norm(arr))
            if not norm:
                continue
            arr = arr / norm
            if key.startswith("q:"):
                qnorm = key[2:]
                self._pending_q.pop(qnorm, None)
                self._qvecs.pop(qnorm, None)
                self._qvecs[qnorm] = arr
                while len(self._qvecs) > MAX_QUERY_CACHE:
                    self._qvecs.pop(next(iter(self._qvecs)))
            elif key in self._tokens:  # ignore docs evicted while embedding
                self._vecs[key] = arr

    # -- saving -------------------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "docs": {c: [[d.kind, d.text, d.tick, d.importance] for d in ds] for c, ds in self._docs.items()},
        }  # lore is not saved: the server reloads it from code

    def load(self, d: dict) -> None:
        self.__init__(self.cap)
        for cid, rows in d.get("docs", {}).items():
            for kind, text, tick, importance in rows:
                self.add(cid, kind, text, tick, importance)
        for name, text in d.get("lore", []):
            self.add_lore(name, text)


class VoyageEmbedder:
    def __init__(
        self,
        api_key: str,
        model: str = "voyage-3.5-lite",
        dims: int = 512,
        post: Callable[[str, dict, dict], Awaitable[dict]] | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.dims = dims
        self._post = post or self._http_post

    @staticmethod
    async def _http_post(url: str, headers: dict, payload: dict) -> dict:
        import aiohttp

        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        out: list[list[float]] = []
        headers = {"Authorization": f"Bearer {self.api_key}"}
        for i in range(0, len(texts), BATCH):
            payload = {
                "input": texts[i : i + BATCH],
                "model": self.model,
                "input_type": input_type,
                "output_dimension": self.dims,
            }
            data = (await self._post(VOYAGE_URL, headers, payload))["data"]
            out.extend(row["embedding"] for row in sorted(data, key=lambda r: r["index"]))
        return out


async def embed_pending(index: RecallIndex, embedder) -> int:
    """Embed one batch of what `index` is waiting on. Returns how many vectors were set. Errors propagate: the
    caller decides how to report them and when to retry; keyword search carries on regardless."""
    items = index.pending(BATCH)
    docs = [(k, t) for k, t in items if not k.startswith("q:")]
    queries = [(k, t) for k, t in items if k.startswith("q:")]
    done = 0
    for group, input_type in ((docs, "document"), (queries, "query")):
        if not group:
            continue
        vecs = await embedder.embed([t for _, t in group], input_type)
        index.set_vectors([(k, v) for (k, _), v in zip(group, vecs)])
        done += len(group)
    return done
