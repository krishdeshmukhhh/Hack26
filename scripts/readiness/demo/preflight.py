"""Read-only offline preflight; does not certify hardware, providers or outcomes."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[3]
    checks = {
        "Python 3.12": sys.version_info[:2] == (3, 12),
        **{f"module {name}": importlib.util.find_spec(name) is not None
           for name in ("PySide6", "httpx", "qasync", "sounddevice", "mss")},
        **{f"asset {name}": (root / "curio-py/curio/assets/pets" / name).is_file()
           for name in ("fox.png", "cat.png", "red_panda.png", "ferret.png", "clips.json")},
        "concept graph": (root / "curio-py/curio/skills/concepts.json").is_file(),
        "dashboard": (root / "curio-py/curio/map_sync/assets/dashboard.html").is_file(),
    }
    for name, ok in checks.items():
        print(f"{'PASS' if ok else 'FAIL'} {name}")
    print(
        "Offline checks only: microphone, audio, Qt DLL loading, model, DPI and packaging untested."
    )
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
