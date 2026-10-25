"""What the voice pipeline asks of a focus/study session.

``CompanionManager`` calls into one ``FocusIntegration``:

- ``handle_transcript`` first, for replies to an open card ("back to it"),
  "I'm doing X for N minutes", "end the session" and "take a break";
- ``directive_for`` on a learner-initiated help turn, to get the study
  coach's TutorDirective for that request only (section G);
- ``walkthrough_step`` / ``step_settled`` as walkthrough steps are given and
  finish, so the coach and the resume notes follow the learner.

Directives never touch walkthrough continuations ("i did step k. what's
next?"): those keep the STEP flow exactly as it is. On a help turn, a
partial step or worked example *is* a walkthrough, so the walkthrough
reminder stays; every other move (guiding question, hint, try first) asks
for spoken help only, without STEP or POINT tags, so a hint never turns
into "click here".
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from curio.focus_contract import (
    LearnerEvent,
    LearnerEventKind,
    StudyCoach,
    TutoringMove,
)
from curio.focus_session.planning import parse_start_request
from curio.learning_contract import StepEvent, StepOutcome, concept_key
from curio.prompts import is_howto_question

logger = logging.getLogger(__name__)

CONTEXT_TIMEOUT_SECONDS = 1.0
PROBLEM_WINDOW = timedelta(minutes=10)
DIRECTIVE_PREFIX = "TUTOR DIRECTIVE:"
WALKTHROUGH_MOVES = frozenset({TutoringMove.PARTIAL_STEP, TutoringMove.WORKED_EXAMPLE})
NO_TAGS = "This turn, don't start a walkthrough: leave out the [STEP] tag and use [POINT:none]."
WITH_TAGS = "If this is an on-screen task, give it as walkthrough steps with the usual tags."

_STUCK_RE = re.compile(
    r"\b(i'?m stuck|i am stuck|stuck on|i don'?t get (it|this)|i can'?t figure|"
    r"confused|lost here|what am i doing wrong|it'?s not working|doesn'?t work)\b",
    re.I,
)
_ANSWER_SEEKING_RE = re.compile(
    r"\b(answer|solve|solution|formula|hint|help me|what should i|which function|"
    r"just tell me|show me|explain)\b",
    re.I,
)
# Asking again about the same thing: keeps the help ladder on one problem.
_FOLLOW_UP_RE = re.compile(
    r"\b(another hint|more help|still (stuck|confused|don'?t)|just tell me|give me the answer|"
    r"what'?s the answer|i still|again|that didn'?t (help|work)|next step)\b",
    re.I,
)
_END_RE = re.compile(
    r"^(?:hey\s+)?(?:curio[,\s]+)?(?:let'?s\s+)?(?:end|stop|finish)\s+(?:the|my|this)?\s*"
    r"(?:focus\s+|study\s+)?session\b",
    re.I,
)
_BREAK_RE = re.compile(
    r"^(?:hey\s+)?(?:curio[,\s]+)?(?:i'?m\s+)?(?:going to\s+|gonna\s+)?"
    r"(?:take|taking)\s+a\s+break\b",
    re.I,
)


def is_help_request(text: str) -> bool:
    """How-to questions, "I'm stuck", and asking for an answer or a hint."""
    return bool(
        is_howto_question(text) or _STUCK_RE.search(text) or _ANSWER_SEEKING_RE.search(text)
    )


@dataclass(frozen=True)
class TurnDirective:
    move: TutoringMove
    line: str  # appended to this request only
    allow_walkthrough: bool  # keep the walkthrough reminder for how-to questions


class ProblemTracker:
    """Groups help requests about the same problem so the hint ladder can climb."""

    def __init__(self, clock: Callable[[], datetime]) -> None:
        self._clock = clock
        self.current: str | None = None
        self._task = ""
        self._last: datetime | None = None
        self._by_task: dict[str, str] = {}

    def for_request(self, text: str, task: str) -> str:
        now = self._clock()
        recent = self._last is not None and now - self._last < PROBLEM_WINDOW
        same = bool(_FOLLOW_UP_RE.search(text)) or (bool(task) and task == self._task)
        if self.current is None or not recent or not same:
            self.current = f"help:{task or uuid4().hex[:8]}"
            self._task = task
        self._last = now
        if task:
            # A walkthrough started by this turn records its steps under ``task``.
            self._by_task[task] = self.current
        return self.current

    def for_walkthrough(self, task: str) -> str:
        return self._by_task.get(task, f"walkthrough:{task}")

    def solved(self, problem_id: str) -> None:
        if problem_id == self.current:
            self.current = None

    def reset(self) -> None:
        self.current, self._task, self._last = None, "", None
        self._by_task.clear()


class FocusIntegration:
    def __init__(
        self,
        runtime,
        presenter,
        *,
        coach: StudyCoach | None = None,
        learning=None,  # LearningServices: skill model mastery and task-map concepts
        open_start: Callable[[str, int], None] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.runtime = runtime
        self.presenter = presenter
        self.coach = coach
        self.learning = learning
        self._open_start = open_start
        self._clock = clock
        self.problems = ProblemTracker(clock)
        runtime.session_ended.connect(lambda _summary: self.problems.reset())

    @property
    def studying(self) -> bool:
        return bool(self.runtime.active) and not self.runtime.on_break

    # --- transcripts ---------------------------------------------------------------

    def handle_transcript(self, text: str) -> bool:
        """True if the session consumed this utterance (no assistant turn)."""
        text = text.strip()
        if not text:
            return False
        open_card = self.presenter.current is not None and not is_help_request(text)
        if open_card and self.presenter.handle_spoken(text):
            return True
        if self.runtime.active:
            if _END_RE.search(text):
                self.runtime.request_end()
                return True
            if _BREAK_RE.search(text):
                self.runtime.take_break()
                return True
            return False
        request = parse_start_request(text)
        if request is not None and self._open_start is not None:
            self._open_start(request.goal, request.minutes)
            return True
        return False

    # --- tutoring directives -------------------------------------------------------

    async def directive_for(self, text: str, *, app: str, task: str) -> TurnDirective | None:
        """The coach's directive for a learner-initiated help turn, or None."""
        if self.coach is None or not self.studying or not is_help_request(text):
            return None
        problem_id = self.problems.for_request(text, task)
        concepts = await self._concepts(app, task)
        mastery = await self._mastery(concepts)
        try:
            directive = self.coach.next_move(
                LearnerEvent(
                    kind=LearnerEventKind.HELP_REQUESTED,
                    concepts=concepts,
                    problem_id=problem_id,
                    at=self._clock(),
                ),
                mastery,
            )
        except Exception:
            logger.exception("study coach failed; answering without a directive")
            return None
        if directive.move == TutoringMove.WAIT or not directive.instruction:
            return None
        allow = directive.move in WALKTHROUGH_MOVES
        line = f"{DIRECTIVE_PREFIX} {directive.instruction} {WITH_TAGS if allow else NO_TAGS}"
        logger.info("focus: tutor directive %s for %s", directive.move.value, problem_id)
        return TurnDirective(move=directive.move, line=line, allow_walkthrough=allow)

    async def _concepts(self, app: str, task: str) -> tuple[str, ...]:
        concepts: dict[str, None] = {}
        task_map = getattr(self.learning, "task_map", None)
        if task_map is not None and task:
            try:
                path = await asyncio.wait_for(task_map.find(app, task), CONTEXT_TIMEOUT_SECONDS)
            except Exception:
                path = None
            for step in getattr(path, "steps", ()):
                concepts.update(dict.fromkeys(step.concepts))
        plan = self.runtime.plan
        if not concepts and plan is not None:
            concepts.update(dict.fromkeys(plan.concepts))
        return tuple(c for c in concepts if concept_key(c))

    async def _mastery(self, concepts: tuple[str, ...]) -> float | None:
        skill_model = getattr(self.learning, "skill_model", None)
        if skill_model is None or not concepts:
            return None
        from curio.study_coach import mastery_from_skill_model

        try:
            return await asyncio.wait_for(
                mastery_from_skill_model(skill_model, concepts), CONTEXT_TIMEOUT_SECONDS
            )
        except Exception:
            return None

    # --- walkthrough progress --------------------------------------------------------

    def walkthrough_step(self, index: int, instruction: str, concepts=()) -> None:
        """A step was just given: it's where the learner is, for resume notes."""
        if not self.runtime.active:
            return
        self.runtime.set_context(
            where=f"step {index}", next_action=instruction[:160], source="walkthrough"
        )
        self.runtime.note_concepts(concepts, instruction)

    def step_settled(self, event: StepEvent) -> None:
        """A walkthrough step finished (from the learning event log's stream)."""
        if self.coach is None or not self.studying:
            return
        kind = {
            StepOutcome.SUCCEEDED: LearnerEventKind.ATTEMPT_SUCCEEDED,
            StepOutcome.RETRIED: LearnerEventKind.ATTEMPT_FAILED,
            StepOutcome.TIMED_OUT: LearnerEventKind.STUCK,
        }.get(event.outcome)
        if kind is None:
            return
        problem_id = self.problems.for_walkthrough(event.task)
        try:
            # Updates the coach's per-problem state; the instruction itself is not
            # spoken here, because the next turn is the walkthrough's own.
            self.coach.next_move(
                LearnerEvent(kind=kind, concepts=event.concepts, problem_id=problem_id,
                             at=event.occurred_at)
            )
        except Exception:
            logger.exception("study coach failed on a step event")

    def walkthrough_finished(self, task: str, completed: bool) -> None:
        if completed:
            self.problems.solved(self.problems.for_walkthrough(task))
