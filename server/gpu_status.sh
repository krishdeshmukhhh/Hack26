#!/usr/bin/env bash
# Show the GPUs you're allowed to use and whether each is idle.
# Exit 0 if at least one is idle, 1 otherwise.
set -euo pipefail
source "$(dirname "$0")/common.sh"

printf "%-4s %9s %9s %5s %5s %-5s %s\n" GPU USED_MiB FREE_MiB UTIL PROCS IDLE OWNERS
status=1
for g in $ALLOWED_GPUS; do
    IFS=', ' read -r used free util < <(nvidia-smi -i "$g" \
        --query-gpu=memory.used,memory.free,utilization.gpu --format=csv,noheader,nounits)
    pids="$(gpu_pids "$g")"
    # A process can exit between nvidia-smi and ps; don't let that abort us.
    owners="$(for p in $pids; do ps -o user= -p "$p" 2>/dev/null || true; done \
        | sort | uniq -c | awk '{ printf "%s(%s) ", $2, $1 }')"
    idle=no
    if gpu_is_idle "$g"; then idle=yes; status=0; fi
    printf "%-4s %9s %9s %4s%% %5s %-5s %s\n" "$g" "$used" "$free" "$util" \
        "$(grep -c . <<< "$pids" || true)" "$idle" "${owners:--}"
done
exit "$status"
