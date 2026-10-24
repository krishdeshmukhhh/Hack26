# Shared helpers for the Curio server scripts. Sourced, not run.

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -f "$HERE/curio.env" ]]; then
    echo "missing $HERE/curio.env - copy curio.env.example and edit it" >&2
    exit 2
fi
# shellcheck source=/dev/null
source "$HERE/curio.env"

LOG_DIR="$WORK_DIR/logs"
API_KEY_FILE="$WORK_DIR/api_key"

# Make nvidia-smi indices match CUDA's numbering.
export CUDA_DEVICE_ORDER=PCI_BUS_ID

if ! nvidia-smi -L > /dev/null 2>&1; then
    echo "nvidia-smi isn't working on this machine:" >&2
    nvidia-smi -L >&2 || true
    exit 2
fi

is_allowed_gpu() {
    local g
    for g in $ALLOWED_GPUS; do [[ "$g" == "$1" ]] && return 0; done
    return 1
}

gpu_uuid() {
    nvidia-smi --query-gpu=index,uuid --format=csv,noheader \
        | awk -F', ' -v i="$1" '$1 == i { print $2 }'
}

gpu_pids() {
    nvidia-smi --query-compute-apps=gpu_uuid,pid --format=csv,noheader \
        | awk -F', ' -v u="$(gpu_uuid "$1")" '$1 == u { print $2 }'
}

# Idle = no compute processes at all and under 2 GB of memory in use.
gpu_is_idle() {
    local used
    used="$(nvidia-smi -i "$1" --query-gpu=memory.used --format=csv,noheader,nounits | tr -d ' ')"
    [[ -z "$(gpu_pids "$1")" && "$used" -lt 2048 ]]
}

first_idle_gpu() {
    local g
    for g in $ALLOWED_GPUS; do
        if gpu_is_idle "$g"; then echo "$g"; return 0; fi
    done
    return 1
}
