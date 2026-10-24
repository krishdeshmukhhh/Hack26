"""Speech bubble that follows the companion and shows what it's saying.

Mirrors the original Curio's response overlay: the answer streams into a
dark rounded bubble next to the blue triangle, a title names what it's
pointing at (or which walkthrough step this is), and the bubble fades out a
few seconds after it finishes talking. Like the companion, it never takes
focus or mouse input, and it hides itself during screenshots.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPoint, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from curio.design_system import DS
from curio.point_parser import strip_tags_for_display
from curio.state import VoiceState
from curio.ui.window_effects import make_overlay_window

MAX_WIDTH = 340
MAX_BODY_LINES = 7
PADDING = 12
LINE_GAP = 4
# Bubble's top-left relative to the companion widget's top-left: just below
# and right of the triangle.
ANCHOR_OFFSET = QPoint(26, 30)
FADE_AFTER_MS = 6000
ERROR_VISIBLE_MS = 8000
FOLLOW_INTERVAL_MS = 33


def wrap_tail(
    text: str, measure: Callable[[str], int], width: int, max_lines: int
) -> list[str]:
    """Word-wrap ``text`` to ``width`` and keep only the last ``max_lines`` lines.

    Streaming answers grow at the bottom, so the newest words stay visible;
    a leading "…" marks that earlier lines were dropped.
    """
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}" if line else word
            if line and measure(candidate) > width:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    while lines and not lines[-1]:
        lines.pop()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
        # The "…" makes the first line wider; drop its leading words to fit.
        words = lines[0].split()
        while len(words) > 1 and measure("… " + " ".join(words)) > width:
            words.pop(0)
        lines[0] = "… " + " ".join(words)
    return lines


def friendly_error(message: str) -> str:
    """Short, actionable wording for errors shown in the bubble."""
    lowered = message.lower()
    if "cannot reach llm server" in lowered or "connecterror" in lowered:
        return (
            "can't reach the model server. check the VPN, the SSH tunnel, "
            "and that the server is running."
        )
    if "401" in lowered or "unauthorized" in lowered:
        return "the model server rejected the API key. check llm_api_key in config.toml."
    if "transcription" in lowered:
        return "couldn't transcribe that. check your microphone and try again."
    return message if len(message) <= 160 else message[:157] + "…"


class ResponseBubble(QWidget):
    """Floating text bubble anchored to the companion widget."""

    def __init__(self, anchor: QWidget, parent: QWidget | None = None) -> None:
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

        self._anchor = anchor
        self._raw = ""
        self._title: str | None = None
        self._hint: str | None = None
        self._is_error = False
        self._placeholder = False  # dim "thinking…" text instead of an answer
        self._hidden_for_capture = False
        self._lines: list[str] = []

        self._title_font = QFont()
        self._title_font.setPixelSize(DS.Fonts.size_sm)
        self._title_font.setBold(True)
        self._body_font = QFont()
        self._body_font.setPixelSize(DS.Fonts.size_md)
        self._hint_font = QFont()
        self._hint_font.setPixelSize(DS.Fonts.size_sm)

        self._follow_timer = QTimer(self)
        self._follow_timer.setInterval(FOLLOW_INTERVAL_MS)
        self._follow_timer.timeout.connect(self._follow_anchor)

        self._fade_timer = QTimer(self)
        self._fade_timer.setSingleShot(True)
        self._fade_timer.timeout.connect(self._fade_out)
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_anim.setDuration(400)
        self._fade_anim.finished.connect(self._on_fade_finished)

    # ------------------------------------------------------------------
    # Content
    # ------------------------------------------------------------------

    def on_state(self, state: VoiceState) -> None:
        if state == VoiceState.LISTENING:
            self.clear()
        elif state == VoiceState.PROCESSING:
            self._raw = ""
            self._is_error = False
            self._set_body_placeholder("thinking…")
        elif state in (VoiceState.RESPONDING, VoiceState.GUIDING):
            self._fade_timer.stop()
        elif state == VoiceState.IDLE and self.isVisible() and not self._is_error:
            self._fade_timer.start(FADE_AFTER_MS)

    def append_delta(self, text: str) -> None:
        if self._is_error:
            return
        self._raw += text
        self._refresh()

    def set_response(self, text: str) -> None:
        self._raw = text
        self._is_error = False
        self._refresh()

    def set_title(self, title: str | None) -> None:
        self._title = title
        self._refresh()

    def set_hint(self, hint: str | None) -> None:
        self._hint = hint
        self._refresh()

    def show_error(self, message: str) -> None:
        self._is_error = True
        self._title = "something went wrong"
        self._hint = None
        self._raw = friendly_error(message)
        self._refresh()
        self._fade_timer.start(ERROR_VISIBLE_MS)

    def clear(self) -> None:
        self._raw = ""
        self._title = None
        self._hint = None
        self._is_error = False
        self._fade_timer.stop()
        self._fade_anim.stop()
        self._follow_timer.stop()
        super().hide()

    def _set_body_placeholder(self, text: str) -> None:
        self._title = None
        self._hint = None
        self._lines = [text]
        self._placeholder = True
        self._relayout_and_show()

    def _refresh(self) -> None:
        self._placeholder = False
        body = self._raw if self._is_error else strip_tags_for_display(self._raw)
        metrics = QFontMetrics(self._body_font)
        self._lines = wrap_tail(
            body, metrics.horizontalAdvance, MAX_WIDTH - 2 * PADDING, MAX_BODY_LINES
        )
        if not self._lines and not self._title:
            return
        self._relayout_and_show()

    # ------------------------------------------------------------------
    # Capture visibility
    # ------------------------------------------------------------------

    def hide_for_capture(self) -> None:
        self._hidden_for_capture = self.isVisible()
        if self._hidden_for_capture:
            self.setVisible(False)

    def restore_after_capture(self) -> None:
        if self._hidden_for_capture:
            self._hidden_for_capture = False
            self.setVisible(True)

    # ------------------------------------------------------------------
    # Layout, position, painting
    # ------------------------------------------------------------------

    def _line_height(self, font: QFont) -> int:
        return QFontMetrics(font).height()

    def _relayout_and_show(self) -> None:
        body_metrics = QFontMetrics(self._body_font)
        widths = [body_metrics.horizontalAdvance(line) for line in self._lines] or [0]
        if self._title:
            widths.append(QFontMetrics(self._title_font).horizontalAdvance(self._title))
        if self._hint:
            widths.append(QFontMetrics(self._hint_font).horizontalAdvance(self._hint))
        width = min(MAX_WIDTH, max(widths) + 2 * PADDING)

        height = 2 * PADDING + len(self._lines) * (self._line_height(self._body_font) + LINE_GAP)
        if self._title:
            height += self._line_height(self._title_font) + LINE_GAP
        if self._hint:
            height += self._line_height(self._hint_font) + LINE_GAP
        self.setFixedSize(int(width), int(height))

        self._fade_anim.stop()
        self.setWindowOpacity(1.0)
        self._follow_anchor()
        if not self.isVisible() and not self._hidden_for_capture:
            self.show()
        self._follow_timer.start()
        self.update()

    def _follow_anchor(self) -> None:
        anchor = self._anchor.pos()
        x = anchor.x() + ANCHOR_OFFSET.x()
        y = anchor.y() + ANCHOR_OFFSET.y()
        screen = QGuiApplication.screenAt(anchor) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        if x + self.width() > area.right():
            x = anchor.x() - self.width() - 4
        if y + self.height() > area.bottom():
            y = anchor.y() - self.height() - 4
        x = max(area.left(), x)
        y = max(area.top(), y)
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    def showEvent(self, event) -> None:  # noqa: ARG002
        make_overlay_window(self)

    def paintEvent(self, event) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        background = QColor(DS.Colors.panel_bg)
        background.setAlphaF(0.94)
        border = QColor(DS.Colors.error_red if self._is_error else DS.Colors.accent_blue)
        border.setAlphaF(0.55)
        painter.setPen(QPen(border, 1.2))
        painter.setBrush(background)
        painter.drawRoundedRect(
            QRectF(0.5, 0.5, self.width() - 1, self.height() - 1),
            DS.CornerRadius.medium, DS.CornerRadius.medium,
        )

        y = PADDING
        text_width = self.width() - 2 * PADDING
        if self._title:
            painter.setFont(self._title_font)
            painter.setPen(QColor(DS.Colors.error_red if self._is_error else DS.Colors.accent_blue))
            painter.drawText(PADDING, y, text_width, self._line_height(self._title_font),
                             Qt.AlignmentFlag.AlignLeft, self._title)
            y += self._line_height(self._title_font) + LINE_GAP

        painter.setFont(self._body_font)
        body_color = DS.Colors.text_secondary if self._placeholder else DS.Colors.text_white
        painter.setPen(QColor(body_color))
        for line in self._lines:
            painter.drawText(PADDING, y, text_width, self._line_height(self._body_font),
                             Qt.AlignmentFlag.AlignLeft, line)
            y += self._line_height(self._body_font) + LINE_GAP

        if self._hint:
            painter.setFont(self._hint_font)
            painter.setPen(QColor(DS.Colors.text_secondary))
            painter.drawText(PADDING, y, text_width, self._line_height(self._hint_font),
                             Qt.AlignmentFlag.AlignLeft, self._hint)
        painter.end()

    # ------------------------------------------------------------------
    # Fading
    # ------------------------------------------------------------------

    def _fade_out(self) -> None:
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self.windowOpacity())
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()

    def _on_fade_finished(self) -> None:
        if self.windowOpacity() <= 0.01:
            self.clear()
