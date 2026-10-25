"""Eyeball the spotlight without the model: ``uv run python scripts/spotlight_demo.py 710 1176``.

Shows the overlay at global screen point (x, y) for a few seconds, then exits.
``--ring-only`` skips the dim (the look a walkthrough step settles into).
"""

from __future__ import annotations

import argparse
import logging
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from curio.config import UiSettings
from curio.ui.spotlight import SpotlightController


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("x", type=int)
    parser.add_argument("y", type=int)
    parser.add_argument("--ring-only", action="store_true", help="no dim, just the ring")
    parser.add_argument("--seconds", type=float, default=5.0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG, format="%(name)s: %(message)s")
    app = QApplication(sys.argv)
    controller = SpotlightController(UiSettings())
    controller.point_started(args.x, args.y)
    controller.arrived()
    if args.ring_only:
        controller._overlay.set_dim(False)
    QTimer.singleShot(int(args.seconds * 1000), app.quit)
    app.aboutToQuit.connect(controller.hide_now)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
