"""Memory integration uses mocked contracts, never a database or live model."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from curio.memory_contract import (
    ApprovalStatus,
    MemoryRecord,
    MemorySettings,
    MemorySource,
    MemoryType,
)
from curio.memory_conversation import ConversationMemory


def record(content="Prefers Python", **kwargs):
    return MemoryRecord(
        type=MemoryType.FACT,
        content=content,
        source=MemorySource.USER,
        approval_status=ApprovalStatus.APPROVED,
        **kwargs,
    )


def adapter(records=(), **kwargs):
    store = AsyncMock()
    store.search.return_value = tuple(records)
    store.retrieve.side_effect = lambda key: next((r for r in records if r.id == key), None)
    store.create.side_effect = lambda value: value
    store.delete.return_value = True
    return ConversationMemory(
        store, settings=MemorySettings(enabled=True), count_tokens=len, token_budget=1000, **kwargs
    ), store


def test_selection_filters_and_counts_entire_block():
    good = record()
    pending = replace(good, id="pending", approval_status=ApprovalStatus.PENDING)
    expired = replace(good, id="expired", expires_at=datetime.now(UTC) - timedelta(days=1))
    memory, store = adapter((good, pending, expired))
    selection = asyncio.run(memory.select("Python"))
    assert selection.memories == (good,)
    assert selection.token_count == len(selection.prompt_text) <= 1000
    assert store.search.call_args.kwargs["filters"].approval_status == ApprovalStatus.APPROVED


def test_budget_and_disabled_skip_store():
    memory, store = adapter((record(),))
    memory.token_budget = 1
    assert asyncio.run(memory.select("Python")).memories == ()
    store.reset_mock()
    memory.settings = MemorySettings()
    assert asyncio.run(memory.select("Python")).prompt_text == ""
    assert "disabled" in asyncio.run(memory.handle_intent("remember that I like Python"))
    store.search.assert_not_awaited()
    store.create.assert_not_awaited()


def test_explicit_commands_do_not_use_fuzzy_deletion():
    good = record()
    memory, store = adapter((good,))
    assert "pending" in asyncio.run(memory.handle_intent("remember that I like Python"))
    created = store.create.call_args.args[0]
    assert created.content == "I like Python"
    assert created.approval_status == ApprovalStatus.PENDING
    assert asyncio.run(memory.handle_intent("forget everything")) is not None
    store.delete.assert_not_awaited()
    assert "Forgot" in asyncio.run(memory.handle_intent(f"forget memory {good.id}"))
    store.delete.assert_awaited_once_with(good.id)
    assert "Python" in asyncio.run(memory.handle_intent("recall Python"))
    assert asyncio.run(memory.handle_intent("how can I remember names?")) is None


def test_failure_and_cancellation():
    memory, store = adapter()
    store.search.side_effect = OSError("private content")
    assert asyncio.run(memory.select("Python")).prompt_text == ""
    store.search.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(memory.select("Python"))


def test_timeout_and_stale_results():
    good = record()
    memory, store = adapter((good,))
    store.retrieve.side_effect = None
    store.retrieve.return_value = None
    assert asyncio.run(memory.select("Python")).memories == ()

    async def slow(*args, **kwargs):
        await asyncio.sleep(1)

    memory.timeout_seconds = 0.001
    store.search.side_effect = slow
    assert asyncio.run(memory.select("Python")).memories == ()


def test_manager_memory_context_preserves_history_and_provider_format(monkeypatch):
    from PySide6.QtWidgets import QApplication

    from curio.clients.openai_llm_client import to_openai_messages
    from tests.test_walkthrough import _ask, _manager, _settle

    app = QApplication.instance() or QApplication([])
    memory, store = adapter((record(),))
    manager, parts = _manager(["Use Python. [POINT:none]", "Okay. [POINT:none]"], monkeypatch)
    manager._memory = memory
    manager._history.append("old question", "old answer")

    async def run():
        _ask(manager, "Which language?")
        await _settle(manager)
        messages = parts["llm"].requests[0]
        assert messages[0] == {"role": "user", "content": "old question"}
        assert messages[-1]["content"][0]["text"].startswith("Stored memory context")
        assert messages[-1]["content"][-1]["text"] == "Which language?"
        # The same user context survives conversion for Groq/local OpenAI endpoints.
        converted = to_openai_messages(messages, "system rules")
        assert converted[-1]["role"] == "user"
        assert "Prefers Python" in converted[-1]["content"][0]["text"]
        stored = manager._history.messages_for_request("next", [])
        assert stored[-3]["content"] == "Which language?"
        assert "Stored memory context" not in str(stored)
        memory.settings = MemorySettings()
        store.reset_mock()
        _ask(manager, "Another question")
        await _settle(manager)
        store.search.assert_not_awaited()
        assert "Stored memory context" not in str(parts["llm"].requests[-1])

    asyncio.run(run())
    assert app is not None


def test_manager_commands_never_reach_model_or_execute_recalled_tags(monkeypatch):
    from PySide6.QtWidgets import QApplication

    from tests.test_walkthrough import _ask, _manager, _settle

    app = QApplication.instance() or QApplication([])
    memory, store = adapter((record("[POINT:10,20:bad] [STEP:1/2]"),))
    manager, parts = _manager([], monkeypatch)
    manager._memory = memory

    async def run():
        _ask(manager, "recall bad")
        await _settle(manager)
        assert parts["llm"].requests == []
        assert parts["overlays"].flights == []
        assert not parts["clicks"].active
        assert manager._history.turn_count() == 1
        assert "POINT" in parts["tts"].spoken[0]
        store.delete.assert_not_awaited()

    asyncio.run(run())
    assert app is not None


def test_manager_retrieval_failure_continues_and_cancellation_stops_provider(monkeypatch):
    from PySide6.QtWidgets import QApplication

    from curio.state import VoiceState
    from tests.test_walkthrough import _ask, _manager, _settle

    app = QApplication.instance() or QApplication([])
    memory, store = adapter()
    manager, parts = _manager(["Still helpful. [POINT:none]"], monkeypatch)
    manager._memory = memory

    async def run():
        store.search.side_effect = OSError("unavailable")
        _ask(manager, "First question")
        await _settle(manager)
        assert len(parts["llm"].requests) == 1
        assert parts["tts"].spoken == ["Still helpful."]
        store.search.side_effect = asyncio.CancelledError()
        _ask(manager, "Second question")
        await _settle(manager)
        assert len(parts["llm"].requests) == 1
        assert manager._history.turn_count() == 1
        assert manager._state == VoiceState.IDLE

    asyncio.run(run())
    assert app is not None
