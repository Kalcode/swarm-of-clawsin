"""Checks for the student, run inside mlx-lm's environment (scripts/train_student.sh runs both):

    uvx --from mlx-lm==0.32.2 python scripts/check_student.py template MODEL DATA_DIR --max-seq-length 4096
    uvx --from mlx-lm==0.32.2 python scripts/check_student.py answer MODEL DATA_DIR

template: will the student see, when it serves, exactly what it was trained on? The live brain asks with
chat_template_kwargs {"enable_thinking": false} (swarmworld/node/brain.py), so the server renders the prompt with
enable_thinking=False and the model continues from there. mlx_lm.lora renders each whole training example with the
chat template's defaults. For a sample of examples this checks, token by token, that the training sequence begins
with the serving prompt and goes on with the answer; and, for every example, that it fits --max-seq-length (mlx-lm
would cut a longer one at the end, losing the answer it should learn). Exits 1 if either fails.

answer: the model answers one held-out prompt as the live brain would ask it (thinking off); prints the answer and
whether it is one JSON object with the intention's fields. Informational: it never fails the run."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SAMPLE = 200
FIELDS = {"thought", "action", "target", "items", "text", "count", "goal", "speech"}


def examples(data: Path) -> list[tuple[str, list[dict]]]:
    out = []
    for split in ("train", "valid"):
        path = data / f"{split}.jsonl"
        if path.exists():
            out += [(split, json.loads(line)["messages"]) for line in path.read_text().splitlines() if line.strip()]
    return out


def serving_prompt(tok, messages: list[dict], tokenize: bool = True):
    return tok.apply_chat_template(messages, add_generation_prompt=True, enable_thinking=False, tokenize=tokenize,
                                   return_dict=False)


def check_template(model: str, data: Path, max_seq: int) -> int:
    from mlx_lm.utils import load_tokenizer

    tok = load_tokenizer(model)
    rows = examples(data)
    if not rows:
        print(f"No examples in {data}")
        return 1
    step = max(1, len(rows) // SAMPLE)
    mismatched = 0
    for split, msgs in rows[::step]:
        full = tok.apply_chat_template(msgs, return_dict=False)  # exactly what mlx_lm.lora trains on
        serve = serving_prompt(tok, msgs[:-1])
        rest = tok.decode(full[len(serve):])
        if full[:len(serve)] != serve or not rest.startswith(msgs[-1]["content"]):
            mismatched += 1
            if mismatched == 1:
                text_full = tok.apply_chat_template(msgs, tokenize=False)
                text_serve = serving_prompt(tok, msgs[:-1], tokenize=False)
                print("MISMATCH between training and serving renderings (first case):")
                print("  trained on (tail):", repr(text_full[-300:]))
                print("  served     (tail):", repr(text_serve[-200:]))
    lengths = [len(tok.apply_chat_template(msgs, return_dict=False)) for _, msgs in rows]
    long = sum(n > max_seq for n in lengths)
    checked = len(rows[::step])
    print(f"Template: {checked - mismatched}/{checked} sampled examples train on exactly the serving prompt "
          f"(enable_thinking=False) followed by the answer.")
    sample = rows[0][1]
    text = tok.apply_chat_template(sample, tokenize=False)
    at = text.rfind(sample[-1]["content"])
    print("  Where the answer begins, as trained:", repr(text[max(0, at - 60):at + 30]))
    print(f"Lengths: {len(lengths)} examples, mean {sum(lengths) / len(lengths):.0f} tokens, longest {max(lengths)}; "
          f"{long} longer than --max-seq-length {max_seq}.")
    if mismatched:
        print("The student would be trained on a different text than it is served: fix the export or the template "
              "before training (see docs/distillation.md).")
    if long:
        print(f"Raise MAX_SEQ_LENGTH above {max(lengths)}: a longer example is cut at the end and loses its answer.")
    return 1 if mismatched or long else 0


def check_answer(model: str, data: Path) -> int:
    from mlx_lm import generate, load

    rows = [r for r in examples(data) if r[0] == "valid"] or examples(data)
    if not rows:
        print(f"No examples in {data}")
        return 0
    msgs = rows[0][1]
    m, tok = load(model)
    reply = generate(m, tok, serving_prompt(tok, msgs[:-1], tokenize=False), max_tokens=400)
    print("The student, asked one held-out prompt as a live creature would ask it:")
    print("  " + reply.strip()[:600])
    try:
        obj = json.loads(reply.strip())
        ok = isinstance(obj, dict) and FIELDS <= set(obj)
    except json.JSONDecodeError:
        ok = False
    print("  -> " + ("one JSON object with every intention field" if ok else
                     "NOT a clean intention JSON object (fine for a smoke test; a real student should manage it)"))
    print("  the teacher said:", msgs[-1]["content"][:300])
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Swarm World student checks (run in mlx-lm's environment)")
    ap.add_argument("check", choices=["template", "answer"])
    ap.add_argument("model", help="Hugging Face repo or local MLX model folder")
    ap.add_argument("data", type=Path, help="folder with train.jsonl and valid.jsonl (from export_training.py)")
    ap.add_argument("--max-seq-length", type=int, default=4096)
    args = ap.parse_args()
    if args.check == "template":
        sys.exit(check_template(args.model, args.data, args.max_seq_length))
    sys.exit(check_answer(args.model, args.data))


if __name__ == "__main__":
    main()
