"""Deterministic demo: real manager, SQLite and loopback HTTP; fake perception/providers."""

import asyncio
import json
import threading
from dataclasses import replace

from curio.learning_contract import AssistanceLevel, StepOutcome
from curio.live_tutoring import TutoringService
from curio.map_sync.server import make_server
from tests.test_learning_end_to_end import _laptop, _manager_with, _walk
from tests.test_walkthrough import _ask, _settle


def test_demo_recovery_restart_and_shared_context(tmp_path, monkeypatch):
    server = make_server("127.0.0.1", 0, tmp_path / "map.json", rate_per_minute=0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()

    async def run():
        a = _laptop(tmp_path / "a", server.url, share=True)
        b = _laptop(tmp_path / "b", server.url, share=False)
        from tests.test_learning_integration import PIVOT_REPLIES

        try:
            manager, parts = _manager_with(a, list(PIVOT_REPLIES), monkeypatch)
            fresh = await a.prompt_text(
                app="excel",
                task="how do i insert a pivot table",
                point_coords="pixel",
                image_size=(1280, 720),
            )
            await _walk(manager, parts)
            events = await a.event_log.recent()
            assert sorted(e.outcome.value for e in events) == [
                "retried",
                "succeeded",
                "succeeded",
            ]
            await b.start()
            later = await b.prompt_text(
                app="excel",
                task="how do i insert a pivot table",
                point_coords="pixel",
                image_size=(1280, 720),
            )
            assert "from shared records" in later
            assert "click insert again" in later
            assert "from shared records" not in (fresh or "")
            assert "Book1" not in (tmp_path / "map.json").read_text()
            # Recreate the SQLite reader: persistence, not an in-memory cache.
            from curio.learning_events import SqliteEventLog

            restarted = SqliteEventLog(tmp_path / "a" / "events.sqlite3")
            assert len(await restarted.recent()) == 3
            from curio.task_map import SqliteTaskMap

            reopened = SqliteTaskMap(tmp_path / "b" / "task_map.sqlite3")
            try:
                assert await reopened.find("excel", "how do i insert a pivot table")
            finally:
                await reopened.close()
            print(
                json.dumps(
                    {
                        "evidence": "mocked model-reported completion",
                        "outcomes": [e.outcome.value for e in events],
                        "retrieved": later,
                    }
                )
            )
        finally:
            await a.aclose()
            await b.aclose()

    try:
        asyncio.run(run())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        assert not thread.is_alive()


def test_request_construction_text_vs_screenshot(monkeypatch):
    from curio import companion_manager
    from tests.test_learning_integration import _manager
    from tests.test_walkthrough import _screens

    async def request(capture):
        manager, parts = _manager(["Try Insert. [POINT:none]"], monkeypatch)
        manager._screen_capture_fn = capture
        _ask(manager, "how do i insert a pivot table")
        await _settle(manager)
        await parts["learning"].aclose()
        content = parts["llm"].requests[0][-1]["content"]
        return (
            [{"type": "text", "text": content}] if isinstance(content, str) else content
        )

    monkeypatch.setattr(
        companion_manager, "get_foreground_window_title", lambda: "Excel"
    )
    text = asyncio.run(request(lambda: []))
    grounded = asyncio.run(request(_screens))
    assert not any(b["type"] == "image" for b in text)
    assert sum(b["type"] == "image" for b in grounded) == 1
    print(
        "Text-only: 0 image blocks; synthetic screenshot: 1 image block. No usability claim."
    )


def test_assistance_evidence_histories(tmp_path):
    from curio.learning_contract import StepEvent, WalkthroughSummary
    from curio.skills import ConceptGraph, SqliteSkillModel

    async def run():
        model = SqliteSkillModel(tmp_path / "skills.sqlite3", graph=ConceptGraph.load())
        fresh = await model.recommend_assistance("excel", ["pivot tables"])
        for i in range(12):
            step = StepEvent(
                walkthrough_id=str(i),
                app="excel",
                task="pivot",
                step_index=1,
                instruction="Insert pivot",
                concepts=("pivot tables",),
                assistance=AssistanceLevel.NONE,
                outcome=StepOutcome.SUCCEEDED,
            )
            await model.observe(
                WalkthroughSummary(
                    walkthrough_id=str(i),
                    app="excel",
                    task="pivot",
                    steps=(step,),
                    completed=True,
                )
            )
        experienced = await model.recommend_assistance("excel", ["pivot tables"])
        assert list(AssistanceLevel).index(experienced) > list(AssistanceLevel).index(
            fresh
        )
        before = await model.snapshot()
        await model.observe(
            WalkthroughSummary(
                walkthrough_id="cancel",
                app="excel",
                task="pivot",
                steps=(replace(step, id="cancel", outcome=StepOutcome.ABANDONED),),
                completed=False,
            )
        )
        assert (await model.snapshot())[0].attempts == before[0].attempts
        print(
            f"Seeded evidence histories: fresh={fresh}; 12 unassisted reports={experienced}"
        )

    asyncio.run(run())


def test_model_claim_cannot_override_exact_math():
    tutor = TutoringService()
    tutor.start("2*x*(x^2+1)^2")
    tutor.submit("u=x^2+1")
    # Simulated model says both equations are correct; exact checker disagrees on the first.
    assert tutor.submit("du=x*dx").status == "incorrect"
    assert tutor.submit("du=2*x*dx").status == "confirmed"
    assert tutor.submit("I=u^2").status == "confirmed"
    result = tutor.submit("F=(x^2+1)^3/3+C")
    assert result.completion_kind == "guided_completion"
    print(
        "Mock model claims 2/2 correct; exact verifier: incorrect, confirmed; recovery guided."
    )


def test_disabled_learning_does_not_construct_stores(monkeypatch):
    from curio import app
    from curio.config import Config, LearningSettings

    def forbidden(*args, **kwargs):
        raise AssertionError("disabled learning constructed a persistence component")

    monkeypatch.setattr(app, "SqliteTaskMap", forbidden)
    config = Config(
        worker_url="",
        hotkey="ctrl+alt",
        default_model="m",
        log_level="INFO",
        knowledge_dir=None,
        learning=LearningSettings(enabled=False),
    )
    assert app._build_learning(config) is None
