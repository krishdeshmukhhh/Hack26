"""Offscreen smoke tests for the start panel, timeline, summary and history windows."""

import asyncio
from datetime import UTC, datetime, timedelta

from curio.focus_contract import BreakStyle, IfThenPlan, InterventionKind, InterventionResponse
from curio.focus_session import SqliteSessionStore, build_plan
from curio.focus_session.history_window import FocusHistoryWindow
from curio.focus_session.presenter import FocusPresenter
from curio.focus_session.session_window import FocusSessionWindow, minutes_text
from curio.focus_session.start_panel import FocusStartPanel
from curio.focus_session.summary_window import SessionSummaryWindow, next_review_text
from curio.focus_session.timeline import TimelineState
from tests.test_focus_session_fakes import (
    EXCEL,
    T0,
    YOUTUBE,
    Clock,
    close,
    drain,
    feed,
    make_runtime,
    review_item,
    steps,
)


async def _settle():
    for _ in range(5):
        await asyncio.sleep(0)


async def _idle(window):
    while window._tasks:
        await asyncio.gather(*tuple(window._tasks))


def test_start_panel_prefill_suggest_edit_and_start():
    async def scenario():
        async def suggest(goal):
            assert goal == "excel assignment"
            return (IfThenPlan(cue="i open youtube", response="close it", cue_apps=("youtube",)),)

        panel = FocusStartPanel(suggest=suggest, foreground_app=lambda: "excel", clock=Clock())
        plans = []
        panel.plan_ready.connect(plans.append)
        panel.prefill("excel assignment", 30)
        assert panel.allowed.text() == "excel" and panel.minutes.value() == 30
        assert not panel.strict.isChecked()
        assert panel.break_style.currentData() == BreakStyle.FIXED
        await _settle()
        assert len(panel.rows) == 1
        assert panel.rows[0].text.text() == "if i open youtube, then close it"
        row = panel.add_row()
        row.text.setText("this is not a plan")
        panel.start()
        assert plans == [] and "if" in panel.status.text()
        row.use.setChecked(False)
        panel.strict.setChecked(True)
        panel.start()
        (plan,) = plans
        assert plan.goal == "excel assignment" and plan.duration == timedelta(minutes=30)
        assert plan.if_then[0].cue_apps == ("youtube",) and plan.strict
        assert plan.allowed_apps == ("excel",) and plan.started_at == T0
        panel.close()

    asyncio.run(scenario())


def test_start_panel_requires_goal_and_survives_failed_suggestion():
    async def scenario():
        async def broken(goal):
            raise RuntimeError

        panel = FocusStartPanel(suggest=broken)
        panel.request_suggestions()
        assert "working on" in panel.status.text()
        panel.goal.setText("essay")
        panel.request_suggestions()
        await _settle()
        assert "write your own" in panel.status.text()
        assert panel.suggest_button.isEnabled()
        panel.goal.setText("")
        panel.start()
        assert "working on" in panel.status.text()
        panel.close()

    asyncio.run(scenario())


def test_session_window_tracks_runtime():
    async def scenario():
        clock = Clock()
        runtime, p = make_runtime(clock)
        window = FocusSessionWindow(runtime, clock=clock)
        runtime.start(
            build_plan(goal="excel assignment", minutes=25, allowed_apps=["excel"], now=T0)
        )
        assert window.isVisible() and window.goal.text() == "excel assignment"
        await feed(runtime, steps(EXCEL, 180, YOUTUBE, 240), clock)
        spans = window.bar.spans()
        assert [s[0] for s in spans] == [TimelineState.ON_GOAL, TimelineState.DRIFTING]
        assert abs(sum(s[2] for s in spans) - 418 / 1500) < 1e-9
        assert "on goal 3 min" in window.totals.text()
        assert "drifting 4 min" in window.totals.text()
        clock.now = T0 + timedelta(minutes=10)
        window._update_remaining()
        assert window.remaining.text() == "15 min left"
        window.grab()
        await runtime.end()
        assert not window.isVisible()
        window.dispose()
        await close(runtime, p)

    asyncio.run(scenario())


def test_summary_window_quiz_reflection_and_next_review():
    async def scenario():
        clock = Clock()
        runtime, p = make_runtime(clock)
        await p["coach"].add_review_items([
            review_item("vlookup", T0, "what does the 4th VLOOKUP argument do?"),
            review_item("index match", T0),
        ])
        spoken = []
        window = SessionSummaryWindow(runtime, speak=spoken.append, clock=clock)
        runtime.start(
            build_plan(goal="excel assignment", minutes=25, allowed_apps=["excel"], now=T0)
        )
        await feed(runtime, steps(EXCEL, 722), clock)
        summary = await runtime.end()
        await _idle(window)
        assert window.isVisible() and window.title.text() == "Session done: excel assignment"
        assert "On goal: 12 min" in window.card.text()
        first, second = window.items
        assert window.quiz.isVisible() and spoken == [first.question]
        assert not window.right_button.isEnabled()
        window.mark(True)  # can't mark before seeing the answer
        assert window.index == 0
        window.attempt.setText("exact match")
        window.reveal()
        assert first.answer in window.answer.text()
        window.mark(True)
        await _idle(window)
        assert window.index == 1 and spoken[-1] == second.question
        window.reveal()
        window.mark(False)
        await _idle(window)
        assert window.next_review.text() in {
            f"I'll ask you about {item.concept} again tomorrow." for item in (first, second)
        }
        assert await p["coach"].due_reviews(clock.now) == ()  # both rescheduled
        window.reflection.setText("  my   phone  ")
        done = []
        window.done.connect(done.append)
        window.finish()
        await drain(runtime)
        assert done[0].reflection == "my phone"
        saved = await p["store"].summaries()
        assert [(s.plan_id, s.reflection) for s in saved] == [(summary.plan_id, "my phone")]
        assert runtime.plan is None and not window.isVisible()
        window.dispose()
        await close(runtime, p)

    asyncio.run(scenario())


def test_review_window_mode_for_due_reviews():
    async def scenario():
        runtime, p = make_runtime(Clock())
        window = SessionSummaryWindow(runtime)
        item = review_item("index match", T0 - timedelta(days=1))
        runtime.review_requested.emit((item,))
        assert window.isVisible() and not window.card.isVisible()
        assert not window.reflection.isVisible() and window.items == [item]
        window.close()
        assert not window.isVisible()
        window.dispose()
        await close(runtime, p)

    asyncio.run(scenario())


def test_summary_without_reviews_hides_quiz():
    async def scenario():
        runtime, p = make_runtime(Clock())
        window = SessionSummaryWindow(runtime)
        runtime.start(build_plan(goal="essay", minutes=25, now=T0))
        await runtime.end()
        await _idle(window)
        assert window.isVisible() and not window.quiz.isVisible()
        window.close()
        assert runtime.plan is None
        window.dispose()
        await close(runtime, p)

    asyncio.run(scenario())


def test_next_review_text():
    now = datetime(2026, 10, 24, 12, 0).astimezone()
    assert next_review_text(now + timedelta(hours=1), now) == "later today"
    assert next_review_text(now + timedelta(days=1), now) == "tomorrow"
    tuesday = now + timedelta(days=3)
    assert next_review_text(tuesday, now) == f"on {tuesday:%A}"
    assert next_review_text(now + timedelta(days=20), now).startswith("on 13 ")
    assert next_review_text(now.astimezone(UTC), now) == "later today"
    assert minutes_text(90 * 60) == "1 h 30 min" and minutes_text(-5) == "0 min"


def test_history_window_lists_and_deletes(tmp_path):
    async def scenario():
        async with SqliteSessionStore(tmp_path / "f.sqlite3") as store:
            runtime, p = make_runtime(Clock(), store=store)
            runtime.start(build_plan(goal="stats homework", minutes=25, now=T0))
            summary = await runtime.end()
            answers = iter([False, True])
            window = FocusHistoryWindow(store, confirm=lambda _parent: next(answers))
            results = []
            window.operation_finished.connect(lambda name, ok: results.append((name, ok)))
            window.show()
            await _idle(window)
            assert window.table.rowCount() == 1
            assert window.table.item(0, 1).text() == summary.goal
            window.clear_all()  # declined
            await _idle(window)
            assert len(await store.summaries()) == 1
            window.clear_all()
            await _idle(window)
            assert await store.summaries() == () and window.table.rowCount() == 0
            assert results == [("Load history", True), ("Delete history", True)]
            window.close()
            p["store"] = None
            await close(runtime, p)

    asyncio.run(scenario())


def test_real_presenter_expiry_reaches_the_real_policy():
    async def scenario():
        fired = []
        presenter = FocusPresenter(schedule=lambda s, cb: fired.append(cb) or (lambda: None))
        runtime, p = make_runtime(Clock(), presenter=presenter)
        runtime.start(build_plan(goal="excel", minutes=25, now=T0))
        await drain(runtime)
        assert presenter.current.kind == InterventionKind.METACOGNITIVE
        fired[-1]()
        assert p["policy"].responses[-1][1] == InterventionResponse.IGNORED
        assert not presenter.bubble.isVisible()
        await close(runtime, p)
        presenter.bubble.close()

    asyncio.run(scenario())
