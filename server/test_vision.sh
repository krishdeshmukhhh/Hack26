#!/usr/bin/env bash
# Check the running server can see an image and point at it.
#   ./test_vision.sh          (PORT=8001 ./test_vision.sh if serve.sh moved ports)
set -euo pipefail
source "$(dirname "$0")/common.sh"
# shellcheck source=/dev/null
source "$VENV/bin/activate"

API_KEY="$(cat "$API_KEY_FILE")" PORT="$PORT" MODEL="$SERVED_MODEL_NAME" \
    python3 "$HERE/test_vision.py"
