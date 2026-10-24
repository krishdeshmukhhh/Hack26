#!/bin/bash
# Serve a vision LLM for Curio on one GPU with vLLM.
#
#   cd ~/curio && sbatch vllm.sbatch   # submit (logs/ is relative to here)
#   squeue --me                   # see which node it landed on
#   tail -f ~/curio/logs/vllm-<jobid>.out
#
# Fill in the #SBATCH lines your cluster needs (partition, account, GPU type).
#SBATCH --job-name=curio-vllm
#SBATCH --partition=CHANGE_ME
#SBATCH --account=CHANGE_ME
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=04:00:00
#SBATCH --output=logs/vllm-%j.out

set -euo pipefail

MODEL="${MODEL:-Qwen/Qwen3-VL-32B-Instruct}"
PORT="${PORT:-8000}"
CURIO_DIR="$HOME/curio"

# Big model weights go on scratch/project storage, not your home quota.
export HF_HOME="${HF_HOME:-CHANGE_ME_SCRATCH_DIR/hf}"

# Load whatever your cluster needs for Python + CUDA, e.g.:
# module load cuda/12.4
source "$CURIO_DIR/venv/bin/activate"

API_KEY="$(cat "$CURIO_DIR/api_key")"

echo "node=$(hostname) port=$PORT model=$MODEL"
echo "tunnel from your laptop with:"
echo "  ssh -N -L 8000:localhost:$PORT -J $USER@<login-node> $USER@$(hostname)"

# Bind to 127.0.0.1 so only an SSH tunnel into this node can reach the
# server; the API key is a second layer on a shared machine.
exec vllm serve "$MODEL" \
    --host 127.0.0.1 \
    --port "$PORT" \
    --api-key "$API_KEY" \
    --max-model-len 32768 \
    --limit-mm-per-prompt '{"image": 4}' \
    --gpu-memory-utilization 0.90
