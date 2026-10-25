"""Small speech pill shown next to the companion, as in macOS Curio.

Used for the pointer phrase when the companion lands on something ("right
here!"), the launch greeting ("hey! i'm curio"), and short error notes.
Text types out one character at a time (30-60 ms each) while the pill pops
in from half size with a bright glow that settles, matching the original's
navigation bubble. Click-through and never takes focus.
"""

from __future__ import annotations

import random
from collections.abc import Callable

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QWidget

from curio.ui.window_effects import make_overlay_window

CURSOR_BLUE = "#3380FF"  # DS.Colors.overlayCursorBlue in the Swift app
ERROR_RED = "#E5484D"

POINTER_PHRASES = (
    "right here!",
    "this one!",
    "over here!",
    "click this!",
    "here it is!",
    "found it!",
)

# Sized to stay legible in a 1080p screen recording (Qt scales logical pixels
# with the Windows display scale, so these hold at 100/125/150%).
FONT_PIXEL_SIZE = 15  # was 12
PADDING_X = 11  # was 8
PADDING_Y = 6  # was 4
CORNER_RADIUS = 8  # was 6
# Room around the pill for its glow.
GLOW_MARGIN = 18


def random_pointer_phrase() -> str:
    return random.choice(POINTER_PHRASES)


def step_caption(phrase: str, step: tuple[int, int] | None) -> str:
    """Pointer phrase with walkthrough progress: "click this! (2/4)".

    The model's step totals are often too low, so show "step k" instead of
    a total that's already been reached.
    """
    if step is None:
        return phrase
    index, total = step
    return f"{phrase} ({index}/{total})" if total > index else f"{phrase} (step {index})"


def friendly_error(message: str) -> str:
    """Short, actionable wording for errors shown in the pill."""
    lowered = message.lower()
    if "cannot reach llm server" in lowered or "connecterror" in lowered:
        return "can't reach the model server. check the VPN and SSH tunnel."
    if "401" in lowered or "unauthorized" in lowered:
        return "the server rejected the API key. check llm_api_key."
    if "config problem" in lowered:
        return "config problem. see the log, or tray → Settings."
    if "transcription" in lowered:
        return "couldn't hear that. check your mic."
    return message if len(message) <= 60 else message[:57] + "…"


class PointerBubble(QWidget):
    """A pill whose left edge sits at ``anchor`` (a global point)."""

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

        self._font = QFont()
        self._font.setPixelSize(FONT_PIXEL_SIZE)
        self._font.setWeight(QFont.Weight.DemiBold)

        self._full_text = ""
        self._shown_chars = 0
        self._color = QColor(CURSOR_BLUE)
        self._opacity = 0.0
        self._scale = 1.0  # pop-in: 0.5 -> 1.0
        self._anchor = QPointF()
        self._on_typed: Callable[[], None] | None = None
        self._auto_hide_ms: int | None = None
        self._hidden_for_capture = False

        self._type_timer = QTimer(self)
        self._type_timer.setSingleShot(True)
        self._type_timer.timeout.connect(self._type_next)

        self._pop_anim = QVariantAnimation(self)
        self._pop_anim.setDuration(400)
        self._pop_anim.setStartValue(0.5)
        self._pop_anim.setEndValue(1.0)
        self._pop_anim.setEasingCurve(QEasingCurve.Type.OutBack)  # springy overshoot
        self._pop_anim.valueChanged.connect(self._set_scale)

        self._fade_anim = QVariantAnimation(self)
        self._fade_anim.valueChanged.connect(self._set_opacity)
        self._fade_anim.finished.connect(self._on_fade_finished)

        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.timeout.connect(lambda: self.fade_out())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_text(
        self,
        text: str,
        anchor: QPointF,
        *,
        color: str = CURSOR_BLUE,
        on_typed: Callable[[], None] | None = None,
        auto_hide_ms: int | None = None,
    ) -> None:
        """Pop in and type ``text`` out. ``on_typed`` runs when the last char appears."""
        self._type_timer.stop()
        self._hold_timer.stop()
        self._fade_anim.stop()
        self._full_text = text
        self._shown_chars = 0
        self._color = QColor(color)
        self._on_typed = on_typed
        self._auto_hide_ms = auto_hide_ms
        self._opacity = 1.0
        self._scale = 0.5
        self._resize_for(text)
        self.move_to(anchor)
        if not self._hidden_for_capture:
            self.show()
        self._type_next()

    def move_to(self, anchor: QPointF) -> None:
        """Keep the pill's left edge at ``anchor.x()``, vertically centred on ``anchor.y()``."""
        self._anchor = QPointF(anchor)
        x = int(anchor.x()) - GLOW_MARGIN
        y = int(anchor.y() - self.height() / 2)
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    def fade_out(self, duration_ms: int = 500) -> None:
        self._type_timer.stop()
        self._hold_timer.stop()
        if not self.isVisible() and not self._hidden_for_capture:
            return
        self._fade_anim.stop()
        self._fade_anim.setDuration(duration_ms)
        self._fade_anim.setStartValue(self._opacity)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()

    def hide_now(self) -> None:
        self._type_timer.stop()
        self._hold_timer.stop()
        self._fade_anim.stop()
        self._pop_anim.stop()
        self._full_text = ""
        self._on_typed = None
        self._hidden_for_capture = False
        super().hide()

    @property
    def active(self) -> bool:
        return bool(self._full_text) and (self.isVisible() or self._hidden_for_capture)

    def hide_for_capture(self) -> None:
        self._hidden_for_capture = self.isVisible()
        if self._hidden_for_capture:
            self.setVisible(False)

    def restore_after_capture(self) -> None:
        if self._hidden_for_capture:
            self._hidden_for_capture = False
            self.setVisible(True)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resize_for(self, text: str) -> None:
        metrics = QFontMetrics(self._font)
        width = metrics.horizontalAdvance(text) + 2 * PADDING_X + 2 * GLOW_MARGIN
        height = metrics.height() + 2 * PADDING_Y + 2 * GLOW_MARGIN
        self.setFixedSize(width, height)

    def _type_next(self) -> None:
        if self._shown_chars >= len(self._full_text):
            callback, self._on_typed = self._on_typed, None
            if self._auto_hide_ms is not None:
                self._hold_timer.start(self._auto_hide_ms)
            if callback is not None:
                callback()
            return
        self._shown_chars += 1
        if self._shown_chars == 1:
            self._pop_anim.start()
        self.update()
        self._type_timer.start(random.randint(30, 60))

    def _set_scale(self, value: float) -> None:
        self._scale = float(value)
        self.update()

    def _set_opacity(self, value: float) -> None:
        self._opacity = float(value)
        self.update()

    def _on_fade_finished(self) -> None:
        if self._opacity <= 0.01:
            self.hide_now()

    def showEvent(self, event) -> None:  # noqa: ARG002
        make_overlay_window(self)

    def paintEvent(self, event) -> None:  # noqa: ARG002
        if not self._full_text or self._opacity <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._opacity)

        pill = QRectF(
            GLOW_MARGIN, GLOW_MARGIN,
            self.width() - 2 * GLOW_MARGIN, self.height() - 2 * GLOW_MARGIN,
        )
        # Scale around the pill's left-centre so it grows out of the companion.
        painter.translate(pill.left(), pill.center().y())
        painter.scale(self._scale, self._scale)
        painter.translate(-pill.left(), -pill.center().y())

        # Glow: brighter and wider while popping in, settling to a soft halo.
        settle = max(0.0, min(1.0, (1.0 - self._scale) * 2))
        radius = 6 + settle * 10
        alpha = 0.5 + settle * 0.5
        painter.setPen(Qt.PenStyle.NoPen)
        steps = 6
        for i in range(steps, 0, -1):
            grow = radius * i / steps
            glow = QColor(self._color)
            glow.setAlphaF(alpha * 0.12 * (1 - (i - 1) / steps))
            painter.setBrush(glow)
            painter.drawRoundedRect(
                pill.adjusted(-grow, -grow, grow, grow),
                CORNER_RADIUS + grow, CORNER_RADIUS + grow,
            )

        painter.setBrush(self._color)
        # Light rim keeps the pill's edge visible on dark and blue backgrounds.
        painter.setPen(QPen(QColor(255, 255, 255, 215), 1.5))
        painter.drawRoundedRect(pill, CORNER_RADIUS, CORNER_RADIUS)
        painter.setFont(self._font)
        text_rect = pill.adjusted(PADDING_X, 0, 0, 0)
        align = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        shown = self._full_text[: self._shown_chars]
        # Soft dark shadow under the white text for contrast on the blue pill.
        painter.setPen(QColor(0, 0, 0, 110))
        painter.drawText(text_rect.translated(0, 1), align, shown)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(text_rect, align, shown)
        painter.end()
