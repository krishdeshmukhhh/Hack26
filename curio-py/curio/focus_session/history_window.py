"""Saved focus sessions, newest first, with delete-all (section F, Privacy).

Construct on the Qt/qasync thread with a SessionStore. Loads on show; the
store runs SQLite off the UI thread. Everything listed here is all Curio
keeps about focus sessions, so "Delete all" really empties it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from curio.design_system import DS
from curio.focus_contract import SessionStore, SessionSummary
from curio.focus_session.session_window import minutes_text

COLUMNS = ("Date", "Goal", "On goal", "Drifting", "Breaks", "Drifts", "False alarms", "Reflection")


def _row(summary: SessionSummary) -> tuple[str, ...]:
    return (
        summary.started_at.astimezone().strftime("%Y-%m-%d %H:%M"),
        summary.goal,
        minutes_text(summary.on_goal_seconds),
        minutes_text(summary.off_goal_seconds),
        minutes_text(summary.break_seconds),
        str(summary.drift_count),
        str(summary.false_alarms),
        summary.reflection,
    )


def _ask(parent: QWidget) -> bool:
    return (
        QMessageBox.question(
            parent,
            "Delete all focus history?",
            "Permanently delete every saved focus session summary, your \"not a distraction\" "
            "corrections and your review questions? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        == QMessageBox.StandardButton.Yes
    )


class FocusHistoryWindow(QWidget):
    operation_finished = Signal(str, bool)
    LIMIT = 200

    def __init__(
        self,
        store: SessionStore,
        *,
        confirm: Callable[[QWidget], bool] = _ask,
        clear_extra: Sequence[Callable[[], Awaitable[object]]] = (),
        parent=None,
    ):
        """``clear_extra``: other focus data cleared by "Delete all" (corrections, reviews)."""
        super().__init__(parent)
        self._store = store
        self._clear_extra = tuple(clear_extra)
        self._confirm = confirm
        self._tasks: set[asyncio.Task] = set()
        self._busy = False
        self.summaries: tuple[SessionSummary, ...] = ()
        self.setWindowTitle("Curio — Focus history")
        self.setFont(QFont("Segoe UI", 10))
        self.resize(820, 420)
        self.setStyleSheet(
            f"QWidget {{ background: {DS.Colors.panel_bg}; color: {DS.Colors.text_primary}; }}"
            f"QTableWidget {{ background: {DS.Colors.surface}; }}"
            f"QPushButton {{ padding: 6px 10px; }}"
        )
        layout = QVBoxLayout(self)
        note = QLabel(
            "Session summaries stay on this computer. Window titles and activity samples "
            "aren't kept. Delete all also removes your corrections and review questions."
        )
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {DS.Colors.text_secondary};")
        layout.addWidget(note)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setAccessibleName("Saved focus sessions")
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        self.clear_button = QPushButton("Delete all history…")
        self.clear_button.clicked.connect(self.clear_all)
        actions.addWidget(self.refresh_button)
        actions.addWidget(self.clear_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.status = QLabel("")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setAccessibleName("Focus history status")
        layout.addWidget(self.status)

    def _start(self, name: str, work: Callable[[], Awaitable[str]]) -> None:
        if self._busy:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.status.setText("Focus history needs the application's event loop.")
            self.operation_finished.emit(name, False)
            return
        self._busy = True
        self.refresh_button.setEnabled(False)
        self.clear_button.setEnabled(False)

        async def run() -> None:
            try:
                message = await work()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.status.setText(f"{name} failed. Try again.")
                self.operation_finished.emit(name, False)
            else:
                self.status.setText(message)
                self.operation_finished.emit(name, True)
            finally:
                self._busy = False
                self.refresh_button.setEnabled(True)
                self.clear_button.setEnabled(True)

        task = loop.create_task(run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _fetch(self) -> None:
        self.summaries = await self._store.summaries(self.LIMIT)
        self.table.setRowCount(len(self.summaries))
        for row, summary in enumerate(self.summaries):
            for col, text in enumerate(_row(summary)):
                self.table.setItem(row, col, QTableWidgetItem(text))

    def refresh(self) -> None:
        async def work() -> str:
            await self._fetch()
            count = len(self.summaries)
            return f"{count} saved session{'s' if count != 1 else ''}."

        self._start("Load history", work)

    def clear_all(self) -> None:
        if self._busy or not self._confirm(self):
            return

        async def work() -> str:
            await self._store.clear()
            for clear in self._clear_extra:
                await clear()
            await self._fetch()
            return "Focus history deleted."

        self._start("Delete history", work)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def closeEvent(self, event) -> None:
        for task in tuple(self._tasks):
            task.cancel()
        super().closeEvent(event)
