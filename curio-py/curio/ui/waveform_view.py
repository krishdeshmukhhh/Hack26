"""Live audio waveform visualization for Curio.

Displays a horizontal row of vertical bars that react to mic RMS
level. Driven by a 60 Hz QTimer triggering paintEvent — the deque of
historical RMS values scrolls left each paint.
"""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent
from PySide6.QtWidgets import QWidget

from curio.design_system import DS

_BAR_COUNT = 60
_ACCENT_BLUE = QColor(DS.Colors.waveform_bar)
_BAR_FILL_FRACTION = 0.6
_BAR_HEIGHT_FRACTION = 0.9
_BAR_CORNER_RADIUS = 2.0
_FRAME_INTERVAL_MS = 16  # ~60 FPS


class WaveformView(QWidget):
    """60 Hz live audio-level bar waveform."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(360, 72)
        # Pre-fill so the first paint doesn't show an empty widget.
        self._levels: deque[float] = deque([0.0] * _BAR_COUNT, maxlen=_BAR_COUNT)
        self._timer = QTimer(self)
        self._timer.setInterval(_FRAME_INTERVAL_MS)
        self._timer.timeout.connect(self.update)

    @Slot(float)
    def push_level(self, level: float) -> None:
        # Clamp defensively — caller should already clamp, but this is
        # a public slot and bad data should not break rendering.
        level = 0.0 if level < 0.0 else 1.0 if level > 1.0 else level
        self._levels.append(level)

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        widget_w = self.width()
        widget_h = self.height()
        if widget_w <= 0 or widget_h <= 0:
            return

        bar_slot_w = widget_w / _BAR_COUNT
        bar_w = bar_slot_w * _BAR_FILL_FRACTION
        bar_x_offset = (bar_slot_w - bar_w) / 2.0
        mid_y = widget_h / 2.0

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_ACCENT_BLUE)

        for i, level in enumerate(self._levels):
            bar_h = level * widget_h * _BAR_HEIGHT_FRACTION
            if bar_h <= 0:
                continue
            x = i * bar_slot_w + bar_x_offset
            y = mid_y - bar_h / 2.0
            path = QPainterPath()
            path.addRoundedRect(x, y, bar_w, bar_h, _BAR_CORNER_RADIUS, _BAR_CORNER_RADIUS)
            painter.fillPath(path, _ACCENT_BLUE)
