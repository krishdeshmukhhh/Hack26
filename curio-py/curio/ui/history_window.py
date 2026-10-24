"""Live-tail conversation history window."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QTextEdit, QVBoxLayout, QWidget

from curio.design_system import DS

logger = logging.getLogger(__name__)


class HistoryWindow(QWidget):
    """Scrollable conversation history — live-updates as turns come in."""

    MIN_W = 450
    MIN_H = 350

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Curio — History")
        self.setMinimumSize(self.MIN_W, self.MIN_H)
        self.resize(500, 500)
        # Normal window, not overlay
        self.setWindowFlags(
            Qt.WindowType.Window | Qt.WindowType.WindowCloseButtonHint
        )
        self.setStyleSheet(
            f"background-color: {DS.Colors.panel_bg};"
        )

        self._text = QTextEdit(self)
        self._text.setReadOnly(True)
        self._text.setFrameShape(QTextEdit.Shape.NoFrame)
        self._text.setStyleSheet(
            f"color: {DS.Colors.text_primary}; background-color: {DS.Colors.panel_bg};"
            f" selection-background-color: {DS.Colors.accent_blue};"
        )
        font = QFont("Segoe UI", 11)
        self._text.setFont(font)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self._text)

        self._auto_scroll = True
        self._text.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self._text.verticalScrollBar().rangeChanged.connect(self._maybe_scroll)

        # Track current in-progress turn
        self._has_interim = False
        self._building_response = False

    def _on_scroll(self, value: int) -> None:
        """Detect if user scrolled away from bottom."""
        sb = self._text.verticalScrollBar()
        self._auto_scroll = value >= sb.maximum() - 20

    def _maybe_scroll(self) -> None:
        """Auto-scroll to bottom if user hasn't scrolled up."""
        if self._auto_scroll:
            sb = self._text.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _append_label(self, label: str, color: str) -> None:
        """Append a colored label (e.g. 'You:' or 'Curio:')."""
        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        fmt.setFontWeight(QFont.Weight.Bold)
        cursor.insertText(label, fmt)
        self._text.setTextCursor(cursor)

    def _append_text(self, text: str, color: str, *, italic: bool = False) -> None:
        """Append plain text with the given color."""
        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if italic:
            fmt.setFontItalic(True)
        cursor.insertText(text, fmt)
        self._text.setTextCursor(cursor)

    @Slot(str)
    def append_interim(self, text: str) -> None:
        """Show interim (in-progress) transcription — replaces previous interim."""
        if not self._has_interim:
            self._append_label("\nYou: ", DS.Colors.text_secondary)
            self._has_interim = True
        else:
            # Remove previous interim text and re-append
            cursor = self._text.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            # Select back to after the label
            cursor.movePosition(
                QTextCursor.MoveOperation.StartOfBlock,
                QTextCursor.MoveMode.KeepAnchor,
            )
            # Keep "You: " prefix (5 chars)
            cursor.movePosition(
                QTextCursor.MoveOperation.Right,
                QTextCursor.MoveMode.MoveAnchor,
                5,
            )
            cursor.movePosition(
                QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor
            )
            cursor.removeSelectedText()
        self._append_text(text, DS.Colors.interim_text, italic=True)

    @Slot(str)
    def set_final(self, text: str) -> None:
        """Finalize user transcription — replace interim with final text."""
        if self._has_interim:
            # Clear interim line
            cursor = self._text.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            cursor.movePosition(
                QTextCursor.MoveOperation.StartOfBlock,
                QTextCursor.MoveMode.KeepAnchor,
            )
            cursor.removeSelectedText()
            # Remove the newline too
            cursor.deletePreviousChar()
        self._has_interim = False
        self._append_label("\nYou: ", DS.Colors.accent_blue)
        self._append_text(text + "\n", DS.Colors.text_primary)

    @Slot(str)
    def append_delta(self, text: str) -> None:
        """Append streaming response text from Claude."""
        if not self._building_response:
            self._append_label("Curio: ", DS.Colors.companion_responding)
            self._building_response = True
        self._append_text(text, DS.Colors.text_primary)

    @Slot()
    def commit_turn(self, _text: str = "") -> None:
        """Finalize the current turn — add spacing."""
        if self._building_response:
            self._append_text("\n", DS.Colors.text_primary)
        self._building_response = False

    @Slot(str)
    def show_error(self, msg: str) -> None:
        """Show an error line in red."""
        self._append_label("\n⚠ Error: ", DS.Colors.companion_error)
        self._append_text(msg + "\n", DS.Colors.error_red)
