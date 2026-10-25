#!/usr/bin/env bash
# Start vLLM for Curio on an idle allowed GPU. Refuses busy or
# disallowed GPUs. Run it inside tmux so it outlives your SSH session:
#   tmux new -d -s curio "/path/to/serve.sh [gpu]"
# DRY_RUN=1 ./serve.sh checks everything and prints the command only.
set -euo pipefail
source "$(dirname "$0")/common.sh"

problems=0
fail() { echo "ERROR: $*" >&2; problems=$((problems + 1)); }

if [[ $# -ge 1 ]]; then
    GPU="$1"
    if ! is_allowed_gpu "$GPU"; then
        echo "GPU $GPU is not in ALLOWED_GPUS ($ALLOWED_GPUS)" >&2
        exit 2
    fi
    if ! gpu_is_idle "$GPU"; then
        echo "GPU $GPU is busy; refusing to start" >&2
        "$HERE/gpu_status.sh" || true
        exit 3
    fi
elif ! GPU="$(first_idle_gpu)"; then
    fail "no idle GPU among $ALLOWED_GPUS"
    GPU="none"
fi

[[ -f "$API_KEY_FILE" ]] || fail "missing $API_KEY_FILE (openssl rand -hex 16 > it; chmod 600 it)"
[[ -f "$VENV/bin/activate" ]] || fail "no venv at $VENV"
index="$MODEL_PATH/model.safetensors.index.json"
if [[ -f "$index" ]]; then
    while read -r shard; do
        shard="${shard%$'\r'}"
        [[ -f "$MODEL_PATH/$shard" ]] || fail "missing weight shard $shard"
    done < <(python3 -c 'import json, sys
print("\n".join(sorted(set(json.load(open(sys.argv[1]))["weight_map"].values()))))' "$index")
else
    fail "no weights at $MODEL_PATH"
fi

# Shared machine: take the next free port if the configured one is in use.
while ss -ltn "sport = :$PORT" | grep -q LISTEN; do PORT=$((PORT + 1)); done

mkdir -p "$LOG_DIR" "$CACHE_ROOT" "$WORK_DIR/tmp"
export CUDA_VISIBLE_DEVICES="$GPU"
export HF_HOME="$CACHE_ROOT/hf" HF_HUB_OFFLINE=1
export XDG_CACHE_HOME="$CACHE_ROOT/xdg" VLLM_CACHE_ROOT="$CACHE_ROOT/vllm"
export TRITON_CACHE_DIR="$CACHE_ROOT/triton" FLASHINFER_WORKSPACE_BASE="$CACHE_ROOT/flashinfer"
# vLLM puts IPC sockets in TMPDIR, so keep it on a local disk.
export TMPDIR="$WORK_DIR/tmp"
# DeepGEMM JIT-compiles FP8 kernels with the system nvcc and needs >= 12.9.
# The lab machines have older CUDA toolkits and crash at startup without this.
export VLLM_USE_DEEP_GEMM=0

cmd=(vllm serve "$MODEL_PATH"
    --served-model-name "$SERVED_MODEL_NAME"
    --host 127.0.0.1 --port "$PORT"
    --max-model-len "$MAX_MODEL_LEN"
    --limit-mm-per-prompt "{\"image\": $MAX_IMAGES}"
    --gpu-memory-utilization "$GPU_MEM_UTIL")

# Latency knobs (see curio.env.example). Defaults live here so an older
# curio.env without these lines keeps working.
# Prefix caching reuses the KV cache of the long, identical system prompt.
if [[ "${ENABLE_PREFIX_CACHING:-1}" == "1" ]]; then
    cmd+=(--enable-prefix-caching)
else
    cmd+=(--no-enable-prefix-caching)
fi
[[ -z "${MAX_NUM_SEQS:-}" ]] || cmd+=(--max-num-seqs "$MAX_NUM_SEQS")
[[ -z "${MM_PROCESSOR_KWARGS:-}" ]] || cmd+=(--mm-processor-kwargs "$MM_PROCESSOR_KWARGS")

if [[ -n "${DRY_RUN:-}" ]]; then
    echo "GPU=$GPU PORT=$PORT"
    printf '%q ' "${cmd[@]}"
    echo
    exit $(( problems > 0 ))
fi
[[ $problems -eq 0 ]] || exit 1

log="$LOG_DIR/vllm-$(date +%Y%m%d-%H%M%S).log"
echo "GPU=$GPU PORT=$PORT log=$log"
echo "laptop tunnel: ssh -N -L 8000:localhost:$PORT $USER@$(hostname -f)"
# shellcheck source=/dev/null
source "$VENV/bin/activate"
# Pass the key through the environment so it doesn't show up in `ps`.
VLLM_API_KEY="$(cat "$API_KEY_FILE")"
export VLLM_API_KEY
"${cmd[@]}" 2>&1 | tee "$log"
