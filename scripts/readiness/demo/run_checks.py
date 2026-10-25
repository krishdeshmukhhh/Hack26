"""Run owned and existing demo checks without cache/bytecode or shared temp paths."""

import os
import subprocess
import sys
import uuid
from pathlib import Path

root = Path(__file__).resolve().parents[3]
env = dict(
    os.environ,
    PYTHONPATH=str(root / "curio-py"),
    PYTHONDONTWRITEBYTECODE="1",
    QT_QPA_PLATFORM="offscreen",
)
paths = [
    "tests/readiness/test_demo_journey.py",
    "tests/readiness/test_sync_recovery.py",
    "curio-py/tests/test_coaching_integration.py",
    "curio-py/tests/test_live_tutoring.py",
    "curio-py/tests/test_learning_integration.py",
    "curio-py/tests/test_walkthrough.py",
    "curio-py/tests/test_hands_free.py",
    "curio-py/tests/test_kokoro_tts.py",
]
temp = root / "scripts/readiness/demo" / ("tmp-" + uuid.uuid4().hex)
command = [
    sys.executable,
    "-m",
    "pytest",
    *paths,
    "-q",
    "-s",
    "-p",
    "no:cacheprovider",
    "--basetemp",
    str(temp),
]
print(subprocess.list2cmdline(command), flush=True)
result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True)
print(result.stdout)
print(result.stderr)
(root / "docs/readiness/demo/check-results.txt").write_text(
    subprocess.list2cmdline(command)
    + "\n"
    + result.stdout
    + result.stderr
    + f"\nEXIT {result.returncode}\n",
    encoding="utf-8",
)
# Pytest data stays inside the owned tree and can be inspected before removal.
print(f"Temporary evidence: {temp}")
raise SystemExit(result.returncode)
