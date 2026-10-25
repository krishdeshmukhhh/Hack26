#!/usr/bin/env bash
# Check every 60 s until an allowed GPU is idle, then start serve.sh on it.
#   tmux new -d -s curio "/path/to/wait_and_serve.sh"
set -euo pipefail
source "$(dirname "$0")/common.sh"

until gpu="$(first_idle_gpu)"; do
    echo "$(date '+%H:%M:%S') no idle GPU among $ALLOWED_GPUS; checking again in 60 s"
    sleep 60
done
exec "$HERE/serve.sh" "$gpu"
