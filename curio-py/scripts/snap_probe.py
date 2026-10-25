"""Live-desktop probe for UIA point snapping.

Usage (from curio-py/):
    uv run python scripts/snap_probe.py X Y "label"      # physical screen pixels
    uv run python scripts/snap_probe.py --list X Y       # list nearby target elements
"""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import logging
import sys
import time

from curio import ui_automation as ua


def _list(x: int, y: int) -> None:
    be = ua._get_backend()
    for c in be.collect(x, y, ua.SEARCH_RADIUS_PX, time.monotonic() + 5):
        print(f"{c.kind:10s} {c.name[:50]!r:54s} ({c.left},{c.top},{c.right},{c.bottom})")


async def _run(x: int, y: int, label: str) -> None:
    # First call includes type-library load; time a second one for steady state.
    for i in range(3):
        t = time.monotonic()
        res = await ua.snap_point(x, y, label, timeout_s=5.0 if i == 0 else ua.DEFAULT_TIMEOUT_S)
        print(f"run {i}: {res}  wall={(time.monotonic() - t) * 1000:.0f} ms")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    with contextlib.suppress(Exception):
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    args = sys.argv[1:]
    if args and args[0] == "--list":
        _list(int(args[1]), int(args[2]))
        return
    if len(args) != 3:
        sys.exit(__doc__)
    asyncio.run(_run(int(args[0]), int(args[1]), args[2]))


if __name__ == "__main__":
    main()
