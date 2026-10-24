"""Real SQLite/learning/retrieval integration with temporary local settings."""

import asyncio
import subprocess
import sys
from dataclasses import replace

import pytest

from curio.config import Config
from curio.memory_contract import (
    ApprovalStatus,
    AutomaticLearningPolicy,
    ExplicitFeedback,
    MemorySettings,
    StorageMode,
)
from curio.memory_runtime import MemoryRuntime


def test_restart_preferences_correction_deletion_and_disable(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text('worker_url = "https://example.test"\n[pet]\nspecies = "cat"\n')
    settings = MemorySettings(enabled=True, storage_path=tmp_path / "memory.sqlite3")

    async def scenario():
        runtime = MemoryRuntime(settings, config_path=config_path)
        changes = []
        runtime.subscribe_changes(changes.append)
        reply = await runtime.conversation.handle_intent("remember that I prefer short answers")
        assert "pending" in reply
        (pending,) = await runtime.list()
        assert pending.preference_key == "response.verbosity"
        assert not (await runtime.conversation.select("Explain loops")).memories
        await runtime.update(replace(pending, approval_status=ApprovalStatus.APPROVED))
        await runtime.close()

        runtime = MemoryRuntime(settings, config_path=config_path)
        selection = await runtime.conversation.select("Explain loops")
        assert selection.memories[0].content == "short"
        assert "response.verbosity" in selection.prompt_text
        await runtime.conversation.handle_intent("Actually, I prefer detailed answers instead")
        replacement = next(r for r in await runtime.list() if r.content == "long")
        await runtime.update(replace(replacement, approval_status=ApprovalStatus.APPROVED))
        assert (await runtime.retrieve(pending.id)).approval_status == ApprovalStatus.REJECTED
        assert [
            r.content for r in (await runtime.conversation.select("Explain loops")).memories
        ] == ["long"]
        # An explicit reversal reuses a rejected value but still requires approval.
        await runtime.conversation.handle_intent("Actually, I prefer short answers instead")
        revived = await runtime.retrieve(pending.id)
        assert revived.approval_status == ApprovalStatus.PENDING
        assert (await runtime.conversation.select("Explain loops")).memories[0].content == "long"
        await runtime.save_settings(replace(settings, enabled=False))
        assert not (await runtime.conversation.select("Explain loops")).memories
        await runtime.conversation.handle_intent("remember that I work on Curio")
        assert len(await runtime.list()) == 2
        with pytest.raises(PermissionError):
            await runtime.persist_proposal(replace(revived, source_id="late-feedback"))
        assert not await runtime.engine.process_explicit_feedback(
            ExplicitFeedback(text="remember that I work on Curio"), settings=runtime.settings
        )
        assert "enabled = false" in config_path.read_text()
        assert 'species = "cat"' in config_path.read_text()
        await runtime.delete(replacement.id)  # Management deletion remains available disabled.
        await runtime.close()
        runtime = MemoryRuntime(settings, config_path=config_path)
        assert await runtime.retrieve(replacement.id) is None
        await runtime.close()
        assert changes

    asyncio.run(scenario())


def test_automatic_policy_and_disabled_race(tmp_path):
    async def scenario():
        path = tmp_path / "config.toml"
        path.write_text('worker_url = "https://example.test"\n')
        settings = MemorySettings(
            enabled=True,
            storage_mode=StorageMode.SESSION,
            automatic_learning=AutomaticLearningPolicy.PROPOSE,
        )
        runtime = MemoryRuntime(settings, config_path=path)
        for index in range(3):
            await runtime.conversation.learn_from_turn(
                "please be shorter", "answer", source_id=str(index)
            )
        (pending,) = await runtime.list()
        assert pending.approval_status == ApprovalStatus.PENDING
        await runtime.save_settings(replace(settings, enabled=False))
        await runtime.conversation.learn_from_turn("please be detailed", "answer", source_id="4")
        assert len(await runtime.list()) == 1  # Session records retained on disable.
        with pytest.raises(PermissionError):
            await runtime.create(replace(pending, id="another"))
        assert not (tmp_path / "memory.sqlite3").exists()
        assert Config.from_path(path).memory.enabled is False
        await runtime.close()

    asyncio.run(scenario())


def test_real_ui_approval_edit_and_settings_on_qasync(qt_application, tmp_path, monkeypatch):
    import qasync

    from curio.ui.memory_window import MemoryWindow
    from tests.test_memory_window import settle

    qt_application.setQuitOnLastWindowClosed(False)
    loop = qasync.QEventLoop(qt_application)
    asyncio.set_event_loop(loop)

    async def scenario():
        path = tmp_path / "config.toml"
        path.write_text('worker_url = "https://example.test"\n')
        runtime = MemoryRuntime(
            MemorySettings(enabled=True, storage_path=tmp_path / "m.db"), config_path=path
        )
        window = MemoryWindow(
            runtime, settings=runtime.settings, save_settings=runtime.save_settings, events=runtime
        )
        window.show()
        await settle(window)
        await runtime.conversation.handle_intent("remember that I use Python")
        await settle(window)
        assert window.table.rowCount() == 1  # CREATED callback refreshes visible UI.
        window.table.selectRow(0)
        assert window.approve_button.isEnabled()
        window.approve_button.click()
        await settle(window)
        assert window.table.item(0, 2).text() == "approved"
        window.table.selectRow(0)
        window.editor.setPlainText("I use Rust")
        window.save_button.click()
        await settle(window)
        assert window.table.item(0, 2).text() == "pending"
        window.table.selectRow(0)
        window.reject_button.click()
        await settle(window)
        assert window.table.item(0, 2).text() == "rejected"
        window.enabled.click()
        await settle(window)
        assert not runtime.settings.enabled
        monkeypatch.setattr(window, "_confirm", lambda *args: True)
        window.table.selectRow(0)
        window.delete_button.click()
        await settle(window)
        assert window.table.rowCount() == 0
        window.close()
        await runtime.close()

    with loop:
        loop.run_until_complete(scenario())
    asyncio.set_event_loop(None)


def test_preferences_reach_mock_provider_and_pointing_still_works(
    qt_application, tmp_path, monkeypatch
):
    from tests.test_walkthrough import _ask, _manager, _settle

    async def scenario():
        path = tmp_path / "config.toml"
        path.write_text('worker_url = "https://example.test"\n')
        runtime = MemoryRuntime(
            MemorySettings(enabled=True, storage_path=tmp_path / "m.db"), config_path=path
        )
        await runtime.conversation.handle_intent("remember that I prefer short answers")
        (pending,) = await runtime.list()
        await runtime.update(replace(pending, approval_status=ApprovalStatus.APPROVED))
        manager, parts = _manager([], monkeypatch)
        manager._memory = runtime.conversation

        async def send(messages, system, model):
            context = messages[-1]["content"][0]["text"]
            assert '"preference_key": "response.verbosity"' in context
            assert '"content": "short"' in context
            parts["llm"].delta.emit("Brief answer.")
            return "Brief answer. [POINT:100,100:button]"

        parts["llm"].send = send
        _ask(manager, "Explain this interface")
        await _settle(manager)
        assert parts["tts"].spoken == ["Brief answer."]
        assert len(parts["overlays"].flights) == 1
        assert manager._history.turn_count() == 1
        assert len(await runtime.list()) == 1  # No conversation archival.
        await runtime.close()

    asyncio.run(scenario())


def test_persistence_across_process_restart(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('worker_url = "https://example.test"\n')
    database = tmp_path / "memory.sqlite3"
    code = """
import asyncio, sys
from pathlib import Path
from curio.memory_runtime import MemoryRuntime
from curio.memory_contract import MemorySettings
async def main():
    runtime = MemoryRuntime(MemorySettings(enabled=True, storage_path=Path(sys.argv[1])),
                            config_path=Path(sys.argv[2]))
    if sys.argv[3] == 'write':
        await runtime.conversation.handle_intent('remember that I use Python')
    else:
        records = await runtime.list()
        assert len(records) == 1 and records[0].content == 'I use Python'
    await runtime.close()
asyncio.run(main())
"""
    for operation in ("write", "read"):
        result = subprocess.run(
            [sys.executable, "-c", code, str(database), str(path), operation],
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stderr


def test_app_initializes_shared_runtime_and_closes_it(qt_application, tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    import qasync
    from PySide6.QtCore import Signal

    from curio import app as application
    from curio.pet_config import PetSettings
    from tests.test_walkthrough import (
        FakeHotkey,
        FakeLLM,
        FakeMic,
        FakeTranscription,
        FakeTTS,
    )

    class Mic(FakeMic):
        error = Signal(str)

    class Hotkey(FakeHotkey):
        def __init__(self, **kwargs):
            super().__init__()

        def start(self):
            pass

        def stop(self):
            pass

    path = tmp_path / "config.toml"
    path.write_text('worker_url = "https://example.test"\n')
    config = Config.from_path(path)
    monkeypatch.setattr(
        application,
        "bootstrap",
        lambda: application.BootstrapResult(
            app=qt_application,
            config=config,
            config_error=None,
            was_first_run=False,
            config_path=path,
            log_dir=tmp_path,
        ),
    )
    monkeypatch.setattr(application, "configure_logging", lambda *args: None)
    monkeypatch.setattr(application.signal, "signal", lambda *args: None)
    monkeypatch.setattr(application, "MicCapture", Mic)
    monkeypatch.setattr(application, "HotkeyMonitor", Hotkey)
    monkeypatch.setattr(application, "TranscriptionClient", lambda **kwargs: FakeTranscription())
    monkeypatch.setattr(application, "LLMClient", lambda **kwargs: FakeLLM([]))
    monkeypatch.setattr(application, "TTSClient", lambda **kwargs: FakeTTS())
    companion = MagicMock(settings=PetSettings())
    tray = MagicMock(show_cursor=False)
    monkeypatch.setattr(application, "PetCompanionWidget", lambda **kwargs: companion)
    monkeypatch.setattr(application, "TrayIcon", lambda: tray)
    runtimes = []

    def make_runtime(*args, **kwargs):
        runtime = MemoryRuntime(*args, **kwargs)
        runtimes.append(runtime)
        return runtime

    monkeypatch.setattr(application, "MemoryRuntime", make_runtime)
    original_loop = qasync.QEventLoop

    def make_loop(app):
        loop = original_loop(app)
        loop.call_soon(loop.stop)
        return loop

    monkeypatch.setattr(application.qasync, "QEventLoop", make_loop)
    assert application.run() == 0
    assert len(runtimes) == 1
    assert runtimes[0]._store._closed
    tray.show_memory_requested.connect.assert_called()
    assert not (tmp_path / "memory.sqlite3").exists()
    asyncio.set_event_loop(None)
