"""Memory management UI; services are injected by the application integration.

Construct on the Qt/qasync thread with a MemoryStore and an async save_settings
callback. Connect TrayIcon.show_memory_requested to show/raise/refresh. The
window does not create a database or persist settings itself.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from curio.design_system import DS
from curio.memory_contract import (
    ApprovalStatus,
    MemoryEvent,
    MemoryEvents,
    MemoryFilter,
    MemoryNotification,
    MemoryRecord,
    MemorySettings,
    MemorySource,
    MemoryStore,
    NotificationLevel,
    StorageMode,
)

SaveSettings = Callable[[MemorySettings], Awaitable[None]]


def _origin(record: MemoryRecord) -> str:
    if record.source == MemorySource.AUTOMATIC:
        return "Inferred"
    return "Imported" if record.source == MemorySource.IMPORT else "Explicit"


class _StaleMemoryError(Exception):
    """An edit conflicts with a newer service snapshot."""


def _date(value: datetime | None) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M %Z") if value else "Unknown"


class MemoryWindow(QWidget):
    """Async management client. No service operations run until refresh/show.

    settings_changed emits only after save_settings succeeds; operation_finished
    carries (operation, success). close cancels work and detaches subscriptions.
    Services must yield during I/O, as required by the shared async contract.
    """

    settings_changed = Signal(object)
    operation_finished = Signal(str, bool)
    PAGE_SIZE = 100

    def __init__(
        self,
        store: MemoryStore,
        *,
        settings: MemorySettings,
        save_settings: SaveSettings,
        events: MemoryEvents | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._settings = settings
        self._save_settings = save_settings
        self._events = events
        self._unsubscribers: list[Callable[[], None]] = []
        self._tasks: set[asyncio.Task] = set()
        self._busy = False
        self._refresh_pending = False
        self._limit = self.PAGE_SIZE
        self._records: tuple[MemoryRecord, ...] = ()
        self._selected: MemoryRecord | None = None
        self.setWindowTitle("Curio — Memories")
        self.setMinimumSize(600, 440)
        self.resize(900, 620)
        self.setFont(QFont("Segoe UI", 10))
        self.setStyleSheet(
            f"QWidget {{ background: {DS.Colors.panel_bg}; color: {DS.Colors.text_primary}; }}"
            f"QLineEdit, QTextEdit, QTableWidget, QComboBox {{ background: {DS.Colors.surface}; }}"
            f"QPushButton {{ padding: 6px 10px; }}"
            f"QWidget:disabled {{ color: {DS.Colors.text_secondary}; }}"
        )
        layout = QVBoxLayout(self)
        self.enabled = QCheckBox("Enable persistent memory")
        self.enabled.setToolTip("Disabling stops learning and retrieval; stored memories remain.")
        self._sync_settings()
        self.enabled.toggled.connect(self._toggle_enabled)
        layout.addWidget(self.enabled)
        self.storage_label = QLabel()
        self.storage_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.storage_label)
        self._sync_settings()

        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search memories, then press Enter")
        self.search.setAccessibleName("Search memories")
        self.search.returnPressed.connect(self.refresh)
        search_row.addWidget(self.search, 1)
        self.approval_filter = QComboBox()
        self.approval_filter.setAccessibleName("Approval filter")
        self.approval_filter.addItem("All approval states", None)
        for status in ApprovalStatus:
            self.approval_filter.addItem(status.value.title(), status)
        self.approval_filter.currentIndexChanged.connect(self.refresh)
        search_row.addWidget(self.approval_filter)
        self.refresh_button = QPushButton("Search / Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        search_row.addWidget(self.refresh_button)
        layout.addLayout(search_row)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableWidget(0, 5)
        self.table.setAccessibleName("Stored memories")
        self.table.setHorizontalHeaderLabels(
            ["Content", "Origin", "Approval", "Created", "Updated"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._select)
        splitter.addWidget(self.table)
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        self.details = QLabel("Select a memory to edit or delete.")
        self.details.setTextFormat(Qt.TextFormat.PlainText)
        self.details.setWordWrap(True)
        detail_layout.addWidget(self.details)
        self.editor = QTextEdit()
        self.editor.setAcceptRichText(False)
        self.editor.setAccessibleName("Memory content")
        self.editor.textChanged.connect(self._update_actions)
        detail_layout.addWidget(self.editor)
        buttons = QHBoxLayout()
        self.save_button = QPushButton("Save edit")
        self.save_button.clicked.connect(self.save_edit)
        self.delete_button = QPushButton("Delete memory…")
        self.delete_button.clicked.connect(self.delete_selected)
        self.approve_button = QPushButton("Approve")
        self.approve_button.clicked.connect(lambda: self.set_approval(ApprovalStatus.APPROVED))
        self.reject_button = QPushButton("Reject")
        self.reject_button.clicked.connect(lambda: self.set_approval(ApprovalStatus.REJECTED))
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.approve_button)
        buttons.addWidget(self.reject_button)
        buttons.addWidget(self.delete_button)
        buttons.addStretch()
        detail_layout.addLayout(buttons)
        splitter.addWidget(detail)
        layout.addWidget(splitter, 1)
        actions = QHBoxLayout()
        self.more_button = QPushButton("Show more")
        self.more_button.clicked.connect(self._more)
        self.export_button = QPushButton("Export all…")
        self.export_button.clicked.connect(self._choose_export)
        self.clear_button = QPushButton("Clear all memories…")
        self.clear_button.clicked.connect(self.clear_all)
        for button in (self.more_button, self.export_button, self.clear_button):
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        self.status = QLabel("Ready. Search includes expired and unapproved memories.")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        self.status.setAccessibleName("Memory operation status")
        layout.addWidget(self.status)
        self._update_actions()

    def _sync_settings(self) -> None:
        self.enabled.blockSignals(True)
        self.enabled.setChecked(
            self._settings.enabled and self._settings.storage_mode == StorageMode.LOCAL
        )
        self.enabled.blockSignals(False)
        if hasattr(self, "storage_label"):
            state = "Enabled" if self._settings.enabled else "Disabled"
            self.storage_label.setText(
                f"{state} · Storage: {self._settings.storage_mode.value} · "
                f"Automatic learning: {self._settings.automatic_learning.value}"
            )

    def set_settings(self, settings: MemorySettings) -> None:
        """Synchronize a settings snapshot after external settings_changed events."""
        self._settings = settings
        self._sync_settings()

    def _message(self, text: str, error: bool = False) -> None:
        self.status.setText(text)
        color = DS.Colors.error_red if error else DS.Colors.text_primary
        self.status.setStyleSheet(f"color: {color};")

    def _update_actions(self) -> None:
        selected = self._selected is not None and not self._busy
        self.editor.setEnabled(selected)
        self.delete_button.setEnabled(selected)
        clean = selected and self.editor.toPlainText() == self._selected.content
        self.approve_button.setEnabled(
            bool(clean) and self._selected.approval_status != ApprovalStatus.APPROVED
        )
        self.reject_button.setEnabled(
            bool(clean) and self._selected.approval_status != ApprovalStatus.REJECTED
        )
        self.save_button.setEnabled(
            selected
            and bool(self.editor.toPlainText().strip())
            and self.editor.toPlainText() != self._selected.content
        )
        for control in (
            self.enabled,
            self.refresh_button,
            self.more_button,
            self.export_button,
            self.clear_button,
            self.table,
        ):
            control.setEnabled(not self._busy)

    def _start(self, name: str, work: Callable[[], Awaitable[str]]) -> None:
        if self._busy:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._sync_settings()
            self._message("Memory operations require the application's qasync event loop.", True)
            self.operation_finished.emit(name, False)
            return
        self._busy = True
        self._update_actions()
        self._message(f"{name}…")

        async def run() -> None:
            try:
                message = await work()
            except asyncio.CancelledError:
                raise
            except _StaleMemoryError:
                self._message("Memory changed elsewhere. Refresh before editing again.", True)
                self.operation_finished.emit(name, False)
            except Exception:
                # Service exceptions can contain memory content or credentials.
                self._sync_settings()
                self._message(f"{name} failed. Check the memory service and try again.", True)
                self.operation_finished.emit(name, False)
            else:
                self._message(message)
                self.operation_finished.emit(name, True)
            finally:
                self._busy = False
                self._update_actions()
                if self._refresh_pending:
                    self._refresh_pending = False
                    self.refresh()

        task = loop.create_task(run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _fetch(self) -> None:
        filters = MemoryFilter(
            approval_status=self.approval_filter.currentData(), include_expired=True
        )
        query = self.search.text().strip()
        if query:
            records = await self._store.search(query, filters=filters, limit=self._limit)
        else:
            records = await self._store.list(filters=filters, limit=self._limit)
        self._records = records
        self._selected = None
        self.table.setRowCount(0)
        self.table.setRowCount(len(records))
        for row, record in enumerate(records):
            for col, text in enumerate(
                (
                    record.content.replace("\n", " "),
                    _origin(record),
                    record.approval_status.value,
                    _date(record.created_at),
                    _date(record.updated_at),
                )
            ):
                self.table.setItem(row, col, QTableWidgetItem(text))
        self.editor.clear()
        self.details.setText("Select a memory to edit or delete.")
        self.more_button.setVisible(len(records) >= self._limit)

    async def _reload_after(self, message: str) -> str:
        try:
            await self._fetch()
        except Exception:
            # A successful write must not be reported as failed if reload fails.
            return message + " List refresh failed; use Refresh to retry."
        return message

    def refresh(self) -> None:
        """Reload after an external mutation or on request; coalesce busy refreshes."""
        if self._busy:
            self._refresh_pending = True
            return

        async def work() -> str:
            await self._fetch()
            return f"Showing {len(self._records)} memories (up to {self._limit})."

        self._start("Load memories", work)

    def _more(self) -> None:
        self._limit += self.PAGE_SIZE
        self.refresh()

    def _select(self) -> None:
        row = self.table.currentRow()
        self._selected = self._records[row] if 0 <= row < len(self._records) else None
        if self._selected:
            r = self._selected
            expired = r.expires_at is not None and r.expires_at <= datetime.now(UTC)
            self.details.setText(
                f"{r.type.value.title()} · {r.source.value} · Confidence {r.confidence:.0%}\n"
                f"ID: {r.id}\nCreated: {_date(r.created_at)} · Updated: {_date(r.updated_at)}\n"
                f"Expires: {_date(r.expires_at) if r.expires_at else 'Never'}"
                f"{' (expired)' if expired else ''}\n"
                "Editing returns approval to pending. Updated time is not a confirmation time."
            )
            self.editor.setPlainText(r.content)
        self._update_actions()

    def save_edit(self) -> None:
        record = self._selected
        content = self.editor.toPlainText().strip()
        if record is None or not content or content == record.content:
            return

        async def work() -> str:
            current = await self._store.retrieve(record.id)
            if current != record:
                raise _StaleMemoryError
            await self._store.update(
                replace(
                    record,
                    content=content,
                    updated_at=datetime.now(UTC),
                    approval_status=ApprovalStatus.PENDING,
                )
            )
            return await self._reload_after("Memory saved. Approval is pending.")

        self._start("Save memory", work)

    def set_approval(self, status: ApprovalStatus) -> None:
        record = self._selected
        if record is None or self._busy or self.editor.toPlainText() != record.content:
            return

        async def work() -> str:
            if await self._store.retrieve(record.id) != record:
                raise _StaleMemoryError
            await self._store.update(replace(record, approval_status=status))
            return await self._reload_after(f"Memory {status.value}.")

        self._start("Review memory", work)

    def _confirm(self, title: str, message: str) -> bool:
        return (
            QMessageBox.question(
                self,
                title,
                message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        )

    def delete_selected(self) -> None:
        record = self._selected
        if record is None or self._busy:
            return
        if not self._confirm("Delete memory?", "Permanently delete this memory?"):
            return

        async def work() -> str:
            removed = await self._store.delete(record.id)
            return await self._reload_after(
                "Memory deleted." if removed else "Memory was already deleted."
            )

        self._start("Delete memory", work)

    def clear_all(self) -> None:
        if self._busy or not self._confirm(
            "Clear all memories?",
            "Permanently delete ALL memories, including hidden, expired and rejected records? "
            "Conversation history and knowledge files are kept. This cannot be undone.",
        ):
            return

        async def work() -> str:
            count = await self._store.clear()
            return await self._reload_after(f"Cleared {count} memories.")

        self._start("Clear memories", work)

    def _toggle_enabled(self, checked: bool) -> None:
        proposed = replace(
            self._settings,
            enabled=checked,
            storage_mode=StorageMode.LOCAL if checked else self._settings.storage_mode,
        )

        async def work() -> str:
            await self._save_settings(proposed)
            self.set_settings(proposed)
            self.settings_changed.emit(proposed)
            return (
                "Persistent memory enabled."
                if checked
                else "Memory disabled. Stored memories kept."
            )

        self._start("Save memory settings", work)

    def _choose_export(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export all memories", "curio-memories.txt", "Readable text (*.txt)"
        )
        if filename:
            self.export_to(Path(filename))

    def export_to(self, path: Path) -> None:
        """Export all states, ignoring current UI filters, without blocking disk I/O."""

        async def work() -> str:
            records: list[MemoryRecord] = []
            while True:
                page = await self._store.list(
                    filters=MemoryFilter(include_expired=True),
                    offset=len(records),
                    limit=self.PAGE_SIZE,
                )
                records.extend(page)
                if len(page) < self.PAGE_SIZE:
                    break
            blocks = ["Curio memory export", f"Exported: {datetime.now(UTC).isoformat()}", ""]
            for r in records:
                blocks.extend(
                    [
                        f"ID: {r.id}",
                        f"Type: {r.type.value}",
                        f"Origin: {_origin(r)} ({r.source.value})",
                        f"Approval: {r.approval_status.value}",
                        f"Confidence: {r.confidence}",
                        f"Created: {r.created_at.isoformat()}",
                        f"Updated: {r.updated_at.isoformat() if r.updated_at else 'Unknown'}",
                        f"Expires: {r.expires_at.isoformat() if r.expires_at else 'Never'}",
                        f"Preference key: {r.preference_key or ''}",
                        "Content:",
                        r.content,
                        "",
                        "---",
                        "",
                    ]
                )
            await asyncio.to_thread(path.write_text, "\n".join(blocks), encoding="utf-8")
            return f"Exported {len(records)} memories. The file contains personal information."

        self._start("Export memories", work)

    def _on_change(self, event: MemoryEvent) -> None:
        if self._selected and self.editor.toPlainText() != self._selected.content:
            self._message("Memories changed. Your unsaved edit is kept; Save checks for conflicts.")
            return
        self.refresh()

    def _on_notification(self, notification: MemoryNotification) -> None:
        self._message(notification.message, notification.level == NotificationLevel.ERROR)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._events and not self._unsubscribers:
            self._unsubscribers = [
                self._events.subscribe_changes(self._on_change),
                self._events.subscribe_notifications(self._on_notification),
            ]
        self.refresh()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._refresh_pending = False
        for task in tuple(self._tasks):
            task.cancel()
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        super().closeEvent(event)
