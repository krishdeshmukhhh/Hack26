"""Eyeball the overlay without the model: ``uv run python scripts/overlay_preview.py 710 1176``.

Flies the companion to global screen point (x, y): the target ring pulses during the
flight, hands off to the spotlight ring on landing, with the pill and the landing bounce.
It quits after a few seconds. ``--triangle`` uses the triangle companion instead of the pet;
``--no-spotlight`` keeps the plain target ring; ``--celebrate`` ends with the finished flourish.
"""

from __future__ import annotations

import argparse
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from curio.config import UiSettings
from curio.pet_config import PetSettings
from curio.ui.companion_widget import CompanionWidget
from curio.ui.pet_widget import PetCompanionWidget
from curio.ui.spotlight import SpotlightController


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("x", type=int)
    parser.add_argument("y", type=int)
    parser.add_argument("--triangle", action="store_true")
    parser.add_argument("--no-spotlight", action="store_true")
    parser.add_argument("--celebrate", action="store_true")
    parser.add_argument("--seconds", type=float, default=6.0)
    args = parser.parse_args()

    app = QApplication(sys.argv)
    companion = CompanionWidget() if args.triangle else PetCompanionWidget(settings=PetSettings())
    spotlight = SpotlightController(UiSettings(spotlight=not args.no_spotlight))
    spotlight.raise_above = companion.raise_overlays
    companion.pointer_arrived.connect(spotlight.arrived)
    companion.show()

    def fly() -> None:
        spotlight.point_started(args.x, args.y)
        companion.fly_to(args.x, args.y)

    QTimer.singleShot(600, fly)
    if args.celebrate:
        QTimer.singleShot(int(args.seconds * 1000) - 1500, companion.celebrate)
    QTimer.singleShot(int(args.seconds * 1000), app.quit)
    app.aboutToQuit.connect(spotlight.hide_now)
    app.aboutToQuit.connect(companion.close)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
