"""FocusRuntime routing with fakes of the sensing, policy and coach protocols."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

from curio.focus_contract import (
    FocusSignal,
    InterventionKind,
    InterventionResponse,
    ResumeNote,
    SignalKind,
    TrackJudgment,
)
from curio.focus_session import FocusRuntime, TimelineState, build_model_call, build_plan
from tests.test_focus_session_fakes import (
    T0,
    Clock,
    FakeClassifier,
    FakeCoach,
    FakePolicy,
    FakePresenter,
    FakeSource,
    FakeStore,
    FakeTracker,
    review_item,
    sample,
)


def _runtime(**overrides):
    clock = overrides.pop("clock", Clock())
    parts = {
        "source": FakeSource(),
        "classifier": FakeClassifier(),
        "tracker": FakeTracker(threshold=60),
        "policy": FakePolicy(),
        "presenter": FakePresenter(),
        "store": FakeStore(),
        "clock": clock,
    }
    parts.update(overrides)
    return FocusRuntime(**parts), parts


def _plan(minutes=25, **kw):
    return build_plan(
        goal="excel assignment", minutes=minutes, allowed_apps=["excel"], now=T0, **kw
    )


async def _feed(runtime, source, apps_every_10s, start=T0):
    """Emit one sample per 10 s; returns the time after the last one."""
    at = start
    previous = None
    for app in apps_every_10s:
        source.emit(sample(app, at, switch=app != previous))
        previous = app
        at += timedelta(seconds=10)
    await asyncio.sleep(0)
    await runtime._queue.join()
    return at


def test_drift_check_in_false_alarm_corrects_classifier_and_policy():
    async def scenario():
        runtime, p = _runtime()
        runtime.start(_plan())
        assert p["source"].started == 1 and p["tracker"].plan is runtime.plan
        await _feed(runtime, p["source"], ["excel"] * 3 + ["youtube"] * 8)
        presenter = p["presenter"]
        check_in = presenter.shown[-1]
        assert check_in.kind == InterventionKind.CHECK_IN
        assert runtime.drift_count == 1
        assert runtime.timeline.state == TimelineState.DRIFTING

        presenter.answer(InterventionResponse.FALSE_ALARM)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert p["policy"].responses == [(check_in, InterventionResponse.FALSE_ALARM)]
        (corrected, judgment), = p["classifier"].corrections
        assert corrected.app == "youtube" and judgment == TrackJudgment.ON_GOAL
        assert runtime.drift_count == 0
        assert runtime.timeline.totals()[TimelineState.DRIFTING] == 0
        # A second answer for the same card is ignored.
        presenter.answer(InterventionResponse.ACCEPTED)
        assert len(p["policy"].responses) == 1
        summary = await runtime.end()
        assert summary.false_alarms == 1 and summary.distractions == ()
        await runtime.aclose()

    asyncio.run(scenario())


def test_other_responses_go_only_to_policy():
    async def scenario():
        runtime, p = _runtime()
        runtime.start(_plan())
        await _feed(runtime, p["source"], ["excel"] + ["youtube"] * 8)
        p["presenter"].answer(InterventionResponse.ACCEPTED)
        await asyncio.sleep(0)
        assert p["policy"].responses[-1][1] == InterventionResponse.ACCEPTED
        assert p["classifier"].corrections == []
        assert runtime.drift_count == 1
        await runtime.aclose()

    asyncio.run(scenario())


def test_drift_passes_plan_resume_note_then_returns_with_resume():
    async def scenario():
        runtime, p = _runtime()
        runtime.start(_plan())
        await _feed(runtime, p["source"], ["excel"] * 2 + ["youtube"] * 8 + ["excel"] * 2)
        note = p["policy"].notes[0]
        assert note.source == "plan" and "excel assignment" in note.where
        kinds = [i.kind for i in p["presenter"].shown]
        assert kinds == [InterventionKind.CHECK_IN, InterventionKind.RESUME]
        assert SignalKind.RETURNED in {s.kind for s in p["presenter"].signals}
        assert runtime.timeline.state == TimelineState.ON_GOAL
        await runtime.aclose()

    asyncio.run(scenario())


def test_explicit_resume_context_wins_over_plan_note():
    async def scenario():
        step = ResumeNote(
            where="step three", next_action="add the row fields", source="walkthrough"
        )
        runtime, p = _runtime(resume_context=lambda: step)
        runtime.start(_plan())
        await _feed(runtime, p["source"], ["excel"] + ["youtube"] * 8)
        assert p["policy"].notes == [step]
        await runtime.aclose()

    asyncio.run(scenario())


def test_timeline_counts_sustained_drift_back_to_its_start():
    async def scenario():
        runtime, p = _runtime()
        runtime.start(_plan())
        # 30 s on goal, 10 s quick lookup, 30 s on goal, then 90 s of youtube.
        apps = ["excel"] * 3 + ["youtube"] + ["excel"] * 3 + ["youtube"] * 9 + ["excel"]
        await _feed(runtime, p["source"], apps)
        totals = runtime.timeline.totals()
        assert totals[TimelineState.DRIFTING] == 90
        assert totals[TimelineState.ON_GOAL] == 70
        assert runtime.drift_count == 1
        await runtime.aclose()

    asyncio.run(scenario())


def test_accepted_break_counts_as_break_until_break_over():
    async def scenario():
        runtime, p = _runtime()
        runtime.start(_plan())
        tracker = p["tracker"]
        tracker.queued.append(FocusSignal(kind=SignalKind.BREAK_DUE, at=T0))
        at = await _feed(runtime, p["source"], ["excel"])
        break_card = p["presenter"].shown[-1]
        assert break_card.kind == InterventionKind.BREAK_START
        p["clock"].now = at
        p["presenter"].answer(InterventionResponse.ACCEPTED)
        at = await _feed(runtime, p["source"], ["excel"] * 3, start=at)
        tracker.queued.append(FocusSignal(kind=SignalKind.BREAK_OVER, at=at))
        await _feed(runtime, p["source"], ["excel"] * 2, start=at)
        totals = runtime.timeline.totals()
        assert totals[TimelineState.BREAK] == 30
        assert p["presenter"].shown[-1].kind == InterventionKind.BREAK_END
        await runtime.aclose()

    asyncio.run(scenario())


def test_on_break_judgment_counts_as_break():
    async def scenario():
        runtime, p = _runtime(classifier=FakeClassifier(on_break=("spotify",)))
        runtime.start(_plan())
        await _feed(runtime, p["source"], ["spotify"] * 4 + ["excel"])
        assert runtime.timeline.totals()[TimelineState.BREAK] == 40
        await runtime.aclose()

    asyncio.run(scenario())


def test_end_saves_summary_and_ignores_open_cards():
    async def scenario():
        runtime, p = _runtime()
        ended = []
        runtime.session_ended.connect(ended.append)
        runtime.start(_plan())
        runtime.note_concepts(["VLOOKUP", "vlookup", "Absolute references"], "step 3: add fields")
        await _feed(runtime, p["source"], ["excel"] * 2 + ["youtube"] * 8)
        summary = await runtime.end()
        assert p["source"].stopped == 1 and p["source"].callbacks == []
        assert p["presenter"].cleared == 1
        assert p["policy"].responses[-1][1] == InterventionResponse.IGNORED
        assert p["store"].saved == [summary] and ended == [summary]
        assert summary.goal == "excel assignment" and summary.drift_count == 1
        assert summary.distractions == ("youtube",)
        assert summary.concepts_practised == ("vlookup", "absolute references")
        assert summary.interventions == 1
        assert summary.on_goal_seconds + summary.off_goal_seconds == 90
        assert await runtime.end() is None
        runtime.finish()
        assert runtime.plan is None
        await runtime.aclose()

    asyncio.run(scenario())


def test_session_ends_itself_after_its_duration():
    async def scenario():
        runtime, p = _runtime()
        ended = []
        runtime.session_ended.connect(ended.append)
        runtime.start(_plan(minutes=1))
        await _feed(runtime, p["source"], ["excel"] * 7)
        for _ in range(5):
            await asyncio.sleep(0)
        assert len(ended) == 1 and ended[0].on_goal_seconds == 60
        await runtime.aclose()

    asyncio.run(scenario())


def test_cancel_saves_nothing_and_aclose_is_idempotent():
    async def scenario():
        runtime, p = _runtime()
        runtime.start(_plan())
        await _feed(runtime, p["source"], ["excel"] * 2)
        await runtime.cancel()
        assert runtime.plan is None and p["store"].saved == []
        await runtime.aclose()
        await runtime.aclose()

    asyncio.run(scenario())


def test_classifier_failure_does_not_stop_the_pipeline():
    async def scenario():
        classifier = FakeClassifier()
        calls = {"n": 0}
        real = classifier.assess

        async def flaky(s, plan):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("model down")
            return await real(s, plan)

        classifier.assess = flaky
        runtime, p = _runtime(classifier=classifier)
        runtime.start(_plan())
        await _feed(runtime, p["source"], ["excel"] * 3)
        assert runtime.timeline.total_seconds == 20
        await runtime.aclose()

    asyncio.run(scenario())


def test_review_items_new_first_then_due_and_recorded():
    async def scenario():
        clock = Clock()
        due = [
            review_item("index match", T0 - timedelta(days=1)),
            review_item("later", T0 + timedelta(days=3)),
        ]
        coach = FakeCoach(due=due)
        fresh = [review_item("vlookup", T0 + timedelta(days=1))]
        generate = AsyncMock(return_value=fresh)
        runtime, _ = _runtime(coach=coach, generate_reviews=generate, clock=clock)
        runtime.start(_plan())
        runtime.note_concepts(["VLOOKUP"], "row fields")
        items = await runtime.review_items()
        generate.assert_awaited_once_with(("vlookup",), "row fields")
        assert [i.concept for i in items] == ["vlookup", "index match"]
        assert coach.added == fresh
        updated = await runtime.record_review(items[0], True)
        assert updated.due_at > items[0].due_at and coach.recorded == [(items[0], True)]
        await runtime.aclose()

    asyncio.run(scenario())


def test_review_items_without_coach_or_generator():
    async def scenario():
        runtime, _ = _runtime()
        runtime.start(_plan())
        assert await runtime.review_items() == ()
        await runtime.aclose()
        coach = FakeCoach()
        runtime, _ = _runtime(coach=coach)
        runtime.start(_plan(concepts=["pivot tables"]))
        assert await runtime.review_items() == ()
        await runtime.aclose()

    asyncio.run(scenario())


def test_suggestions_use_past_distractions():
    async def scenario():
        runtime, p = _runtime()
        runtime.start(_plan())
        await _feed(runtime, p["source"], ["excel"] + ["youtube"] * 8)
        await runtime.end()
        runtime.finish()
        plans = await runtime.suggest_if_then("stats homework")
        assert plans[0].cue_apps == ("youtube",)
        await runtime.aclose()

    asyncio.run(scenario())


def test_model_call_uses_dedicated_provider():
    async def scenario():
        provider = AsyncMock()
        provider.send.return_value = "ok"
        call = build_model_call(provider, "configured-model", max_tokens=99)
        assert await call("system text", "user text") == "ok"
        provider.send.assert_awaited_once_with(
            [{"role": "user", "content": "user text"}],
            system="system text",
            model="configured-model",
            max_tokens=99,
        )

    asyncio.run(scenario())


def test_cannot_start_twice():
    async def scenario():
        runtime, _ = _runtime()
        runtime.start(_plan())
        try:
            runtime.start(_plan())
        except RuntimeError:
            pass
        else:
            raise AssertionError("second start accepted")
        await runtime.aclose()

    asyncio.run(scenario())
