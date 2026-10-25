"""Cursor-following companion overlay, matching macOS Curio's behaviour.

- Idle / responding: a blue triangle beside the cursor, with a soft glow.
- Listening: five reactive waveform bars replace the triangle.
- Processing: a small spinner replaces the triangle.
- Pointing: flies along a bowed arc to the target (turning to face the way
  it's going and swelling mid-flight), lands beside it, and a pill pops in
  with "right here!" or similar. After 3 s it fades and flies back; moving
  the mouse during the return flight snaps it back to the cursor.
- Walkthrough steps hold at the target until released.
- Launch: fades in over 2 s, then says "hey! i'm curio".
- With the cursor toggled off, it appears only for an interaction and fades
  out a second after it's done.
"""

from __future__ import annotations

import logging
import math
from enum import Enum, auto

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QPainter,
    QPen,
    QPolygonF,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from curio.state import VoiceState
from curio.ui.flight import (
    REST_ROTATION_DEGREES,
    RETURN_CANCEL_DISTANCE,
    flight_duration_seconds,
    flight_frame,
    follow_center,
    landing_point,
)
from curio.ui.pointer_bubble import (
    CURSOR_BLUE,
    ERROR_RED,
    PointerBubble,
    friendly_error,
    random_pointer_phrase,
    step_caption,
)
from curio.ui.window_effects import make_overlay_window

logger = logging.getLogger(__name__)

WELCOME_TEXT = "hey! i'm curio"


def _screen_rect(point: QPointF) -> tuple[int, int, int, int]:
    """(left, top, width, height) of the screen containing ``point``."""
    screen = QGuiApplication.screenAt(point.toPoint()) or QGuiApplication.primaryScreen()
    geo = screen.geometry()
    return (geo.x(), geo.y(), geo.width(), geo.height())


class _Mode(Enum):
    FOLLOWING = auto()
    FLYING = auto()      # towards a target
    POINTING = auto()    # landed, showing the pointer pill
    RETURNING = auto()   # flying back to the cursor


class CompanionWidget(QWidget):
    """The blue buddy that follows the cursor and points at things."""

    CANVAS = 72                # square window; the buddy is drawn at its centre
    TRIANGLE_SIZE = 22         # was 18; bigger reads better in 1080p recordings
    FRAME_MS = 16              # ~60 fps for tracking and flights
    POINT_HOLD_MS = 3000       # pill stays this long once typed out
    BUBBLE_FADE_MS = 500
    ERROR_FLASH_MS = 1000
    TRANSIENT_HIDE_DELAY_MS = 1000

    # Listening waveform (macOS BlueCursorWaveformView).
    WAVE_PROFILE = (0.4, 0.7, 1.0, 0.7, 0.4)
    WAVE_BAR_WIDTH = 2.5
    WAVE_BAR_GAP = 2.0
    # Our mic level is RMS (speech ~0.01-0.1); the Swift formula expects a
    # larger power level, so scale it up first.
    WAVE_LEVEL_GAIN = 3.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedSize(self.CANVAS, self.CANVAS)

        self.bubble = PointerBubble()

        self._state = VoiceState.IDLE
        self._mode = _Mode.FOLLOWING
        self._center = QPointF(QCursor.pos())
        self._rotation = REST_ROTATION_DEGREES
        self._flight_scale = 1.0
        self._opacity = 1.0
        self._audio_level = 0.0
        self._spin_degrees = 0.0
        self._error_flash = False
        self._hidden_for_capture = False

        # Pointing
        self._hold = False
        self._caption = ""
        self._return_cancel_origin = QPointF()

        # Show/hide toggle (tray "Show Curio")
        self._cursor_enabled = True

        self._clock = QElapsedTimer()
        self._clock.start()

        self._frame_timer = QTimer(self)
        self._frame_timer.setInterval(self.FRAME_MS)
        self._frame_timer.timeout.connect(self._on_frame)

        self._flight_start = (0.0, 0.0)
        self._flight_end = (0.0, 0.0)
        self._flight_duration_ms = 0.0
        self._flight_started_ms = 0
        self._flight_done = None

        self._point_timer = QTimer(self)
        self._point_timer.setSingleShot(True)
        self._point_timer.timeout.connect(self._run_point_callback)
        self._point_callback = None

        self._error_timer = QTimer(self)
        self._error_timer.setSingleShot(True)
        self._error_timer.setInterval(self.ERROR_FLASH_MS)
        self._error_timer.timeout.connect(self._end_error_flash)

        self._fade_anim = QVariantAnimation(self)
        self._fade_anim.valueChanged.connect(self._set_opacity)

        self._transient_timer = QTimer(self)
        self._transient_timer.setInterval(200)
        self._transient_timer.timeout.connect(self._check_transient_hide)
        self._transient_idle_since: int | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def show(self) -> None:
        self._snap_to_cursor()
        super().show()
        self._frame_timer.start()

    def start(self) -> None:
        """First appearance: fade in over 2 s, then greet."""
        self._set_opacity(0.0)
        self.show()
        self._animate_opacity(1.0, 2000)
        QTimer.singleShot(2000, self._greet)

    def hide(self) -> None:
        self._frame_timer.stop()
        self.bubble.hide_now()
        super().hide()

    def showEvent(self, event) -> None:  # noqa: ARG002
        make_overlay_window(self)

    def hide_for_capture(self) -> None:
        self._hidden_for_capture = self.isVisible()
        if self._hidden_for_capture:
            self.setVisible(False)
        self.bubble.hide_for_capture()

    def restore_after_capture(self) -> None:
        if self._hidden_for_capture:
            self._hidden_for_capture = False
            self.setVisible(True)
        self.bubble.restore_after_capture()

    def set_cursor_enabled(self, enabled: bool) -> None:
        """Tray toggle. Off: hidden except during an interaction."""
        self._cursor_enabled = enabled
        self._transient_timer.stop()
        if enabled:
            if not self.isVisible():
                self.show()
                self._animate_opacity(1.0, 300)
        elif self._state == VoiceState.IDLE and not self._is_pointing():
            self.hide()

    # ------------------------------------------------------------------
    # Voice state
    # ------------------------------------------------------------------

    def set_state(self, state: VoiceState) -> None:
        if state == self._state:
            return
        self._state = state

        if state == VoiceState.LISTENING:
            # A new question cancels any pointing and brings the buddy back.
            self._transient_timer.stop()
            if not self.isVisible():
                self._set_opacity(1.0)
                self.show()
            self._cancel_pointing()
            self.bubble.hide_now()
            self._snap_to_cursor()
        elif state == VoiceState.IDLE:
            if self._hold:
                self.release_hold()
            if not self._cursor_enabled:
                self._transient_idle_since = None
                self._transient_timer.start()
        self.update()

    def set_audio_level(self, level: float) -> None:
        self._audio_level = level

    def flash_error(self, _msg: str = "") -> None:
        self._error_flash = True
        self._error_timer.start()
        self.update()

    def show_error(self, message: str) -> None:
        """Red flash plus a short red pill explaining what to check."""
        self.flash_error()
        if self._is_pointing():
            return  # don't cover a pointer pill mid-point
        self.bubble.show_text(
            friendly_error(message), self._bubble_anchor(), color=ERROR_RED, auto_hide_ms=3500
        )

    def _end_error_flash(self) -> None:
        self._error_flash = False
        self.update()

    # ------------------------------------------------------------------
    # Pointing
    # ------------------------------------------------------------------

    def fly_to(
        self, x: int, y: int, *, hold: bool = False, step: tuple[int, int] | None = None
    ) -> None:
        """Fly to screen point (x, y) and point at it.

        ``hold`` keeps the buddy there (walkthrough step) until
        ``release_hold``; ``step`` adds "(k/n)" to the pointer phrase.
        """
        self._point_timer.stop()
        self.bubble.hide_now()
        self._hold = hold
        self._caption = step_caption(random_pointer_phrase(), step)

        dest = landing_point((x, y), _screen_rect(QPointF(x, y)))
        self._mode = _Mode.FLYING
        self._start_flight(dest, self._arrive_at_target)
        logger.info("fly_to: (%d, %d)%s", x, y, " [hold]" if hold else "")

    def release_hold(self) -> None:
        """End a walkthrough hold: fade the pill and fly back."""
        self._hold = False
        if self._mode == _Mode.POINTING:
            self._fade_bubble_then_return()

    def return_to_cursor(self) -> None:
        if self._mode in (_Mode.FLYING, _Mode.POINTING):
            self._hold = False
            self._fade_bubble_then_return()

    def _arrive_at_target(self) -> None:
        self._mode = _Mode.POINTING
        self._rotation = REST_ROTATION_DEGREES
        self.bubble.show_text(self._caption, self._bubble_anchor(), on_typed=self._pointer_typed)

    def _pointer_typed(self) -> None:
        if self._mode != _Mode.POINTING or self._hold:
            return
        self._restart_point_timer(self.POINT_HOLD_MS, self._fade_bubble_then_return)

    def _fade_bubble_then_return(self) -> None:
        if self._mode != _Mode.POINTING:
            if self._mode == _Mode.FLYING:
                self._fly_back()
            return
        self.bubble.fade_out(self.BUBBLE_FADE_MS)
        self._restart_point_timer(self.BUBBLE_FADE_MS, self._fly_back)

    def _fly_back(self) -> None:
        if self._mode not in (_Mode.POINTING, _Mode.FLYING):
            return
        cursor = QPointF(QCursor.pos())
        self._return_cancel_origin = cursor
        self._mode = _Mode.RETURNING
        self._start_flight(self._follow_point(cursor), self._finish_return)

    def _finish_return(self) -> None:
        self._mode = _Mode.FOLLOWING
        self._rotation = REST_ROTATION_DEGREES
        self._flight_scale = 1.0

    def _cancel_pointing(self) -> None:
        self._point_timer.stop()
        self._flight_done = None
        self._hold = False
        self._mode = _Mode.FOLLOWING
        self._rotation = REST_ROTATION_DEGREES
        self._flight_scale = 1.0

    def _restart_point_timer(self, ms: int, callback) -> None:
        self._point_callback = callback
        self._point_timer.start(ms)

    def _run_point_callback(self) -> None:
        callback, self._point_callback = self._point_callback, None
        if callback is not None:
            callback()

    # ------------------------------------------------------------------
    # Flight + tracking (one frame timer drives both)
    # ------------------------------------------------------------------

    def _start_flight(self, dest: tuple[float, float], on_done) -> None:
        start = (self._center.x(), self._center.y())
        self._flight_start = start
        self._flight_end = dest
        self._flight_duration_ms = flight_duration_seconds(start, dest) * 1000
        self._flight_started_ms = self._clock.elapsed()
        self._flight_done = on_done

    def _on_frame(self) -> None:
        self._advance_motion()
        if self._state == VoiceState.PROCESSING:
            self._spin_degrees = (self._spin_degrees + 360 * self.FRAME_MS / 800) % 360
        if self.bubble.active and self._mode != _Mode.RETURNING:
            self.bubble.move_to(self._bubble_anchor())
        self.update()

    # ------------------------------------------------------------------
    # Subclass hooks (see ui/pet_widget.py)
    # ------------------------------------------------------------------

    def _advance_motion(self) -> None:
        """Move one frame: fly along the current arc, or follow the cursor."""
        if self._mode in (_Mode.FLYING, _Mode.RETURNING) and self._flight_done is not None:
            if self._mode == _Mode.RETURNING:
                moved = QPointF(QCursor.pos()) - self._return_cancel_origin
                if math.hypot(moved.x(), moved.y()) > RETURN_CANCEL_DISTANCE:
                    self._cancel_pointing()
                    self._snap_to_cursor()
                    return
            elapsed = self._clock.elapsed() - self._flight_started_ms
            progress = min(1.0, elapsed / max(1.0, self._flight_duration_ms))
            (x, y), rotation, scale = flight_frame(self._flight_start, self._flight_end, progress)
            self._center = QPointF(x, y)
            self._rotation = rotation
            self._flight_scale = scale
            self._place()
            if progress >= 1.0:
                done, self._flight_done = self._flight_done, None
                self._flight_scale = 1.0
                done()
        elif self._mode == _Mode.FOLLOWING:
            self._snap_to_cursor()

    def _is_pointing(self) -> bool:
        """True while flying to, pointing at, or returning from a target."""
        return self._mode != _Mode.FOLLOWING

    def _follow_point(self, cursor: QPointF) -> tuple[float, float]:
        return follow_center((cursor.x(), cursor.y()), _screen_rect(cursor))

    def _snap_to_cursor(self) -> None:
        x, y = self._follow_point(QPointF(QCursor.pos()))
        self._center = QPointF(x, y)
        self._place()

    def _place(self) -> None:
        half = self.CANVAS / 2
        pos = (int(self._center.x() - half), int(self._center.y() - half))
        if pos != (self.x(), self.y()):
            self.move(*pos)

    def _bubble_anchor(self) -> QPointF:
        # macOS: pill's left edge 10 px right of the buddy, centred 18 px below.
        return QPointF(self._center.x() + 10, self._center.y() + 18)

    # ------------------------------------------------------------------
    # Greeting, fading, transient visibility
    # ------------------------------------------------------------------

    def _greet(self) -> None:
        if self._state == VoiceState.IDLE and not self._is_pointing():
            self.bubble.show_text(WELCOME_TEXT, self._bubble_anchor(), auto_hide_ms=2000)

    def _animate_opacity(self, end: float, ms: int) -> None:
        self._fade_anim.stop()
        self._fade_anim.setDuration(ms)
        self._fade_anim.setStartValue(self._opacity)
        self._fade_anim.setEndValue(end)
        self._fade_anim.start()

    def _set_opacity(self, value: float) -> None:
        self._opacity = float(value)
        self.update()

    def _check_transient_hide(self) -> None:
        """Cursor toggled off: hide 1 s after speech and pointing are done."""
        busy = self._state != VoiceState.IDLE or self._is_pointing() or self.bubble.active
        if busy:
            self._transient_idle_since = None
            return
        now = self._clock.elapsed()
        if self._transient_idle_since is None:
            self._transient_idle_since = now
        elif now - self._transient_idle_since >= self.TRANSIENT_HIDE_DELAY_MS:
            self._transient_timer.stop()
            self.hide()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._opacity)
        c = QPointF(self.CANVAS / 2, self.CANVAS / 2)
        color = QColor(ERROR_RED if self._error_flash else CURSOR_BLUE)

        flying = self._mode in (_Mode.FLYING, _Mode.RETURNING, _Mode.POINTING)
        if self._state == VoiceState.LISTENING and not flying:
            self._paint_glow(painter, c, color, 12, 0.35)
            self._paint_waveform(painter, c, color)
        elif self._state == VoiceState.PROCESSING and not flying:
            self._paint_glow(painter, c, color, 12, 0.35)
            self._paint_spinner(painter, c, color)
        else:
            glow = 8 + (self._flight_scale - 1.0) * 20
            self._paint_glow(painter, c, color, glow * 1.6, 0.45)
            self._paint_triangle(painter, c, color)
        painter.end()

    def _paint_glow(
        self, painter: QPainter, c: QPointF, color: QColor, radius: float, alpha: float
    ) -> None:
        gradient = QRadialGradient(c, radius)
        inner = QColor(color)
        inner.setAlphaF(alpha)
        outer = QColor(color)
        outer.setAlphaF(0.0)
        gradient.setColorAt(0.0, inner)
        gradient.setColorAt(1.0, outer)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(c, radius, radius)

    def _paint_triangle(self, painter: QPainter, c: QPointF, color: QColor) -> None:
        # Equilateral, centred on its centroid (the Swift Triangle shape).
        size = self.TRIANGLE_SIZE * self._flight_scale
        height = size * math.sqrt(3) / 2
        painter.save()
        painter.translate(c)
        painter.rotate(self._rotation)
        # White rim so the blue triangle stays visible on blue/dark backgrounds.
        rim = QPen(QColor(255, 255, 255, 230), 1.6)
        rim.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(rim)
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF([
            QPointF(0, -height / 1.5),
            QPointF(-size / 2, height / 3),
            QPointF(size / 2, height / 3),
        ]))
        painter.restore()

    def _paint_waveform(self, painter: QPainter, c: QPointF, color: QColor) -> None:
        seconds = self._clock.elapsed() / 1000.0
        level = max(self._audio_level * self.WAVE_LEVEL_GAIN - 0.008, 0.0)
        eased = min(level * 2.85, 1.0) ** 0.76
        count = len(self.WAVE_PROFILE)
        total = count * self.WAVE_BAR_WIDTH + (count - 1) * self.WAVE_BAR_GAP
        x = c.x() - total / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        for i, weight in enumerate(self.WAVE_PROFILE):
            phase = seconds * 3.6 + i * 0.35
            height = (3 + eased * 10 * weight + (math.sin(phase) + 1) / 2 * 1.5) * 1.3
            painter.drawRoundedRect(
                QRectF(x, c.y() - height / 2, self.WAVE_BAR_WIDTH, height), 1.5, 1.5
            )
            x += self.WAVE_BAR_WIDTH + self.WAVE_BAR_GAP

    def _paint_spinner(self, painter: QPainter, c: QPointF, color: QColor) -> None:
        """A 70% arc (Swift: trim 0.15-0.85) fading from tail to head, one turn per 0.8 s."""
        radius = 7.5
        rect = QRectF(c.x() - radius, c.y() - radius, 2 * radius, 2 * radius)
        sweep = 252.0
        segments = 14
        head = -self._spin_degrees  # Qt angles: counter-clockwise from 3 o'clock
        for i in range(segments):
            fraction = (i + 1) / segments  # 0 at the tail, 1 at the head
            seg_color = QColor(color)
            seg_color.setAlphaF(fraction)
            pen = QPen(seg_color, 2.5)
            last = i == segments - 1
            pen.setCapStyle(Qt.PenCapStyle.RoundCap if last else Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)
            seg_start = head + sweep * (1 - fraction)
            painter.drawArc(rect, int(seg_start * 16), int(-sweep / segments * 16 - 8))
