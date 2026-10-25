"""Rule-based tutoring moves: hint ladder, hint-abuse detection, fading, waiting,
self-explanation and informative feedback.

Every rule comes from section G of docs/focus-learning-research.md, so every
directive carries rationale "G". No model is involved: ``next_move`` is a pure
function of the learner events seen so far, the optional skill-model mastery
and the timestamps on the events, which keeps it deterministic in tests.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from curio.focus_contract import (
    HELP_LADDER,
    LearnerEvent,
    LearnerEventKind,
    ReviewItem,
    TutorDirective,
    TutoringMove,
)
from curio.learning_contract import SkillModel, SkillState, concept_key
from curio.study_coach.scheduler import ReviewScheduler, SqliteReviewScheduler

RATIONALE = "G"

NOVICE_MASTERY = 0.3  # below this, start at a worked example
EXPERT_MASTERY = 0.7  # at or above this, start at a question and cap at a partial step
LOCAL_ESTIMATE_MIN_OUTCOMES = 3  # session outcomes needed before trusting the local estimate
_MAX_PROBLEMS = 200

INSTRUCTIONS: dict[TutoringMove, str] = {
    TutoringMove.WAIT: (
        "Stay quiet and let the learner keep working. "
        "Offer help only if they ask or are still stuck after the wait."
    ),
    TutoringMove.GUIDING_QUESTION: (
        "Ask one short guiding question that points at the next step. "
        "Don't give a hint or the answer yet."
    ),
    TutoringMove.HINT: (
        "Give one short hint toward the next step, not the answer. Then let the learner try."
    ),
    TutoringMove.PARTIAL_STEP: (
        "Show only the next single step and why it comes next, then let the learner do the rest. "
        "Don't give the final answer."
    ),
    TutoringMove.WORKED_EXAMPLE: (
        "Walk through a worked example step by step, briefly saying why each step is done. "
        "Don't ask the learner to explain the example back."
    ),
    TutoringMove.SELF_EXPLAIN: (
        "Ask one short question: why did that work? Let the learner answer in their own words; "
        "don't explain it for them."
    ),
    TutoringMove.TRY_FIRST: (
        "Before more help, kindly ask what they've tried so far or what they think the next "
        "step is. Say you'll help right after they answer."
    ),
}

FEEDBACK_AFTER_FAILURE = (
    "Say specifically what was right and what went wrong in their attempt, without bare praise."
)
FEEDBACK_AFTER_SUCCESS = (
    "Say specifically what they got right and why it worked, then name the next step. "
    "No bare 'good job'."
)
FEEDBACK_AFTER_EXPLANATION = (
    "Say which parts of their explanation are right, correct anything that isn't, "
    "then name the next step."
)
AFTER_WORKED_EXAMPLE = (
    "They just saw a worked example. Let them try a similar step on their own; "
    "don't ask them to explain the example."
)
UNSOLICITED_PREFIX = "They seem stuck and haven't asked: offer this gently, don't push. "


@dataclass
class _Problem:
    rung: int | None = None  # index into HELP_LADDER of the last help given
    help_times: list[datetime] = field(default_factory=list)  # requests since the last attempt
    failures: int = 0
    worked_example_seen: bool = False
    last_move: TutoringMove | None = None


@dataclass
class _ConceptRecord:
    successes: float = 0.0
    outcomes: int = 0


def _clean_mastery(mastery: float | None) -> float | None:
    if mastery is None or isinstance(mastery, bool):
        return None
    try:
        value = float(mastery)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return min(1.0, max(0.0, value))


class EvidenceBasedCoach:
    """Implements ``focus_contract.StudyCoach``.

    ``next_move`` keeps per-problem state keyed by ``LearnerEvent.problem_id``.
    Review methods delegate to ``scheduler`` (an in-memory SQLite scheduler
    when none is given, so nothing persists unless integration passes one).
    """

    def __init__(
        self,
        scheduler: ReviewScheduler | None = None,
        *,
        novice_mastery: float = NOVICE_MASTERY,
        expert_mastery: float = EXPERT_MASTERY,
        base_wait_seconds: float = 45.0,
        min_wait_seconds: float = 10.0,
        abuse_requests: int = 3,
        abuse_window: timedelta = timedelta(seconds=30),
        self_explain_cooldown: timedelta = timedelta(minutes=5),
    ) -> None:
        if not 0 <= novice_mastery < expert_mastery <= 1:
            raise ValueError("Mastery thresholds must satisfy 0 <= novice < expert <= 1")
        if abuse_requests < 2:
            raise ValueError("Hint abuse needs at least two requests")
        self._scheduler = scheduler if scheduler is not None else SqliteReviewScheduler(":memory:")
        self._novice = novice_mastery
        self._expert = expert_mastery
        self._base_wait = base_wait_seconds
        self._min_wait = min_wait_seconds
        self._abuse_requests = abuse_requests
        self._abuse_window = abuse_window
        self._self_explain_cooldown = self_explain_cooldown
        self._problems: OrderedDict[str, _Problem] = OrderedDict()
        self._concepts: dict[str, _ConceptRecord] = {}
        self._last_self_explain: datetime | None = None

    # --- StudyCoach -----------------------------------------------------------

    def next_move(self, event: LearnerEvent, mastery: float | None = None) -> TutorDirective:
        problem = self._problem(event.problem_id)
        level = _clean_mastery(mastery)
        if level is None:
            level = self.local_estimate(event.concepts)
        kind = event.kind
        if kind == LearnerEventKind.HELP_REQUESTED:
            directive = self._on_help(problem, event, level)
        elif kind == LearnerEventKind.ATTEMPT_FAILED:
            directive = self._on_failure(problem, event, level)
        elif kind == LearnerEventKind.ATTEMPT_SUCCEEDED:
            directive = self._on_success(problem, event)
        elif kind == LearnerEventKind.STUCK:
            directive = self._on_stuck(problem, level)
        elif kind == LearnerEventKind.WORKED_EXAMPLE_SHOWN:
            problem.worked_example_seen = True
            problem.rung = len(HELP_LADDER) - 1
            directive = self._directive(
                TutoringMove.WAIT,
                AFTER_WORKED_EXAMPLE,
                wait_seconds=self._wait_seconds(problem, level),
            )
        else:  # EXPLANATION_GIVEN counts as an attempt
            problem.help_times.clear()
            directive = self._directive(TutoringMove.FEEDBACK, FEEDBACK_AFTER_EXPLANATION)
        problem.last_move = directive.move
        if directive.move == TutoringMove.WORKED_EXAMPLE:
            problem.worked_example_seen = True
        return directive

    async def due_reviews(self, now: datetime, limit: int = 3) -> tuple[ReviewItem, ...]:
        return await self._scheduler.due_reviews(now, limit)

    async def record_review(self, item: ReviewItem, correct: bool) -> ReviewItem:
        return await self._scheduler.record_review(item, correct)

    async def add_review_items(self, items: Sequence[ReviewItem]) -> None:
        await self._scheduler.add_review_items(items)

    # --- Extras for integration -------------------------------------------------

    def reset(self, problem_id: str | None = None) -> None:
        """Forget one problem, or all per-session state when ``problem_id`` is None."""
        if problem_id is None:
            self._problems.clear()
            self._concepts.clear()
            self._last_self_explain = None
        else:
            self._problems.pop(problem_id, None)

    def local_estimate(self, concepts: Sequence[str]) -> float | None:
        """Mastery estimated from this session's attempts, or None with too little evidence."""
        successes = 0.0
        outcomes = 0
        for concept in {concept_key(c) for c in concepts}:
            record = self._concepts.get(concept)
            if record is not None:
                successes += record.successes
                outcomes += record.outcomes
        if outcomes < LOCAL_ESTIMATE_MIN_OUTCOMES:
            return None
        return (successes + 1) / (outcomes + 2)  # Laplace-smoothed success rate

    # --- Rules ------------------------------------------------------------------

    def _on_help(
        self, problem: _Problem, event: LearnerEvent, level: float | None
    ) -> TutorDirective:
        cutoff = event.at - self._abuse_window
        problem.help_times = [t for t in problem.help_times if t >= cutoff]
        problem.help_times.append(event.at)
        # Hint abuse: rapid requests with no attempt between them. Never refuse
        # twice in a row, since not getting help when needed hurts too.
        if (
            len(problem.help_times) >= self._abuse_requests
            and problem.last_move != TutoringMove.TRY_FIRST
        ):
            problem.help_times.clear()
            return self._directive(TutoringMove.TRY_FIRST, INSTRUCTIONS[TutoringMove.TRY_FIRST])
        self._climb(problem, level)
        return self._rung_directive(problem)

    def _on_failure(
        self, problem: _Problem, event: LearnerEvent, level: float | None
    ) -> TutorDirective:
        problem.help_times.clear()
        problem.failures += 1
        self._observe(event.concepts, 0.0)
        self._climb(problem, level)
        move = HELP_LADDER[problem.rung]
        if move == TutoringMove.WORKED_EXAMPLE:
            problem.worked_example_seen = True
        return self._directive(
            TutoringMove.FEEDBACK,
            f"{FEEDBACK_AFTER_FAILURE} Then: {INSTRUCTIONS[move]}",
        )

    def _on_success(self, problem: _Problem, event: LearnerEvent) -> TutorDirective:
        hint_index = HELP_LADDER.index(TutoringMove.HINT)
        mostly_alone = problem.rung is None or problem.rung <= hint_index
        self._observe(event.concepts, 1.0 if mostly_alone else 0.5)
        cooled_down = (
            self._last_self_explain is None
            or event.at - self._last_self_explain >= self._self_explain_cooldown
        )
        # Never prompt self-explanation after a worked example (Barbieri et al.:
        # negative effect); rate-limited so it isn't on every success.
        self._problems.pop(event.problem_id, None)
        if mostly_alone and not problem.worked_example_seen and cooled_down:
            self._last_self_explain = event.at
            return self._directive(
                TutoringMove.SELF_EXPLAIN, INSTRUCTIONS[TutoringMove.SELF_EXPLAIN]
            )
        return self._directive(TutoringMove.FEEDBACK, FEEDBACK_AFTER_SUCCESS)

    def _on_stuck(self, problem: _Problem, level: float | None) -> TutorDirective:
        if problem.last_move not in (TutoringMove.WAIT, TutoringMove.TRY_FIRST):
            return self._directive(
                TutoringMove.WAIT,
                INSTRUCTIONS[TutoringMove.WAIT],
                wait_seconds=self._wait_seconds(problem, level),
            )
        # Still stuck after waiting: offer the least help, or repeat the current
        # rung. Unrequested help never climbs the ladder.
        if problem.rung is None:
            problem.rung = 0
        move = HELP_LADDER[problem.rung]
        return self._directive(move, UNSOLICITED_PREFIX + INSTRUCTIONS[move])

    # --- Helpers ------------------------------------------------------------------

    def _climb(self, problem: _Problem, level: float | None) -> None:
        start, cap = self._start_and_cap(level)
        problem.rung = start if problem.rung is None else problem.rung + 1
        problem.rung = min(problem.rung, cap)

    def _start_and_cap(self, level: float | None) -> tuple[int, int]:
        top = len(HELP_LADDER) - 1
        if level is None:
            return 0, top
        if level < self._novice:
            return top, top  # novices start with a worked example
        if level < self._expert:
            return HELP_LADDER.index(TutoringMove.HINT), top
        return 0, HELP_LADDER.index(TutoringMove.PARTIAL_STEP)

    def _rung_directive(self, problem: _Problem) -> TutorDirective:
        move = HELP_LADDER[problem.rung]
        return self._directive(move, INSTRUCTIONS[move])

    def _wait_seconds(self, problem: _Problem, level: float | None) -> float:
        seconds = self._base_wait * 0.5 ** min(problem.failures, 2)
        if level is not None and level >= self._expert:
            seconds *= 1.5
        return max(self._min_wait, seconds)

    def _observe(self, concepts: Sequence[str], success: float) -> None:
        for concept in {concept_key(c) for c in concepts}:
            if concept:
                record = self._concepts.setdefault(concept, _ConceptRecord())
                record.successes += success
                record.outcomes += 1

    def _problem(self, problem_id: str) -> _Problem:
        problem = self._problems.get(problem_id)
        if problem is None:
            problem = self._problems[problem_id] = _Problem()
            while len(self._problems) > _MAX_PROBLEMS:
                self._problems.popitem(last=False)
        else:
            self._problems.move_to_end(problem_id)
        return problem

    @staticmethod
    def _directive(
        move: TutoringMove, instruction: str, wait_seconds: float = 0.0
    ) -> TutorDirective:
        return TutorDirective(
            move=move, instruction=instruction, wait_seconds=wait_seconds, rationale=RATIONALE
        )


def teach_back_directive(concept: str) -> TutorDirective:
    """Optional "explain it to the fox" mode. Evidence is weak to moderate; no claims."""
    name = concept_key(concept) or "this"
    return TutorDirective(
        move=TutoringMove.SELF_EXPLAIN,
        instruction=(
            f"Play a curious beginner who doesn't know {name}. Ask the learner to teach it to "
            "you, then ask one naive follow-up question at a time. Don't lecture."
        ),
        rationale=RATIONALE,
    )


def mastery_for(states: Sequence[SkillState], concepts: Sequence[str]) -> float | None:
    """Lowest known mastery among ``concepts``, or None when none are known."""
    wanted = {concept_key(c) for c in concepts}
    known = [s.mastery for s in states if concept_key(s.concept) in wanted]
    return min(known) if known else None


async def mastery_from_skill_model(
    model: SkillModel | None, concepts: Sequence[str]
) -> float | None:
    """``mastery_for`` over a SkillModel snapshot; None when there is no model or it fails."""
    if model is None or not concepts:
        return None
    try:
        states = await model.snapshot()
    except Exception:
        return None
    return mastery_for(states, concepts)
