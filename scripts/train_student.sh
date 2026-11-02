#!/usr/bin/env bash
# Train the student mind: mlx-lm LoRA on exported teacher decisions, then fuse it into a model oMLX can serve.
#   scripts/train_student.sh data/student/night1                  # train, fuse, quantize into ~/models/swarm-student-<date>
#   ITERS=300 scripts/train_student.sh data/student/night1        # a shorter run
#   RESUME=1 scripts/train_student.sh data/student/night1         # ITERS more steps from the adapter saved last time
# mlx-lm runs through uvx (pinned: MLX_LM), so the project itself doesn't depend on MLX (the gaming PC can't run it).
# Settings (environment variables):
#   BASE_MODEL      mlx-community/Qwen3-1.7B-bf16 (Apache 2.0). Trained in bf16, not 4-bit: fusing LoRA into 4-bit
#                   weights re-rounds them to the same grid and loses most of what was learned; quantizing after the
#                   fuse keeps it. A quantized BASE_MODEL works too (fused with --dequantize, then QBITS).
#   OUT             ~/models/swarm-student-<yyyymmdd>, the fused model (must not exist yet)
#   QBITS           8: quantize the fused model to 8 bits (about 1.9 GB); 4 is smaller and faster; 0 keeps bf16 (3.4 GB)
#   EPOCHS          1, or ITERS: training steps (default EPOCHS x train lines / BATCH_SIZE, which has no upper bound:
#                   a night's export can be 10k lines, about 10 h; ITERS=4000 is about 4 h)
#   SECS_PER_EXAMPLE 3.5: for the time estimate printed before training (assumed for Qwen3-1.7B on an M1 Max; put
#                   in what you measure)
#   BATCH_SIZE      1  GRAD_ACCUM 8 (one optimizer step per 8 examples)
#   MAX_SEQ_LENGTH  4096 (prompts run 2-3k tokens; mlx-lm's default 2048 would cut off the answers)
#   NUM_LAYERS      16 (LoRA on the last 16 of Qwen3-1.7B's 28 layers; the backward pass stops there)
#   LORA_RANK 16  LORA_SCALE 20  LORA_DROPOUT 0.05  LEARNING_RATE 2e-5 (cosine decay to a tenth, after a warmup)
#   STEPS_PER_EVAL 200  VAL_BATCHES 50  SAVE_EVERY 200  SEED 0
#   ADAPTERS        DATA_DIR/adapters-<name of OUT> (the LoRA adapter and its training config; kept). It and the
#                   bf16 fuse (DATA_DIR/fused-bf16, deleted after quantizing) stay out of ~/models, where oMLX looks.
#   MLX_LM          mlx-lm==0.32.2
# Memory, beside a live world on a 32 GB M1 Max: the smoke test (Qwen3-0.6B bf16, 1.3k-token examples, BATCH_SIZE 1)
# peaked at 3.3 GB. Scaled to Qwen3-1.7B (3.4 GB of weights) and 2.5-3k-token prompts that is about 8-10 GB at
# BATCH_SIZE 1 (an estimate; 2 would pass 12 GB). mlx-lm 0.32 doesn't print memory: watch Activity Monitor at first.
# Time: about 0.6 s per step for the 0.6B smoke test, so roughly 3-4 s per example for 1.7B: ~1000 examples an hour.
# Before training, scripts/check_student.py checks that every example fits MAX_SEQ_LENGTH and that the training text is
# exactly the serving prompt (chat template with enable_thinking=False, as the live brain asks) plus the answer.
set -euo pipefail

if [[ -z "${1:-}" || ! -s "${1:-}/train.jsonl" ]]; then
  echo "usage: scripts/train_student.sh DATA_DIR   (a folder from scripts/export_training.py, with train.jsonl)"; exit 1
fi
DATA="$(cd "$1" && pwd)"
cd "$(dirname "$0")/.."
if [[ ! -s "$DATA/valid.jsonl" ]]; then
  echo "$DATA/valid.jsonl is empty: mlx-lm needs a validation set. Export two or more episodes."; exit 1
fi
BASE_MODEL="${BASE_MODEL:-mlx-community/Qwen3-1.7B-bf16}"
OUT="${OUT:-$HOME/models/swarm-student-$(date +%Y%m%d)}"
QBITS="${QBITS:-8}"
EPOCHS="${EPOCHS:-1}"
BATCH_SIZE="${BATCH_SIZE:-1}"
GRAD_ACCUM="${GRAD_ACCUM:-8}"
MAX_SEQ_LENGTH="${MAX_SEQ_LENGTH:-4096}"
NUM_LAYERS="${NUM_LAYERS:-16}"
LORA_RANK="${LORA_RANK:-16}"
LORA_SCALE="${LORA_SCALE:-20}"
LORA_DROPOUT="${LORA_DROPOUT:-0.05}"
LEARNING_RATE="${LEARNING_RATE:-2e-5}"
STEPS_PER_EVAL="${STEPS_PER_EVAL:-200}"
VAL_BATCHES="${VAL_BATCHES:-50}"
SAVE_EVERY="${SAVE_EVERY:-200}"
SEED="${SEED:-0}"
ADAPTERS="${ADAPTERS:-$DATA/adapters-$(basename "$OUT")}"
MLX_LM="${MLX_LM:-mlx-lm==0.32.2}"
SECS_PER_EXAMPLE="${SECS_PER_EXAMPLE:-3.5}"
LINES=$(wc -l < "$DATA/train.jsonl" | tr -d ' ')
ITERS="${ITERS:-$(( (LINES * EPOCHS + BATCH_SIZE - 1) / BATCH_SIZE ))}"
UPDATES=$(( ITERS / GRAD_ACCUM > 0 ? ITERS / GRAD_ACCUM : 1 ))
WARMUP=$(( UPDATES / 10 < 100 ? UPDATES / 10 : 100 ))
DECAY=$(( UPDATES - WARMUP > 0 ? UPDATES - WARMUP : 1 ))
MLX=(uvx --from "$MLX_LM")

if [[ -e "$OUT" ]]; then
  echo "$OUT already exists: remove it or set OUT."; exit 1
fi
if [[ -n "${RESUME:-}" && ! -s "$ADAPTERS/adapters.safetensors" ]]; then
  echo "RESUME=1 but there is no $ADAPTERS/adapters.safetensors"; exit 1
fi
if [[ -z "${RESUME:-}" && -e "$ADAPTERS/adapters.safetensors" ]]; then
  echo "$ADAPTERS already holds an adapter: RESUME=1 to go on from it, or remove it or set ADAPTERS."; exit 1
fi

echo "Student: $BASE_MODEL + LoRA on $DATA ($LINES train lines), $ITERS steps of $BATCH_SIZE, an update every $GRAD_ACCUM"
EXAMPLES=$(( ITERS * BATCH_SIZE ))
ESTIMATE=$(awk -v n="$EXAMPLES" -v t="$SECS_PER_EXAMPLE" \
  'BEGIN { s = n * t; if (s < 3600) printf "~%d min", (s + 30) / 60; else printf "~%.1f h", s / 3600 }')
echo "Estimated training time: $EXAMPLES examples x ~$SECS_PER_EXAMPLE s = $ESTIMATE (cap it with ITERS, e.g. ITERS=4000 for about 4 h)"
echo "  (SECS_PER_EXAMPLE is assumed for Qwen3-1.7B on an M1 Max; set what you measure)"
"${MLX[@]}" python scripts/check_student.py template "$BASE_MODEL" "$DATA" --max-seq-length "$MAX_SEQ_LENGTH"

mkdir -p "$ADAPTERS"
CONFIG="$ADAPTERS/train.yaml"
cat > "$CONFIG" <<EOF
# written by scripts/train_student.sh $(date '+%Y-%m-%d %H:%M')
model: "$BASE_MODEL"
train: true
data: "$DATA"
fine_tune_type: lora
optimizer: adamw
seed: $SEED
num_layers: $NUM_LAYERS
batch_size: $BATCH_SIZE
grad_accumulation_steps: $GRAD_ACCUM
iters: $ITERS
val_batches: $VAL_BATCHES
learning_rate: $LEARNING_RATE
steps_per_report: 10
steps_per_eval: $STEPS_PER_EVAL
save_every: $SAVE_EVERY
adapter_path: "$ADAPTERS"
max_seq_length: $MAX_SEQ_LENGTH
grad_checkpoint: true
mask_prompt: true
lora_parameters:
  rank: $LORA_RANK
  scale: $LORA_SCALE
  dropout: $LORA_DROPOUT
lr_schedule:
  name: cosine_decay
  warmup: $WARMUP
  warmup_init: 0.0
  arguments: [$LEARNING_RATE, $DECAY, $(awk "BEGIN { print $LEARNING_RATE / 10 }")]
EOF
RESUME_ARGS=()
[[ -n "${RESUME:-}" ]] && RESUME_ARGS=(--resume-adapter-file "$ADAPTERS/adapters.safetensors")
"${MLX[@]}" mlx_lm.lora -c "$CONFIG" "${RESUME_ARGS[@]+"${RESUME_ARGS[@]}"}"

FUSED="$DATA/fused-bf16"
rm -rf "$FUSED"
"${MLX[@]}" mlx_lm.fuse --model "$BASE_MODEL" --adapter-path "$ADAPTERS" --save-path "$FUSED" --dequantize
if [[ "$QBITS" == "0" ]]; then
  mv "$FUSED" "$OUT"
else
  "${MLX[@]}" mlx_lm.convert --hf-path "$FUSED" --mlx-path "$OUT" -q --q-bits "$QBITS" --q-group-size 64
  rm -rf "$FUSED"
fi
TEMPLATE_OK=1
"${MLX[@]}" python scripts/check_student.py template "$OUT" "$DATA" --max-seq-length "$MAX_SEQ_LENGTH" || TEMPLATE_OK=0
"${MLX[@]}" python scripts/check_student.py answer "$OUT" "$DATA" || true
echo
if [[ "$TEMPLATE_OK" == 0 ]]; then
  echo "Saved $OUT (adapter in $ADAPTERS), but its own chat template, the one oMLX serves with, renders differently"
  echo "from what it was trained on (see the check above): the student is NOT ready. Don't serve it until that's fixed."
  exit 2
fi
echo "Student ready: $OUT (adapter and training config in $ADAPTERS)."
echo "oMLX serves it as '$(basename "$OUT")' (restart oMLX if it isn't listed yet). Live trial: docs/distillation.md."
