"""Landing squash-and-settle shared by the triangle and the pet.

``landing_scale`` is the pure curve (1.0 -> 1.08 -> 0.97 -> 1.0); ``LandingBounce``
drives it with a QVariantAnimation that only runs for its ~180 ms.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QVariantAnimation

LANDING_MS = 180
_KEYFRAMES = ((0.0, 1.0), (0.35, 1.08), (0.7, 0.97), (1.0, 1.0))


def landing_scale(progress: float) -> float:
    """Scale at ``progress`` (0..1) through the landing; 1.0 outside the range."""
    if progress <= 0.0 or progress >= 1.0:
        return 1.0
    for (t0, s0), (t1, s1) in zip(_KEYFRAMES, _KEYFRAMES[1:], strict=False):
        if progress <= t1:
            return s0 + (s1 - s0) * (progress - t0) / (t1 - t0)
    return 1.0


class LandingBounce(QObject):
    """``scale`` is 1.0 except during the bounce; ``on_change`` asks for a repaint."""

    def __init__(self, on_change: Callable[[], None], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.scale = 1.0
        self._on_change = on_change
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(LANDING_MS)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.valueChanged.connect(self._step)
        self._anim.finished.connect(self.stop)

    @property
    def active(self) -> bool:
        return self._anim.state() == QVariantAnimation.State.Running

    def start(self) -> None:
        self._anim.stop()
        self._anim.start()

    def stop(self) -> None:
        self._anim.stop()
        if self.scale != 1.0:
            self.scale = 1.0
            self._on_change()

    def _step(self, value) -> None:
        self.scale = landing_scale(float(value))
        self._on_change()
