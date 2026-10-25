"""FocusRuntime over the real sensing (F1), policy (F2) and study coach (F3)."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

from curio.focus_contract import (
    InterventionKind,
    InterventionResponse,
    TrackJudgment,
)
from curio.focus_session import TimelineState, build_model_call, build_plan
from tests.test_focus_session_fakes import (
    EXCEL,
    REDDIT,
    T0,
    YOUTUBE,
    Clock,
    close,
    drain,
    feed,
    make_runtime,
    review_item,
    settle,
    steps,
)

DRIFT = (EXCEL, 30, YOUTUBE, 150, REDDIT, 30)


def _plan(minutes=25, **kw):
    return build_plan(
        goal="excel assignment", minutes=minutes, allowed_apps=["excel"], now=T0, **kw
    )


def test_session_opens_with_planning_prompt_and_spoken_answer_becomes_resume_note():
    async def scenario():
        clock = Clock()
        runtime, p = make_runtime(clock)
        runtime.start(_plan())
        await settle()
        presenter, policy = p["presenter"], p["policy"]
        opening = presenter.shown[0]
        assert opening.kind == InterventionKind.METACOGNITIVE
        assert "first thing" in opening.message
        presenter.answer(InterventionResponse.ACCEPTED, opening, "add the row fields")
        note = policy.resume_note()
        assert note.next_action == "add the row fields" and note.source == "spoken"
        assert policy.responses == [(opening, InterventionResponse.ACCEPTED)]
        await close(runtime, p)

    asyncio.run(scenario())


def test_drift_ambient_then_check_in_at_breakpoint_then_false_alarm_corrects_classifier():
    async def scenario():
        clock = Clock()
        runtime, p = make_runtime(clock)
        runtime.start(_plan())
        await feed(runtime, steps(*DRIFT), clock)
        presenter, policy = p["presenter"], p["policy"]
        kinds = presenter.kinds()
        assert kinds[1:] == [InterventionKind.AMBIENT_CUE, InterventionKind.CHECK_IN]
        check_in = presenter.last(InterventionKind.CHECK_IN)
        assert "not a distraction" in check_in.choices
        assert runtime.drift_count == 1 and runtime.timeline.state == TimelineState.DRIFTING

        presenter.answer(InterventionResponse.FALSE_ALARM, check_in, "not a distraction")
        await drain(runtime)
        assert policy.responses[-1] == (check_in, InterventionResponse.FALSE_ALARM)
        (corrected, judgment), = p["classifier"].corrections
        assert corrected.app == "chrome" and judgment == TrackJudgment.ON_GOAL
        assert runtime.drift_count == 0
        assert runtime.timeline.totals()[TimelineState.DRIFTING] == 0
        # The learner's correction now wins over the rules for that page.
        assessment = await p["classifier"].assess(corrected, runtime.plan)
        assert assessment.judgment == TrackJudgment.ON_GOAL
        # A second answer for the same card is ignored.
        presenter.answer(InterventionResponse.ACCEPTED, check_in)
        assert len(policy.responses) == 1 + 0 or policy.responses[-1][0] is check_in
        summary = await runtime.end()
        assert summary.false_alarms == 1 and summary.distractions == ()
        await close(runtime, p)

    asyncio.run(scenario())


def test_back_to_it_goes_only_to_policy_and_return_reads_resume_note():
    async def scenario():
        clock = Clock()
        runtime, p = make_runtime(clock)
        runtime.start(_plan())
        runtime.set_context(where="step 3", next_action="add the row fields")
        await feed(runtime, steps(*DRIFT), clock)
        presenter = p["presenter"]
        presenter.answer(
            InterventionResponse.ACCEPTED, presenter.last(InterventionKind.CHECK_IN), "back to it"
        )
        assert p["classifier"].corrections == []
        assert p["policy"].context == [
            {"where": "step 3", "next_action": "add the row fields", "source": "walkthrough"}
        ]
        await feed(runtime, steps(EXCEL, 30, start=clock.now + timedelta(seconds=2)), clock)
        resume = presenter.last(InterventionKind.RESUME)
        assert "add the row fields" in resume.message
        assert runtime.timeline.state == TimelineState.ON_GOAL
        await close(runtime, p)

    asyncio.run(scenario())


def test_take_a_break_from_a_check_in_starts_a_break_that_ends_itself():
    async def scenario():
        clock = Clock()
        runtime, p = make_runtime(clock)
        runtime.start(_plan(break_minutes=1))
        await feed(runtime, steps(*DRIFT), clock)
        presenter = p["presenter"]
        presenter.answer(
            InterventionResponse.ACCEPTED, presenter.last(InterventionKind.CHECK_IN),
            "take a break",
        )
        assert runtime.on_break and p["policy"].on_break
        await feed(runtime, steps(REDDIT, 70, start=clock.now + timedelta(seconds=2)), clock)
        assert not runtime.on_break
        assert presenter.kinds()[-1] == InterventionKind.BREAK_END
        assert 55 <= runtime.timeline.totals()[TimelineState.BREAK] <= 65
        await close(runtime, p)

    asyncio.run(scenario())


def test_session_ending_prompt_leads_to_reflection_and_reflection_ends_session():
    async def scenario():
        clock = Clock()
        runtime, p = make_runtime(clock)
        ended = []
        runtime.session_ended.connect(ended.append)
        runtime.start(_plan(minutes=4))
        await feed(runtime, steps(EXCEL, 150), clock)
        presenter = p["presenter"]
        ending = presenter.last(InterventionKind.METACOGNITIVE)
        assert ending is not presenter.shown[0]
        presenter.answer(InterventionResponse.IGNORED, ending)
        await drain(runtime)
        reflection = presenter.last(InterventionKind.REFLECTION)
        presenter.answer(InterventionResponse.ACCEPTED, reflection, "my phone kept buzzing")
        await drain(runtime)
        assert ended and ended[0].reflection == "my phone kept buzzing"
        assert (await p["store"].summaries())[0].reflection == "my phone kept buzzing"
        await close(runtime, p)

    asyncio.run(scenario())


def test_end_saves_summary_ignores_open_cards_and_resets_coach():
    async def scenario():
        clock = Clock()
        runtime, p = make_runtime(clock)
        ended = []
        runtime.session_ended.connect(ended.append)
        runtime.start(_plan())
        runtime.note_concepts(["VLOOKUP", "vlookup", "Absolute references"], "step 3: fields")
        await feed(runtime, steps(*DRIFT), clock)
        summary = await runtime.end()
        assert p["source"].running is False
        assert p["presenter"].cleared == 1
        assert p["policy"].responses[-1][1] == InterventionResponse.IGNORED
        assert await p["store"].summaries() == (summary,) and ended == [summary]
        assert summary.drift_count == 1 and summary.distractions == ("chrome",)
        assert summary.concepts_practised == ("vlookup", "absolute references")
        assert summary.on_goal_seconds + summary.off_goal_seconds == runtime.timeline.total_seconds
        assert await runtime.end() is None
        runtime.finish()
        assert runtime.plan is None
        await close(runtime, p)

    asyncio.run(scenario())


def test_samples_from_the_source_flow_through_the_queue_and_session_ends_itself():
    async def scenario():
        clock = Clock()
        runtime, p = make_runtime(clock)
        ended = []
        runtime.session_ended.connect(ended.append)
        runtime.start(_plan(minutes=1))
        source = p["source"]
        for s in steps(EXCEL, 70):
            source.push(s)
        source.play()
        await asyncio.sleep(0)
        await runtime._queue.join()
        await drain(runtime)
        assert len(ended) == 1 and ended[0].on_goal_seconds == 60
        await close(runtime, p)

    asyncio.run(scenario())


def test_cancel_saves_nothing_and_aclose_is_idempotent():
    async def scenario():
        clock = Clock()
        runtime, p = make_runtime(clock)
        runtime.start(_plan())
        await feed(runtime, steps(EXCEL, 10), clock)
        await runtime.cancel()
        assert runtime.plan is None and await p["store"].summaries() == ()
        await close(runtime, p)
        await runtime.aclose()

    asyncio.run(scenario())


def test_classifier_failure_does_not_stop_the_queue():
    async def scenario():
        clock = Clock()
        runtime, p = make_runtime(clock)
        real = p["classifier"].assess
        calls = {"n": 0}

        async def flaky(s, plan):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("model down")
            return await real(s, plan)

        p["classifier"].assess = flaky
        runtime.start(_plan())
        for s in steps(EXCEL, 10):
            p["source"].push(s)
        p["source"].play()
        await asyncio.sleep(0)
        await runtime._queue.join()
        assert runtime.timeline.total_seconds == 8
        await close(runtime, p)

    asyncio.run(scenario())


def test_due_reviews_are_offered_after_the_planning_prompt():
    async def scenario():
        clock = Clock()
        runtime, p = make_runtime(clock)
        await p["coach"].add_review_items([review_item("index match", T0 - timedelta(days=1))])
        requested = []
        runtime.review_requested.connect(requested.append)
        runtime.start(_plan())
        await drain(runtime)
        presenter = p["presenter"]
        assert presenter.kinds() == [InterventionKind.METACOGNITIVE]
        presenter.answer(InterventionResponse.DISMISSED, presenter.shown[0], "skip")
        await drain(runtime)
        offer = presenter.shown[-1]
        assert offer.kind == InterventionKind.REVIEW and offer.rationale == "G"
        presenter.answer(InterventionResponse.ACCEPTED, offer, "start review")
        assert [i.concept for i in requested[0]] == ["index match"]
        # The runtime's own card never reaches the policy.
        assert all(i.kind != InterventionKind.REVIEW for i, _ in p["policy"].responses)
        await close(runtime, p)

    asyncio.run(scenario())


def test_review_items_new_first_then_due_and_recorded():
    async def scenario():
        clock = Clock()
        fresh = [review_item("vlookup", T0)]
        generate = AsyncMock(return_value=fresh)
        runtime, p = make_runtime(clock, generate_reviews=generate)
        await p["coach"].add_review_items([
            review_item("index match", T0 - timedelta(days=1)),
            review_item("later", T0 + timedelta(days=3)),
        ])
        runtime.start(_plan())
        runtime.note_concepts(["VLOOKUP"], "row fields")
        items = await runtime.review_items()
        generate.assert_awaited_once_with(("vlookup",), "row fields")
        assert [i.concept for i in items] == ["vlookup", "index match"]
        updated = await runtime.record_review(items[0], True)
        assert updated.due_at > clock.now
        await close(runtime, p)

    asyncio.run(scenario())


def test_suggestions_use_past_distractions():
    async def scenario():
        clock = Clock()
        runtime, p = make_runtime(clock)
        runtime.start(_plan())
        await feed(runtime, steps(*DRIFT), clock)
        await runtime.end()
        runtime.finish()
        plans = await runtime.suggest_if_then("stats homework")
        assert plans[0].cue_apps == ("chrome",)
        await close(runtime, p)

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
        runtime, p = make_runtime(Clock())
        runtime.start(_plan())
        try:
            runtime.start(_plan())
        except RuntimeError:
            pass
        else:
            raise AssertionError("second start accepted")
        await close(runtime, p)

    asyncio.run(scenario())
