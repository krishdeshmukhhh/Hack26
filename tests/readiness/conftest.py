"""Allow readiness checks to run from the repository root without installation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "curio-py"))
