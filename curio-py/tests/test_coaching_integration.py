"""Application coaching integration with real feature services and fake providers."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from curio.coaching_runtime import CoachingMode, CoachingRuntime
from curio.tutorial_coach import extract_html


def test_tutorial_preview_recovery_and_stop(qt_application):
    async def scenario():
        provider = AsyncMock()
        provider.send.return_value = json.dumps(
            {
                "steps": [
                    {"instruction": "Open File", "expected": "File menu visible", "sources": [1]}
                ]
            }
        )
        fetcher = AsyncMock()
        fetcher.fetch.return_value = extract_html(
            "<article><p>Open File to display the application menu.</p></article>",
            "https://example.com/tutorial",
        )
        capture = AsyncMock(return_value=[])
        runtime = CoachingRuntime(provider, "configured-model", capture=capture)
        runtime.tutorial.fetcher = fetcher
        runtime.set_mode(CoachingMode.TUTORIAL)
        await runtime.tutorial.prepare("https://example.com/tutorial")
        assert runtime.tutorial.state == "preview"
        runtime.tutorial.edit_step(0, "Open the File menu", "Menu visible")
        runtime.tutorial.start()
        provider.send.return_value = "Which application version is visible? [POINT:1,2:bad]"
        reply = await runtime.ask("That didn't work; I see a different panel")
        assert "version" in reply and "[POINT:" not in reply
        assert runtime.tutorial.index == 0
        capture.assert_not_awaited()
        runtime.stop_session()
        assert runtime.mode == CoachingMode.ASSISTANT
        assert runtime.tutorial.state == "stopped"
        await runtime.aclose()

    asyncio.run(scenario())


def test_tutoring_exact_error_recovery_and_independent_practice(qt_application):
    async def scenario():
        provider = AsyncMock()
        runtime = CoachingRuntime(provider, "configured-model", capture=AsyncMock())
        runtime.set_mode(CoachingMode.TUTORING)
        tutor = runtime.tutor
        tutor.start("2*x*(x^2+1)^2")
        assert tutor.submit("u=x^2+1").status == "confirmed"
        assert tutor.submit("du=x*dx").status == "incorrect"
        assert "Differentiate" in tutor.help()
        assert tutor.submit("du=2*x*dx").status == "confirmed"
        assert tutor.submit("I=u^2").status == "confirmed"
        assert tutor.submit("F=u^3/3+C").status == "confirmed"
        assert tutor.submit("F=(x^2+1)^3/3+C").completion_kind == "guided_completion"
        tutor.start_practice()
        assert "unassisted" in (await runtime.ask("Give me the answer")).lower()
        provider.send.assert_not_awaited()
        assert tutor.submit("F=(((x+1)^2+1)^3)/3+C").completion_kind == (
            "independent_demonstration"
        )
        runtime.stop_session()
        assert runtime.mode == CoachingMode.ASSISTANT
        await runtime.aclose()

    asyncio.run(scenario())


def test_voice_has_one_owner_and_returns_to_original_pipeline(qt_application, monkeypatch):
    from tests.test_walkthrough import _ask, _manager, _settle

    async def scenario():
        provider = AsyncMock()
        provider.send.return_value = "Use the power rule. [POINT:1,2:bad]"
        runtime = CoachingRuntime(provider, "configured-model", capture=AsyncMock())
        manager, parts = _manager(["Normal answer. [POINT:none]"], monkeypatch)
        manager.attach_coaching(runtime)
        runtime.set_mode(CoachingMode.TUTORING)
        runtime.tutor.start("2*x*(x^2+1)^2")
        runtime.tutor.submit("u=x^2+1")
        _ask(manager, "Why do I need du?")
        await _settle(manager)
        assert provider.send.await_count == 1
        assert not parts["llm"].requests
        assert not parts["overlays"].flights
        assert manager._history.turn_count() == 0
        assert parts["tts"].spoken == ["Use the power rule."]
        runtime.stop_session()
        _ask(manager, "Hello")
        await _settle(manager)
        assert len(parts["llm"].requests) == 1
        assert manager._history.turn_count() == 1
        await runtime.aclose()

    asyncio.run(scenario())


def test_screen_checks_are_suggestions_and_equation_recognition_requires_confirmation(
    qt_application,
):
    from tests.test_walkthrough import _screens

    async def scenario():
        provider = AsyncMock()
        provider.send.return_value = json.dumps(
            {"steps": [{"instruction": "Open File", "expected": "Menu visible", "sources": [1]}]}
        )
        runtime = CoachingRuntime(
            provider, "configured-model", capture=AsyncMock(return_value=_screens())
        )
        runtime.set_mode(CoachingMode.TUTORIAL)
        await runtime.tutorial.prepare_source(
            extract_html(
                "<article><p>Open File to display the application menu.</p></article>",
                "https://example.com/tutorial",
            )
        )
        runtime.tutorial.start()
        provider.send.return_value = json.dumps(
            {
                "status": "mismatch",
                "evidence": "A different panel is visible",
                "question": "Which application version are you using?",
            }
        )
        await runtime.tutorial.check_screen(authorized=True)
        assert runtime.tutorial.last_assessment.status == "needs_clarification"
        assert not runtime.tutorial.completions
        runtime.set_mode(CoachingMode.TUTORING)
        runtime.tutor.start("2*x*(x^2+1)^2")
        provider.send.return_value = "u=x^2+1"
        await runtime.tutor.capture_equations()
        assert runtime.tutor.substitution is None  # OCR never assesses on its own.
        assert runtime.tutor.confirm_equation("u=x^2+1").status == "confirmed"
        assert runtime._capture_fn.await_count == 2
        await runtime.aclose()

    asyncio.run(scenario())


def test_mode_switch_drops_provider_that_suppresses_cancellation(qt_application):
    async def scenario():
        started, released = asyncio.Event(), asyncio.Event()

        async def slow(*args, **kwargs):
            started.set()
            try:
                await released.wait()
            except asyncio.CancelledError:
                await released.wait()
            return "stale answer"

        provider = AsyncMock()
        provider.send.side_effect = slow
        runtime = CoachingRuntime(provider, "configured-model", capture=AsyncMock())
        runtime.set_mode(CoachingMode.TUTORING)
        runtime.tutor.start("2*x")
        replies = []
        runtime.response_ready.connect(replies.append)
        request = asyncio.create_task(runtime.ask("Help me"))
        await started.wait()
        runtime.set_mode(CoachingMode.ASSISTANT)
        released.set()
        with pytest.raises(asyncio.CancelledError):
            await request
        assert not replies
        await runtime.aclose()

    asyncio.run(scenario())


def test_sessions_do_not_learn_when_memory_disabled(qt_application, monkeypatch, tmp_path):
    from curio.memory_contract import MemorySettings
    from curio.memory_runtime import MemoryRuntime
    from tests.test_walkthrough import _ask, _manager, _settle

    async def scenario():
        config = tmp_path / "config.toml"
        config.write_text('worker_url="https://example.com"\n')
        database = tmp_path / "memory.sqlite3"
        memory = MemoryRuntime(MemorySettings(storage_path=database), config_path=config)
        provider = AsyncMock()
        provider.send.return_value = "Consider the inner expression."
        runtime = CoachingRuntime(provider, "configured-model", capture=AsyncMock())
        manager, parts = _manager([], monkeypatch)
        manager._memory = memory.conversation
        manager.attach_coaching(runtime)
        runtime.set_mode(CoachingMode.TUTORING)
        runtime.tutor.start("2*x")
        _ask(manager, "Remember that I prefer short answers")
        await _settle(manager)
        assert not parts["llm"].requests
        assert not await memory.list()
        assert not database.exists()
        manager.detach_coaching()
        await runtime.aclose()
        await memory.close()

    asyncio.run(scenario())


def test_window_mode_navigation_and_reopen(qt_application):
    from curio.ui.coaching_window import CoachingWindow

    async def scenario():
        runtime = CoachingRuntime(AsyncMock(), "configured-model", capture=AsyncMock())
        window = CoachingWindow(runtime)
        window.open_mode(CoachingMode.TUTORIAL)
        assert window.pages.currentWidget() is window.tutorial
        assert "Tutorial" in window.status.text()
        window.mode.setCurrentIndex(2)
        assert runtime.mode == CoachingMode.TUTORING
        window.close()
        assert runtime.mode == CoachingMode.ASSISTANT
        window.open_mode(CoachingMode.TUTORIAL)
        assert window.tutorial.preview.isEnabled()
        window.dispose()
        await runtime.aclose()
        window.deleteLater()

    asyncio.run(scenario())


def test_new_problem_invalidates_pending_tutor_hint(qt_application):
    async def scenario():
        started, released = asyncio.Event(), asyncio.Event()

        async def slow(*args, **kwargs):
            started.set()
            await released.wait()
            return "Hint for the old problem"

        provider = AsyncMock()
        provider.send.side_effect = slow
        runtime = CoachingRuntime(provider, "configured-model", capture=AsyncMock())
        runtime.set_mode(CoachingMode.TUTORING)
        runtime.tutor.start("2*x")
        replies = []
        runtime.response_ready.connect(replies.append)
        request = asyncio.create_task(runtime.ask("Help me"))
        await started.wait()
        runtime.tutor.start("3*x^2")
        released.set()
        with pytest.raises(asyncio.CancelledError):
            await request
        assert not replies
        await runtime.aclose()

    asyncio.run(scenario())


def test_shutdown_drains_owned_capture_and_discards_late_results(qt_application):
    from curio.ui.coaching_window import CoachingWindow

    async def scenario():
        started, released = asyncio.Event(), asyncio.Event()

        async def capture():
            started.set()
            try:
                await released.wait()
            except asyncio.CancelledError:
                await released.wait()
            return []

        provider = AsyncMock()
        runtime = CoachingRuntime(provider, "configured-model", capture=capture)
        window = CoachingWindow(runtime)
        window.open_mode(CoachingMode.TUTORING)
        runtime.tutor.start("2*x")
        window.tutoring.capture_button.click()
        await started.wait()
        closing = asyncio.create_task(window.aclose())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not closing.done()
        released.set()
        await closing
        assert not window.tutoring.confirm_button.isEnabled()
        assert not window.tutoring._tasks
        provider.send.assert_not_awaited()
        await runtime.aclose()
        window.deleteLater()

    asyncio.run(scenario())
