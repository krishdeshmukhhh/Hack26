"""Independent, click-through target pulses. Public methods run on the Qt thread."""

from __future__ import annotations

import time

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from curio.ui.focus_overlay import logical_target
from curio.ui.theme import ACCENT, RING_WIDTH
from curio.ui.window_effects import make_overlay_window


def _logical_target(x: int, y: int):
    return logical_target(x, y)


class TargetRingOverlay(QWidget):
    """Three expanding/fading accent-blue rings over 1.5 seconds.

    ``pulse_at`` accepts physical global desktop pixels. A new target replaces
    the previous animation. Capture hiding/restoring is idempotent; the deadline
    continues to elapse while hidden. Integration must marshal calls to Qt.
    """

    DURATION = 1.5
    PULSE_DURATION = 0.9
    PULSE_SPACING = 0.3
    FADE_DURATION = 0.18  # handoff to the spotlight ring

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        for attribute in (
            Qt.WidgetAttribute.WA_TranslucentBackground,
            Qt.WidgetAttribute.WA_NoSystemBackground,
            Qt.WidgetAttribute.WA_ShowWithoutActivating,
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
        ):
            self.setAttribute(attribute)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._center = QPointF()
        self._started: float | None = None
        self._fade_started: float | None = None
        self._capturing = False
        self._restore_visible = False
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._on_frame)

    def pulse_at(self, x: int, y: int) -> None:
        screen, point = _logical_target(x, y)
        if screen is None:
            self.clear()
            return
        # A screen-sized canvas avoids platform window repositioning at edges.
        self.winId()
        self.windowHandle().setScreen(screen)
        self.setGeometry(screen.geometry())
        self._center = point - QPointF(screen.geometry().topLeft())
        self._started = time.monotonic()
        self._fade_started = None
        self._timer.start()
        if self._capturing:
            self._restore_visible = True
        else:
            self.show()
        self.update()

    def fade_out(self) -> None:
        """Quickly fade the pulse away (the spotlight ring takes over the spot)."""
        if self._started is not None and self._fade_started is None:
            self._fade_started = time.monotonic()

    def clear(self) -> None:
        self._started = None
        self._fade_started = None
        self._restore_visible = False
        self._timer.stop()
        self.hide()

    def hide_for_capture(self) -> None:
        if not self._capturing:
            self._restore_visible = self.isVisible()
            self._capturing = True
            self.hide()

    def restore_after_capture(self) -> None:
        if not self._capturing:
            return
        self._capturing = False
        self._on_frame()
        if self._restore_visible and self._started is not None:
            self.show()
        self._restore_visible = False

    def _on_frame(self) -> None:
        if self._started is None:
            return
        now = time.monotonic()
        faded = self._fade_started is not None and now - self._fade_started >= self.FADE_DURATION
        if faded or now - self._started >= self.DURATION:
            self.clear()
        else:
            self.update()

    def paintEvent(self, event) -> None:
        if self._started is None:
            return
        now = time.monotonic()
        elapsed = now - self._started
        fade = 1.0
        if self._fade_started is not None:
            fade = max(0.0, 1 - (now - self._fade_started) / self.FADE_DURATION)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for index in range(3):
            progress = (elapsed - index * self.PULSE_SPACING) / self.PULSE_DURATION
            if 0 <= progress < 1:
                color = QColor(ACCENT)
                color.setAlphaF(0.85 * (1 - progress) * fade)
                painter.setPen(QPen(color, RING_WIDTH))
                radius = 8 + 34 * progress
                painter.drawEllipse(self._center, radius, radius)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        make_overlay_window(self)

    def closeEvent(self, event) -> None:
        self.clear()
        self._capturing = False
        super().closeEvent(event)
