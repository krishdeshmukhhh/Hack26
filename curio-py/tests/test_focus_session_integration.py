"""Focus session inside the voice pipeline: card replies, directives, walkthrough events.

Uses the walkthrough tests' fake clients for CompanionManager and the real
F1-F3 pieces for the session.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from curio.focus_contract import InterventionResponse, TutoringMove
from curio.focus_session import build_plan
from curio.focus_session.integration import (
    DIRECTIVE_PREFIX,
    NO_TAGS,
    WITH_TAGS,
    FocusIntegration,
    is_help_request,
)
from curio.learning_contract import (
    AssistanceLevel,
    PathStep,
    SkillState,
    StepEvent,
    StepOutcome,
    TaskPath,
)
from curio.state import VoiceState
from tests.test_focus_session_fakes import T0, Clock, close, drain, make_runtime
from tests.test_walkthrough import TWO_STEPS, _ask, _manager, _settle

PLAN = dict(goal="excel assignment", minutes=25, allowed_apps=["excel"])


def _request_text(parts, index=-1) -> str:
    return parts["llm"].requests[index][-1]["content"][-1]["text"]


def _session(clock, *, learning=None, opened=None):
    runtime, p = make_runtime(clock)
    integration = FocusIntegration(
        runtime, p["presenter"], coach=p["coach"], learning=learning, clock=clock,
        open_start=(lambda goal, minutes: opened.append((goal, minutes)))
        if opened is not None else None,
    )
    return runtime, p, integration


def test_help_requests_climb_the_hint_ladder_without_breaking_walkthroughs(monkeypatch):
    manager, parts = _manager(["what do you want the table to summarise? [POINT:none]"] * 2
                              + TWO_STEPS, monkeypatch)

    async def run() -> None:
        clock = Clock()
        runtime, p, integration = _session(clock)
        manager.attach_focus(integration)
        runtime.start(build_plan(**PLAN, now=T0))
        await drain(runtime)

        _ask(manager, "how do i make a pivot table")
        await _settle(manager)
        first = _request_text(parts, 0)
        assert DIRECTIVE_PREFIX in first and "guiding question" in first and NO_TAGS in first
        assert "[STEP:1/N]" not in first  # no walkthrough for a guiding question

        clock.advance(60)
        _ask(manager, "just tell me the answer")
        await _settle(manager)
        second = _request_text(parts, 1)
        assert "one short hint" in second and NO_TAGS in second

        clock.advance(60)
        _ask(manager, "i'm still stuck, how do i make a pivot table")
        await _settle(manager)
        third = _request_text(parts, 2)
        # A partial step is a walkthrough: the STEP reminder comes back.
        assert "next single step" in third and WITH_TAGS in third and "[STEP:1/N]" in third
        assert manager._state == VoiceState.GUIDING

        parts["clicks"].clicked.emit()  # continuation: walkthrough flow untouched
        await _settle(manager)
        continuation = _request_text(parts, 3)
        assert continuation.startswith("i did step 1. what's next?")
        assert DIRECTIVE_PREFIX not in continuation
        # History never stores the directive.
        assert all(DIRECTIVE_PREFIX not in user for user, _ in manager._history._turns)
        await close(runtime, p)

    asyncio.run(run())


def test_no_directive_outside_a_session_or_on_a_break(monkeypatch):
    manager, parts = _manager(["sure. [POINT:none]"] * 2, monkeypatch)

    async def run() -> None:
        clock = Clock()
        runtime, p, integration = _session(clock)
        manager.attach_focus(integration)
        _ask(manager, "what's the formula for an average")
        await _settle(manager)
        assert DIRECTIVE_PREFIX not in _request_text(parts, 0)
        runtime.start(build_plan(**PLAN, now=T0))
        runtime.take_break()
        _ask(manager, "what's the formula for an average")
        await _settle(manager)
        assert DIRECTIVE_PREFIX not in _request_text(parts, 1)
        await close(runtime, p)

    asyncio.run(run())


def test_spoken_card_reply_start_and_end_are_consumed(monkeypatch):
    manager, parts = _manager([], monkeypatch)
    finals = []
    manager.final_transcript.connect(finals.append)

    async def run() -> None:
        clock = Clock()
        opened = []
        runtime, p, integration = _session(clock, opened=opened)
        manager.attach_focus(integration)
        _ask(manager, "Curio, I'm doing my Excel assignment for 25 minutes")
        assert opened == [("my Excel assignment", 25)]

        runtime.start(build_plan(**PLAN, now=T0))
        await drain(runtime)
        presenter = p["presenter"]
        presenter.current = presenter.shown[0]  # the planning card is open

        def handle_spoken(text):
            presenter.answer(InterventionResponse.ACCEPTED, presenter.current, text)
            presenter.current = None
            return True

        presenter.handle_spoken = handle_spoken
        _ask(manager, "first I'll add the row fields")
        assert p["policy"].resume_note().next_action == "first I'll add the row fields"

        _ask(manager, "end the session")
        await drain(runtime)
        assert not runtime.active
        assert parts["llm"].requests == []  # none of these reached the model
        assert manager._state == VoiceState.IDLE
        assert finals[-1] == "end the session"
        await close(runtime, p)

    asyncio.run(run())


def test_help_question_is_not_swallowed_by_an_open_card(monkeypatch):
    manager, parts = _manager(["here's a hint. [POINT:none]"], monkeypatch)

    async def run() -> None:
        clock = Clock()
        runtime, p, integration = _session(clock)
        manager.attach_focus(integration)
        runtime.start(build_plan(**PLAN, now=T0))
        await drain(runtime)
        p["presenter"].current = p["presenter"].shown[0]
        p["presenter"].handle_spoken = lambda text: True
        _ask(manager, "how do i add a slicer")
        await _settle(manager)
        assert len(parts["llm"].requests) == 1
        await close(runtime, p)

    asyncio.run(run())


def test_say_only_speaks_when_idle(monkeypatch):
    manager, parts = _manager([], monkeypatch)

    async def run() -> None:
        assert manager.say("still on the assignment?")
        await _settle(manager)
        assert parts["tts"].spoken == ["still on the assignment?"]
        assert manager._state == VoiceState.IDLE
        manager._set_state(VoiceState.PROCESSING)
        assert not manager.say("not now")
        assert parts["tts"].spoken == ["still on the assignment?"]

    asyncio.run(run())


def test_skill_model_mastery_reaches_the_coach_through_learning_services():
    async def run() -> None:
        clock = Clock()

        class SkillModel:
            async def snapshot(self):
                return (SkillState(concept="pivot tables", mastery=0.1, attempts=4),)

        class TaskMap:
            async def find(self, app, task):
                return TaskPath(app=app, task=task, steps=(
                    PathStep(index=1, instruction="insert", concepts=("pivot tables",)),
                ))

        learning = SimpleNamespace(skill_model=SkillModel(), task_map=TaskMap())
        runtime, p, integration = _session(clock, learning=learning)
        runtime.start(build_plan(**PLAN, now=T0))
        directive = await integration.directive_for(
            "how do i make a pivot table", app="excel", task="make a pivot table"
        )
        # A novice on this concept starts with a worked example, as a walkthrough.
        assert directive.move == TutoringMove.WORKED_EXAMPLE and directive.allow_walkthrough
        await close(runtime, p)

    asyncio.run(run())


def test_walkthrough_steps_feed_resume_context_and_coach_events():
    async def run() -> None:
        clock = Clock()
        runtime, p, integration = _session(clock)
        runtime.start(build_plan(**PLAN, now=T0))
        calls = []
        real = p["coach"].next_move
        p["coach"].next_move = lambda event, mastery=None: calls.append(event) or real(
            event, mastery
        )
        await integration.directive_for("how do i sort by date", app="excel", task="sort by date")
        integration.walkthrough_step(2, "click sort a to z", ("sorting",))
        assert p["policy"].context[-1]["where"] == "step 2"
        assert runtime.summary().concepts_practised == ("sorting",)

        for outcome in (StepOutcome.RETRIED, StepOutcome.SUCCEEDED, StepOutcome.ABANDONED):
            integration.step_settled(StepEvent(
                walkthrough_id="w", app="excel", task="sort by date", step_index=2,
                instruction="click sort", assistance=AssistanceLevel.POINTED, outcome=outcome,
                occurred_at=clock.now,
            ))
        kinds = [e.kind.value for e in calls]
        assert kinds == ["help_requested", "attempt_failed", "attempt_succeeded"]
        assert len({e.problem_id for e in calls}) == 1  # same problem as the help turn
        integration.walkthrough_finished("sort by date", completed=True)
        assert integration.problems.current is None
        await close(runtime, p)

    asyncio.run(run())


def test_is_help_request():
    for text in ("how do i make a chart", "i'm stuck", "what's the formula for this",
                 "just tell me the answer", "give me a hint"):
        assert is_help_request(text), text
    for text in ("back to it", "thanks", "take a break"):
        assert not is_help_request(text), text
