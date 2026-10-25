import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from curio.focus_contract import (
    HELP_LADDER,
    LearnerEvent,
    LearnerEventKind,
    TutoringMove,
)
from curio.learning_contract import SkillState
from curio.study_coach import (
    EvidenceBasedCoach,
    mastery_for,
    mastery_from_skill_model,
    teach_back_directive,
)
from curio.study_coach.coach import (
    AFTER_WORKED_EXAMPLE,
    FEEDBACK_AFTER_EXPLANATION,
    FEEDBACK_AFTER_FAILURE,
    FEEDBACK_AFTER_SUCCESS,
    INSTRUCTIONS,
    UNSOLICITED_PREFIX,
)

T0 = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
K = LearnerEventKind
M = TutoringMove


def event(kind, seconds=0.0, problem="p1", concepts=("vlookup",)):
    return LearnerEvent(
        kind=kind, problem_id=problem, concepts=concepts, at=T0 + timedelta(seconds=seconds)
    )


def moves(coach, events, mastery=None):
    return [coach.next_move(e, mastery).move for e in events]


def test_hints_first_ladder_climbs_one_rung_per_request():
    coach = EvidenceBasedCoach()
    # spaced out so hint abuse never triggers
    got = moves(coach, [event(K.HELP_REQUESTED, s) for s in (0, 60, 120, 180, 240)])
    assert got == [*HELP_LADDER, M.WORKED_EXAMPLE]


def test_failed_attempt_climbs_and_gives_informative_feedback():
    coach = EvidenceBasedCoach()
    first = coach.next_move(event(K.HELP_REQUESTED))
    assert first.move == M.GUIDING_QUESTION
    failed = coach.next_move(event(K.ATTEMPT_FAILED, 10))
    assert failed.move == M.FEEDBACK
    assert failed.instruction == (f"{FEEDBACK_AFTER_FAILURE} Then: {INSTRUCTIONS[M.HINT]}")
    assert coach.next_move(event(K.HELP_REQUESTED, 20)).move == M.PARTIAL_STEP


def test_problems_have_independent_ladders():
    coach = EvidenceBasedCoach()
    coach.next_move(event(K.HELP_REQUESTED, 0, "a"))
    coach.next_move(event(K.HELP_REQUESTED, 60, "a"))
    assert coach.next_move(event(K.HELP_REQUESTED, 120, "b")).move == M.GUIDING_QUESTION


@pytest.mark.parametrize("mastery", [None, 0.3, 0.5, 0.69, 0.7, 0.95, 1.0])
def test_no_worked_example_first_for_non_novice(mastery):
    coach = EvidenceBasedCoach()
    assert coach.next_move(event(K.HELP_REQUESTED), mastery).move != M.WORKED_EXAMPLE
    coach2 = EvidenceBasedCoach()
    assert coach2.next_move(event(K.ATTEMPT_FAILED), mastery).instruction.endswith(
        INSTRUCTIONS[M.GUIDING_QUESTION if mastery is None or mastery >= 0.7 else M.HINT]
    )


def test_fading_start_rung_by_mastery():
    assert EvidenceBasedCoach().next_move(event(K.HELP_REQUESTED), 0.1).move == M.WORKED_EXAMPLE
    assert EvidenceBasedCoach().next_move(event(K.HELP_REQUESTED), 0.5).move == M.HINT
    assert EvidenceBasedCoach().next_move(event(K.HELP_REQUESTED), 0.9).move == M.GUIDING_QUESTION


def test_high_mastery_caps_at_partial_step():
    coach = EvidenceBasedCoach()
    got = moves(coach, [event(K.HELP_REQUESTED, s) for s in (0, 60, 120, 180, 240)], 0.9)
    assert got == [M.GUIDING_QUESTION, M.HINT, M.PARTIAL_STEP, M.PARTIAL_STEP, M.PARTIAL_STEP]
    assert M.WORKED_EXAMPLE not in got


def test_invalid_mastery_is_ignored():
    for bad in (float("nan"), float("inf"), "x", True):
        assert EvidenceBasedCoach().next_move(event(K.HELP_REQUESTED), bad).move == (
            M.GUIDING_QUESTION
        )


def test_local_estimate_from_session_when_no_mastery():
    coach = EvidenceBasedCoach()
    assert coach.local_estimate(["vlookup"]) is None
    for i in range(3):
        coach.next_move(event(K.ATTEMPT_FAILED, i * 60, problem=f"f{i}"))
    assert coach.local_estimate(["VLOOKUP"]) == pytest.approx(1 / 5)
    # three failures on this concept this session: treated as a novice
    assert coach.next_move(event(K.HELP_REQUESTED, 600, problem="new")).move == M.WORKED_EXAMPLE
    # explicit mastery still wins over the local estimate
    assert coach.next_move(event(K.HELP_REQUESTED, 600, problem="n2"), 0.9).move == (
        M.GUIDING_QUESTION
    )


def test_local_estimate_ignores_other_concepts():
    coach = EvidenceBasedCoach()
    for i in range(3):
        coach.next_move(event(K.ATTEMPT_FAILED, i * 60, problem=f"f{i}"))
    fresh = event(K.HELP_REQUESTED, 600, problem="x", concepts=("pivot table",))
    assert coach.next_move(fresh).move == M.GUIDING_QUESTION


def test_hint_abuse_asks_to_try_first():
    coach = EvidenceBasedCoach()
    got = moves(coach, [event(K.HELP_REQUESTED, s) for s in (0, 5, 10)])
    assert got == [M.GUIDING_QUESTION, M.HINT, M.TRY_FIRST]
    directive = coach.next_move(event(K.HELP_REQUESTED, 12))
    assert directive.move == M.PARTIAL_STEP


def test_never_refuses_help_twice_in_a_row():
    coach = EvidenceBasedCoach(abuse_requests=2)
    got = moves(coach, [event(K.HELP_REQUESTED, s) for s in range(0, 12, 1)])
    for previous, current in zip(got, got[1:], strict=False):
        assert not (previous == M.TRY_FIRST and current == M.TRY_FIRST)
    assert M.TRY_FIRST in got
    # every refusal is followed by real help
    for i, move in enumerate(got[:-1]):
        if move == M.TRY_FIRST:
            assert got[i + 1] in HELP_LADDER


def test_slow_requests_or_attempts_between_are_not_abuse():
    slow = EvidenceBasedCoach()
    assert M.TRY_FIRST not in moves(slow, [event(K.HELP_REQUESTED, s) for s in (0, 31, 62)])
    tried = EvidenceBasedCoach()
    got = moves(
        tried,
        [
            event(K.HELP_REQUESTED, 0),
            event(K.HELP_REQUESTED, 5),
            event(K.ATTEMPT_FAILED, 8),
            event(K.HELP_REQUESTED, 10),
        ],
    )
    assert M.TRY_FIRST not in got
    explained = EvidenceBasedCoach()
    got = moves(
        explained,
        [
            event(K.HELP_REQUESTED, 0),
            event(K.HELP_REQUESTED, 5),
            event(K.EXPLANATION_GIVEN, 8),
            event(K.HELP_REQUESTED, 10),
        ],
    )
    assert got[2] == M.FEEDBACK and M.TRY_FIRST not in got


def test_stuck_waits_then_offers_guiding_question():
    coach = EvidenceBasedCoach()
    wait = coach.next_move(event(K.STUCK))
    assert wait.move == M.WAIT
    assert wait.wait_seconds == pytest.approx(45.0)
    assert wait.instruction == INSTRUCTIONS[M.WAIT]
    help_ = coach.next_move(event(K.STUCK, 45))
    assert help_.move == M.GUIDING_QUESTION
    assert help_.instruction == UNSOLICITED_PREFIX + INSTRUCTIONS[M.GUIDING_QUESTION]
    # unrequested help never climbs: the next stuck waits again
    assert coach.next_move(event(K.STUCK, 90)).move == M.WAIT


def test_stuck_after_help_repeats_current_rung_without_climbing():
    coach = EvidenceBasedCoach()
    coach.next_move(event(K.HELP_REQUESTED, 0))
    coach.next_move(event(K.HELP_REQUESTED, 60))  # HINT
    assert coach.next_move(event(K.STUCK, 100)).move == M.WAIT
    assert coach.next_move(event(K.STUCK, 150)).move == M.HINT


def test_wait_shorter_after_failures_longer_at_high_mastery():
    coach = EvidenceBasedCoach()
    coach.next_move(event(K.ATTEMPT_FAILED, 0))
    assert coach.next_move(event(K.STUCK, 5)).wait_seconds == pytest.approx(22.5)
    coach.next_move(event(K.ATTEMPT_FAILED, 10))
    coach.next_move(event(K.ATTEMPT_FAILED, 20))
    assert coach.next_move(event(K.STUCK, 25)).wait_seconds == pytest.approx(11.25)
    expert = EvidenceBasedCoach().next_move(event(K.STUCK), 0.9)
    assert expert.wait_seconds == pytest.approx(67.5)
    floor = EvidenceBasedCoach(base_wait_seconds=12, min_wait_seconds=10)
    floor.next_move(event(K.ATTEMPT_FAILED, 0))
    assert floor.next_move(event(K.STUCK, 5)).wait_seconds == 10


def test_stuck_after_try_first_gets_help_not_another_withhold():
    coach = EvidenceBasedCoach()
    moves(coach, [event(K.HELP_REQUESTED, s) for s in (0, 5, 10)])  # ends with TRY_FIRST
    assert coach.next_move(event(K.STUCK, 15)).move == M.HINT


def test_self_explain_after_solving_alone_or_with_a_hint():
    alone = EvidenceBasedCoach()
    directive = alone.next_move(event(K.ATTEMPT_SUCCEEDED))
    assert directive.move == M.SELF_EXPLAIN
    assert directive.instruction == INSTRUCTIONS[M.SELF_EXPLAIN]
    hinted = EvidenceBasedCoach()
    moves(hinted, [event(K.HELP_REQUESTED, 0), event(K.HELP_REQUESTED, 60)])
    assert hinted.next_move(event(K.ATTEMPT_SUCCEEDED, 90)).move == M.SELF_EXPLAIN


def test_no_self_explain_after_more_than_a_hint():
    coach = EvidenceBasedCoach()
    moves(coach, [event(K.HELP_REQUESTED, s) for s in (0, 60, 120)])  # PARTIAL_STEP
    directive = coach.next_move(event(K.ATTEMPT_SUCCEEDED, 150))
    assert directive.move == M.FEEDBACK
    assert directive.instruction == FEEDBACK_AFTER_SUCCESS


def test_no_self_explain_directly_after_worked_example_shown():
    coach = EvidenceBasedCoach()
    shown = coach.next_move(event(K.WORKED_EXAMPLE_SHOWN))
    assert shown.move == M.WAIT
    assert shown.instruction == AFTER_WORKED_EXAMPLE
    assert coach.next_move(event(K.ATTEMPT_SUCCEEDED, 30)).move == M.FEEDBACK


def test_no_self_explain_after_coach_gave_worked_example():
    coach = EvidenceBasedCoach()
    assert coach.next_move(event(K.HELP_REQUESTED), 0.1).move == M.WORKED_EXAMPLE
    assert coach.next_move(event(K.ATTEMPT_SUCCEEDED, 30), 0.1).move == M.FEEDBACK
    failed_into_example = EvidenceBasedCoach()
    failed_into_example.next_move(event(K.ATTEMPT_FAILED), 0.1)
    assert failed_into_example.next_move(event(K.ATTEMPT_SUCCEEDED, 30)).move == M.FEEDBACK


def test_self_explain_is_rate_limited_across_problems():
    coach = EvidenceBasedCoach(self_explain_cooldown=timedelta(minutes=5))
    assert coach.next_move(event(K.ATTEMPT_SUCCEEDED, 0, "a")).move == M.SELF_EXPLAIN
    assert coach.next_move(event(K.ATTEMPT_SUCCEEDED, 60, "b")).move == M.FEEDBACK
    assert coach.next_move(event(K.ATTEMPT_SUCCEEDED, 301, "c")).move == M.SELF_EXPLAIN


def test_success_resets_problem_and_explanation_feedback():
    coach = EvidenceBasedCoach()
    moves(coach, [event(K.HELP_REQUESTED, 0), event(K.HELP_REQUESTED, 60)])
    coach.next_move(event(K.ATTEMPT_SUCCEEDED, 90))
    assert coach.next_move(event(K.HELP_REQUESTED, 400)).move == M.GUIDING_QUESTION
    explanation = coach.next_move(event(K.EXPLANATION_GIVEN, 500))
    assert explanation.move == M.FEEDBACK
    assert explanation.instruction == FEEDBACK_AFTER_EXPLANATION


def test_every_directive_has_rationale_and_short_instruction():
    coach = EvidenceBasedCoach()
    for i, kind in enumerate(list(K) * 3):
        directive = coach.next_move(event(kind, i * 7))
        assert directive.rationale == "G"
        assert directive.instruction
        assert directive.instruction.count(". ") <= 3


def test_reset_forgets_state():
    coach = EvidenceBasedCoach()
    coach.next_move(event(K.HELP_REQUESTED, 0))
    coach.reset("p1")
    assert coach.next_move(event(K.HELP_REQUESTED, 60)).move == M.GUIDING_QUESTION
    for i in range(3):
        coach.next_move(event(K.ATTEMPT_FAILED, i, problem=f"f{i}"))
    coach.reset()
    assert coach.local_estimate(["vlookup"]) is None


def test_constructor_validates_thresholds():
    with pytest.raises(ValueError):
        EvidenceBasedCoach(novice_mastery=0.8, expert_mastery=0.7)
    with pytest.raises(ValueError):
        EvidenceBasedCoach(abuse_requests=1)


def test_teach_back_directive():
    directive = teach_back_directive("INDEX/MATCH")
    assert directive.move == M.SELF_EXPLAIN
    assert "index match" in directive.instruction
    assert directive.rationale == "G"


def test_mastery_helpers():
    states = (
        SkillState(concept="vlookup", mastery=0.8, attempts=3),
        SkillState(concept="pivot table", mastery=0.2, attempts=1),
    )
    assert mastery_for(states, ["VLOOKUP"]) == 0.8
    assert mastery_for(states, ["vlookup", "pivot table"]) == 0.2
    assert mastery_for(states, ["layers"]) is None

    class Model:
        async def snapshot(self):
            return states

    class Broken:
        async def snapshot(self):
            raise RuntimeError("db gone")

    assert asyncio.run(mastery_from_skill_model(Model(), ["pivot table"])) == 0.2
    assert asyncio.run(mastery_from_skill_model(Broken(), ["pivot table"])) is None
    assert asyncio.run(mastery_from_skill_model(None, ["pivot table"])) is None


def test_coach_delegates_reviews_to_scheduler():
    calls = []

    class Scheduler:
        async def due_reviews(self, now, limit=3):
            calls.append(("due", now, limit))
            return ()

        async def record_review(self, item, correct):
            calls.append(("record", item, correct))
            return item

        async def add_review_items(self, items):
            calls.append(("add", tuple(items)))

    coach = EvidenceBasedCoach(Scheduler())

    async def scenario():
        await coach.due_reviews(T0, 2)
        await coach.add_review_items([])
        await coach.record_review("item", True)

    asyncio.run(scenario())
    assert calls == [("due", T0, 2), ("add", ()), ("record", "item", True)]
