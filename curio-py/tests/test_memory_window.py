"""Offscreen UI checks with async memory services; no database or model needed."""

import asyncio
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from curio.memory_contract import (
    ApprovalStatus,
    MemoryEvent,
    MemoryEventType,
    MemoryNotification,
    MemoryRecord,
    MemorySettings,
    MemorySource,
    MemoryType,
    NotificationLevel,
    StorageMode,
)
from curio.ui.memory_window import MemoryWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def record(**kwargs):
    return MemoryRecord(**{
        "type": MemoryType.FACT, "content": "Prefers short explanations",
        "source": MemorySource.USER, "approval_status": ApprovalStatus.APPROVED, **kwargs,
    })


def make_window(records=(), **kwargs):
    store = AsyncMock()
    store.list.return_value = tuple(records)
    store.search.return_value = tuple(records)
    store.retrieve.return_value = records[0] if records else None
    store.delete.return_value = True
    store.clear.return_value = len(records)
    save = AsyncMock()
    window = MemoryWindow(
        store, settings=kwargs.pop("settings", MemorySettings()), save_settings=save, **kwargs,
    )
    return window, store, save


async def settle(window):
    while window._tasks:
        await asyncio.gather(*tuple(window._tasks), return_exceptions=True)
        await asyncio.sleep(0)


def test_load_search_filter_and_origin(app):
    async def scenario():
        explicit = record()
        inferred = record(source=MemorySource.AUTOMATIC, approval_status=ApprovalStatus.PENDING)
        window, store, _ = make_window([explicit, inferred])
        window.refresh()
        await settle(window)
        assert window.table.rowCount() == 2
        assert window.table.item(0, 1).text() == "Explicit"
        assert window.table.item(1, 1).text() == "Inferred"
        assert window.table.item(1, 2).text() == "pending"
        assert str(explicit.created_at.year) in window.table.item(0, 3).text()
        window.table.selectRow(0)
        assert explicit.id in window.details.text()
        assert "not a confirmation time" in window.details.text()
        window.search.setText("short")
        window.approval_filter.setCurrentIndex(2)  # approved
        await settle(window)
        args = store.search.call_args
        assert args.args == ("short",)
        assert args.kwargs["filters"].approval_status == ApprovalStatus.APPROVED
        assert args.kwargs["filters"].include_expired
        window.close()

    asyncio.run(scenario())


def test_edit_preserves_identity_and_requires_reapproval(app):
    async def scenario():
        original = record()
        window, store, _ = make_window([original])
        completed = []
        window.operation_finished.connect(lambda *args: completed.append(args))
        window.refresh()
        await settle(window)
        window.table.selectRow(0)
        window.editor.setPlainText("New preference")
        assert window.save_button.isEnabled()
        window.save_button.click()
        await settle(window)
        saved = store.update.call_args.args[0]
        assert saved.id == original.id and saved.created_at == original.created_at
        assert saved.content == "New preference"
        assert saved.updated_at >= original.updated_at
        assert saved.approval_status == ApprovalStatus.PENDING
        assert ("Save memory", True) in completed
        assert "saved" in window.status.text()
        window.close()

    asyncio.run(scenario())


def test_blank_edit_and_stale_edit_do_not_write(app):
    async def scenario():
        original = record()
        window, store, _ = make_window([original])
        window.refresh()
        await settle(window)
        window.table.selectRow(0)
        window.editor.setPlainText("   ")
        assert not window.save_button.isEnabled()
        window.save_edit()
        store.update.assert_not_called()
        window.editor.setPlainText("Changed")
        store.retrieve.return_value = replace(original, content="Edited elsewhere")
        window.save_edit()
        await settle(window)
        store.update.assert_not_called()
        assert "changed elsewhere" in window.status.text()
        assert window.editor.toPlainText() == "Changed"
        window.close()

    asyncio.run(scenario())


def test_delete_and_clear_require_confirmation(app, monkeypatch):
    async def scenario():
        original = record()
        window, store, _ = make_window([original])
        window.refresh()
        await settle(window)
        window.table.selectRow(0)
        monkeypatch.setattr(window, "_confirm", lambda *args: False)
        window.delete_selected()
        window.clear_all()
        store.delete.assert_not_called()
        store.clear.assert_not_called()
        monkeypatch.setattr(window, "_confirm", lambda *args: True)
        window.delete_selected()
        await settle(window)
        store.delete.assert_awaited_once_with(original.id)
        window.clear_all()
        await settle(window)
        store.clear.assert_awaited_once()
        assert "Cleared 1" in window.status.text()
        window.close()

    asyncio.run(scenario())


def test_settings_failure_rolls_back_and_success_emits(app):
    async def scenario():
        window, _, save = make_window(settings=MemorySettings(storage_mode=StorageMode.SESSION))
        changed = []
        window.settings_changed.connect(changed.append)
        save.side_effect = OSError("secret path")
        window.enabled.click()
        await settle(window)
        assert not window.enabled.isChecked()
        assert changed == []
        assert "failed" in window.status.text() and "secret" not in window.status.text()
        save.side_effect = None
        window.enabled.click()
        await settle(window)
        assert changed[-1].enabled
        assert changed[-1].storage_mode == StorageMode.LOCAL
        window.enabled.click()
        await settle(window)
        assert not changed[-1].enabled
        window.close()

    asyncio.run(scenario())


def test_failed_load_and_update_are_recoverable(app):
    async def scenario():
        window, store, _ = make_window([record()])
        store.list.side_effect = OSError("private content")
        window.refresh()
        await settle(window)
        assert "failed" in window.status.text()
        assert window.refresh_button.isEnabled()
        store.list.side_effect = None
        window.refresh()
        await settle(window)
        window.table.selectRow(0)
        window.editor.setPlainText("Try again")
        store.update.side_effect = OSError("private content")
        window.save_edit()
        await settle(window)
        assert window.editor.toPlainText() == "Try again"
        assert "private" not in window.status.text()
        window.close()

    asyncio.run(scenario())


def test_write_success_with_failed_reload_is_reported_truthfully(app):
    async def scenario():
        window, store, _ = make_window([record()])
        window.refresh()
        await settle(window)
        window.table.selectRow(0)
        window.editor.setPlainText("Changed")
        store.list.side_effect = OSError()
        window.save_edit()
        await settle(window)
        store.update.assert_awaited_once()
        assert "saved" in window.status.text() and "refresh failed" in window.status.text()
        window.close()

    asyncio.run(scenario())


def test_export_all_pages_ignores_filters_and_handles_failure(app, tmp_path):
    async def scenario():
        first_page = tuple(record(content=f"Memory {i}") for i in range(100))
        expired = record(
            content="Unicode café\nSecond line", source=MemorySource.AUTOMATIC,
            approval_status=ApprovalStatus.REJECTED,
            created_at=datetime.now(UTC) - timedelta(days=2),
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
        window, store, _ = make_window()
        window.search.setText("irrelevant")
        store.list.side_effect = [first_page, (expired,)]
        target = tmp_path / "memories.txt"
        window.export_to(target)
        await settle(window)
        text = target.read_text(encoding="utf-8")
        assert "Unicode café\nSecond line" in text
        assert "Inferred (automatic)" in text and "Approval: rejected" in text
        assert "Exported 101" in window.status.text()
        assert store.list.call_args.kwargs["offset"] == 100
        assert store.list.call_args.kwargs["filters"].approval_status is None
        store.list.side_effect = None
        window.export_to(tmp_path / "missing" / "out.txt")
        await settle(window)
        assert "failed" in window.status.text()
        window.close()

    asyncio.run(scenario())


def test_slow_service_keeps_qt_responsive_and_cancels_on_close(app):
    async def scenario():
        window, store, _ = make_window()
        gate = asyncio.Event()

        async def delayed(**kwargs):
            await gate.wait()
            return ()

        store.list.side_effect = delayed
        window.refresh()
        await asyncio.sleep(0)
        assert not window.clear_button.isEnabled()
        ticks = []
        QTimer.singleShot(0, lambda: ticks.append(True))
        app.processEvents()
        assert ticks == [True] and window._busy
        window.close()
        await settle(window)
        assert not window._busy and not window._tasks

    asyncio.run(scenario())


def test_show_more_and_coalesced_refresh(app):
    async def scenario():
        window, store, _ = make_window(tuple(record() for _ in range(100)))
        window.refresh()
        await settle(window)
        window._more()
        window.refresh()  # coalesced while loading
        await settle(window)
        assert store.list.call_args.kwargs["limit"] == 200
        assert store.list.await_count == 3
        window.close()

    asyncio.run(scenario())


def test_event_subscriptions_detach_and_reopen(app):
    class Events:
        changes = []
        notifications = []

        def subscribe_changes(self, callback):
            self.changes.append(callback)
            return lambda: self.changes.remove(callback)

        def subscribe_notifications(self, callback):
            self.notifications.append(callback)
            return lambda: self.notifications.remove(callback)

    async def scenario():
        events = Events()
        window, store, _ = make_window(events=events)
        window.show()
        await settle(window)
        assert len(events.changes) == 1
        events.changes[0](MemoryEvent(type=MemoryEventType.CLEARED))
        await settle(window)
        assert store.list.await_count == 2
        events.notifications[0](MemoryNotification(
            code="memory.storage_error", message="Storage unavailable",
            level=NotificationLevel.ERROR,
        ))
        assert window.status.text() == "Storage unavailable"
        window.close()
        assert not events.changes and not events.notifications
        window.show()
        await settle(window)
        assert len(events.changes) == 1
        assert not window.grab().isNull()
        window.close()

    asyncio.run(scenario())


def test_tray_memory_action_emits(app):
    from curio.ui.tray_icon import TrayIcon

    tray = TrayIcon()
    requested = []
    tray.show_memory_requested.connect(lambda: requested.append(True))
    action = next(a for a in tray.contextMenu().actions() if a.text() == "Memories")
    action.trigger()
    assert requested == [True]


def test_external_change_preserves_unsaved_edit(app):
    async def scenario():
        window, store, _ = make_window([record()])
        window.refresh()
        await settle(window)
        window.table.selectRow(0)
        window.editor.setPlainText("Unsaved edit")
        window._on_change(MemoryEvent(type=MemoryEventType.UPDATED))
        await settle(window)
        assert window.editor.toPlainText() == "Unsaved edit"
        assert store.list.await_count == 1
        assert "unsaved edit is kept" in window.status.text()
        window.close()

    asyncio.run(scenario())
