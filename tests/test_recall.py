import pytest

from swarmworld.mind.recall import RecallIndex, VoyageEmbedder, embed_pending


def make_index(n_noise: int = 50) -> RecallIndex:
    idx = RecallIndex()
    for i in range(n_noise):
        idx.add("a", "memory", f"walked past boulder number {i} near the pond", tick=i)
    idx.add("a", "memory", "the clay bank lies north of the old oak", tick=20)
    return idx


def test_keyword_recall_finds_the_clay():
    idx = make_index()
    hits = idx.search("a", "where is the clay", now=60)
    assert hits and "clay" in hits[0].text


def test_importance_and_recency_break_ties():
    idx = RecallIndex()
    idx.add("a", "memory", "found berries by the creek", tick=100, importance=1)
    idx.add("a", "memory", "found berries by the creek", tick=100, importance=3)
    assert idx.search("a", "berries creek", k=2, now=100)[0].importance == 3
    idx = RecallIndex()
    idx.add("a", "memory", "found berries by the creek", tick=10)
    idx.add("a", "memory", "found berries by the creek", tick=900)
    assert idx.search("a", "berries creek", k=2, now=1000)[0].tick == 900


def test_cap_evicts_least_important_oldest():
    idx = RecallIndex(cap=3)
    idx.add("a", "memory", "alpha one", tick=1, importance=1)
    idx.add("a", "memory", "beta two", tick=2, importance=1)
    idx.add("a", "memory", "gamma three", tick=3, importance=5)
    idx.add("a", "memory", "delta four", tick=4, importance=1)
    texts = {d[1] for d in idx.to_dict()["docs"]["a"]}
    assert texts == {"beta two", "gamma three", "delta four"}


def test_creatures_only_recall_their_own_but_share_lore():
    idx = RecallIndex()
    idx.add("a", "memory", "my secret hollow stump", tick=1)
    idx.add("b", "memory", "my other hollow log", tick=1)
    idx.add_lore("fire", "fire needs dry wood and a spark")
    assert [d.text for d in idx.search("a", "hollow", now=5)] == ["my secret hollow stump"]
    assert [d.text for d in idx.search("b", "spark fire", now=5)] == ["fire needs dry wood and a spark"]
    assert [d.text for d in idx.search("a", "spark fire", now=5)] == ["fire needs dry wood and a spark"]


def test_extra_and_exclude():
    idx = RecallIndex()
    idx.add("a", "memory", "plain thing", tick=1)
    hits = idx.search("a", "recipe hut", extra=[("recipe", "hut needs sticks")], now=5)
    assert [d.text for d in hits] == ["hut needs sticks"]
    assert idx.search("a", "recipe hut", extra=[("recipe", "hut needs sticks")], exclude=["hut needs sticks"]) == []


def vectors_for(idx: RecallIndex, table: dict[str, list[float]]):
    items = []
    for key, text in idx.pending():
        items.append((key, table[text]))
    idx.set_vectors(items)


def test_vectors_find_meaning_without_shared_words():
    idx = RecallIndex()
    idx.add("a", "memory", "shelter from rain", tick=1)
    idx.add("a", "memory", "picked red berries", tick=1)
    idx.search("a", "a roof over our heads", now=2)  # queues the query
    vectors_for(idx, {
        "shelter from rain": [1.0, 0.0],
        "picked red berries": [0.0, 1.0],
        "a roof over our heads": [0.9, 0.1],
    })
    hits = idx.search("a", "a roof over our heads", k=1, now=2)
    assert [d.text for d in hits] == ["shelter from rain"]


def test_uncached_query_uses_keywords_and_is_queued():
    idx = RecallIndex()
    idx.add("a", "memory", "the clay bank", tick=1)
    idx.set_vectors([(k, [1.0, 0.0]) for k, _ in idx.pending()])
    assert idx.pending() == []
    hits = idx.search("a", "clay", now=2)
    assert hits and hits[0].text == "the clay bank"
    assert ("q:clay", "clay") in idx.pending()


class Boom:
    async def embed(self, texts, input_type):
        raise RuntimeError("network down")


class Fake:
    def __init__(self):
        self.calls = []

    async def embed(self, texts, input_type):
        self.calls.append((input_type, list(texts)))
        return [[1.0, 0.0] for _ in texts]


async def test_embedder_failure_falls_back_to_keywords():
    idx = make_index(3)
    with pytest.raises(RuntimeError):  # the caller (the embed loop) decides how to log and when to retry
        await embed_pending(idx, Boom())
    assert idx.search("a", "clay", now=60)[0].text.startswith("the clay bank")
    assert idx.pending()  # still waiting


async def test_embed_pending_fills_docs_and_queries():
    idx = RecallIndex()
    idx.add("a", "memory", "the clay bank", tick=1)
    idx.search("a", "clay", now=2)
    fake = Fake()
    assert await embed_pending(idx, fake) == 2
    assert {c[0] for c in fake.calls} == {"document", "query"}
    assert idx.pending() == []
    assert await embed_pending(idx, fake) == 0


def test_index_roundtrip():
    idx = make_index(3)
    idx.add_lore("fire", "fire needs dry wood")
    other = RecallIndex()
    other.load(idx.to_dict())
    assert other.to_dict() == idx.to_dict()
    assert "lore" not in idx.to_dict()  # reloaded from code, not saved
    assert other.search("a", "clay", now=60)[0].text.startswith("the clay bank")
    assert not other.search("zed", "dry wood", now=60)
    old = RecallIndex()
    old.load({"docs": {}, "lore": [["fire", "fire needs dry wood"]]})  # older saves still load
    assert old.search("zed", "dry wood", now=60)[0].kind == "lore"
    assert other.pending()  # vectors recomputed after restart


async def test_voyage_embedder_batches_and_parses():
    sent = []

    async def post(url, headers, payload):
        sent.append(payload)
        n = len(payload["input"])
        return {"data": [{"embedding": [float(i)], "index": i} for i in reversed(range(n))]}

    emb = VoyageEmbedder("k", post=post)
    out = await emb.embed([f"t{i}" for i in range(130)], "document")
    assert [len(p["input"]) for p in sent] == [128, 2]
    assert sent[0]["model"] == "voyage-3.5-lite" and sent[0]["output_dimension"] == 512
    assert sent[0]["input_type"] == "document"
    assert len(out) == 130 and out[0] == [0.0] and out[127] == [127.0]


def test_pending_lists_queries_before_docs():
    idx = make_index(200)
    idx.search("a", "where is the clay", now=60)
    keys = [k for k, _ in idx.pending(128)]
    assert keys[0].startswith("q:")


def test_pending_queries_are_capped():
    from swarmworld.mind.recall import MAX_QUERY_CACHE

    idx = make_index(3)
    for i in range(MAX_QUERY_CACHE * 3):
        idx.search("a", f"clay question number {i}", now=60)
    queued = [k for k, _ in idx.pending(10_000) if k.startswith("q:")]
    assert len(queued) == MAX_QUERY_CACHE
    assert queued[-1] == f"q:clay question number {MAX_QUERY_CACHE * 3 - 1}"  # newest kept, oldest dropped


def test_search_returns_each_text_once():
    idx = RecallIndex()
    for t in (10, 20, 30):
        idx.add("a", "memory", "found berries by the creek", tick=t)
    idx.add("a", "memory", "berries grow near the creek bend", tick=5)
    texts = [d.text for d in idx.search("a", "berries creek", k=3, now=40)]
    assert len(texts) == len(set(texts)) == 2


def test_semantic_text_is_what_gets_queued():
    idx = make_index(3)
    idx.search("a", "make a pot oak tree Mara", now=60, semantic="make a pot")
    assert [k for k, _ in idx.pending() if k.startswith("q:")] == ["q:make a pot"]
    assert idx.search("a", "clay", now=60, lore=False)


def test_max_lore_caps_shared_lore():
    idx = RecallIndex()
    for name in ("fire", "flint", "kindling"):
        idx.add_lore(name, f"{name}: fire needs dry wood")
    idx.add("a", "memory", "dry wood by the fire pit", tick=1)
    assert sum(d.kind == "lore" for d in idx.search("a", "fire dry wood", k=5, now=2)) == 3
    hits = idx.search("a", "fire dry wood", k=5, now=2, max_lore=1)
    assert [d.kind for d in hits].count("lore") == 1 and any(d.kind == "memory" for d in hits)
