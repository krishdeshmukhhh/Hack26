"""Compact live timeline of on-goal, drifting and break time (section F)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from curio.design_system import DS
from curio.focus_session.timeline import SessionTimeline, TimelineState

STATE_COLORS = {
    TimelineState.ON_GOAL: DS.Colors.accent_green,
    TimelineState.DRIFTING: DS.Colors.accent_amber,
    TimelineState.BREAK: DS.Colors.accent_blue,
}
STATE_LABELS = {
    TimelineState.ON_GOAL: "on goal",
    TimelineState.DRIFTING: "drifting",
    TimelineState.BREAK: "break",
}


def minutes_text(seconds: float) -> str:
    minutes = round(max(0.0, seconds) / 60)
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d} min"


class TimelineBar(QWidget):
    """Horizontal bar across the planned session; unplayed time stays grey."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.timeline: SessionTimeline | None = None
        self.planned_seconds = 0.0
        self.setMinimumHeight(18)
        self.setAccessibleName("Session timeline")

    def set_timeline(self, timeline: SessionTimeline | None, planned_seconds: float) -> None:
        self.timeline = timeline
        self.planned_seconds = planned_seconds
        self.update()

    def spans(self) -> list[tuple[TimelineState, float, float]]:
        """(state, start fraction, width fraction) for each segment."""
        if self.timeline is None:
            return []
        total = max(self.planned_seconds, self.timeline.total_seconds, 1.0)
        start = self.timeline.started_at
        return [
            (seg.state, (seg.start - start).total_seconds() / total, seg.seconds / total)
            for seg in self.timeline.segments
            if seg.seconds > 0
        ]

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(DS.Colors.surface))
        painter.drawRoundedRect(rect, DS.CornerRadius.xs, DS.CornerRadius.xs)
        for state, start, width in self.spans():
            painter.setBrush(QColor(STATE_COLORS[state]))
            painter.drawRect(
                QRectF(rect.x() + start * rect.width(), rect.y(), width * rect.width(),
                       rect.height())
            )
        painter.end()


class FocusSessionWindow(QWidget):
    """Small always-available session view. ``runtime`` is a FocusRuntime."""

    def __init__(self, runtime, *, clock: Callable[[], datetime] | None = None, parent=None):
        super().__init__(parent)
        self.runtime = runtime
        self._clock = clock or (lambda: datetime.now(UTC))
        self.setWindowTitle("Curio — Focus")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setFont(QFont("Segoe UI", 10))
        self.setMinimumWidth(340)
        self.setStyleSheet(
            f"QWidget {{ background: {DS.Colors.panel_bg}; color: {DS.Colors.text_primary}; }}"
            f"QPushButton {{ padding: 4px 10px; }}"
        )
        layout = QVBoxLayout(self)
        self.goal = QLabel()
        self.goal.setWordWrap(True)
        self.goal.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.goal)
        self.remaining = QLabel()
        self.remaining.setStyleSheet(f"color: {DS.Colors.text_secondary};")
        layout.addWidget(self.remaining)
        self.bar = TimelineBar()
        layout.addWidget(self.bar)
        self.totals = QLabel()
        self.totals.setTextFormat(Qt.TextFormat.RichText)
        self.totals.setAccessibleName("Time on goal, drifting and on break")
        layout.addWidget(self.totals)
        buttons = QHBoxLayout()
        self.end_button = QPushButton("End session")
        self.end_button.clicked.connect(runtime.request_end)
        buttons.addStretch()
        buttons.addWidget(self.end_button)
        layout.addLayout(buttons)
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._update_remaining)
        runtime.session_started.connect(self._started)
        runtime.timeline_changed.connect(self.refresh)
        runtime.session_ended.connect(self._ended)

    def _started(self, plan) -> None:
        self.goal.setText(plan.goal)
        self.end_button.setEnabled(True)
        self._tick.start()
        self.refresh()
        self.show()

    def _ended(self, _summary) -> None:
        self._tick.stop()
        self.end_button.setEnabled(False)
        self.hide()

    def refresh(self) -> None:
        plan, timeline = self.runtime.plan, self.runtime.timeline
        if plan is None or timeline is None:
            self.bar.set_timeline(None, 0)
            self.totals.setText("")
            return
        self.bar.set_timeline(timeline, plan.duration.total_seconds())
        totals = timeline.totals()
        self.totals.setText(" · ".join(
            f'<span style="color:{STATE_COLORS[s]}">■</span> {STATE_LABELS[s]} '
            f"{minutes_text(totals[s])}"
            for s in TimelineState
        ))
        self._update_remaining()

    def _update_remaining(self) -> None:
        plan = self.runtime.plan
        if plan is None:
            self.remaining.setText("")
            return
        left = (plan.started_at + plan.duration - self._clock()).total_seconds()
        self.remaining.setText(f"{minutes_text(left)} left" if left > 0 else "wrapping up")

    def dispose(self) -> None:
        self._tick.stop()
        self.runtime.session_started.disconnect(self._started)
        self.runtime.timeline_changed.disconnect(self.refresh)
        self.runtime.session_ended.disconnect(self._ended)
        self.close()
