"""Classroom / lab mode: what a student's Curio shares with the instructor.

Each student's Curio answers routine questions as usual. In lab mode it
also tracks which lab step the student is on and whether they look stuck,
and reports only that (a random per-launch id, a step number and a stuck
flag) to the instructor's lab server. Questions, answers and screenshots
never leave the student's own pipeline.

The instructor's dashboard shows counts per step. A hint the TA sends for a
step reaches the students stuck on it, and each student's Curio finds the
hint's target on its own screen and points at it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# Students who ask this many questions on one step are counted as stuck.
DEFAULT_STUCK_AFTER_QUESTIONS = 3
MAX_HINT_TEXT = 500
MAX_HINT_TARGET = 120

# Asking for a person rather than for Curio marks the student stuck at once.
_ASK_FOR_HUMAN_RE = re.compile(
    r"\b(i'?m|i am|i'?ve been|i keep getting) (stuck|lost|confused)\b"
    r"|\b(ask|get|call|need|tell) (the |my |a )?(ta|t\.a\.|tee ay|instructor|professor|teacher)\b"
    r"|\bnothing (is )?work(s|ing)\b",
    re.IGNORECASE,
)


def asks_for_human(text: str) -> bool:
    return bool(_ASK_FOR_HUMAN_RE.search(text))


@dataclass(frozen=True)
class LabSettings:
    """``[lab]`` in config.toml."""

    enabled: bool = False
    server_url: str = ""
    code: str = ""
    stuck_after_questions: int = DEFAULT_STUCK_AFTER_QUESTIONS
    poll_seconds: float = 3.0

    @classmethod
    def from_dict(cls, data: object) -> LabSettings:
        if not isinstance(data, dict):
            raise ValueError("[lab] must be a table")
        enabled = data.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError("lab.enabled must be true or false")
        server_url = data.get("server_url", "")
        code = data.get("code", "")
        if not isinstance(server_url, str) or not isinstance(code, str):
            raise ValueError("lab.server_url and lab.code must be strings")
        server_url = server_url.strip().rstrip("/")
        if enabled and not server_url.startswith(("http://", "https://")):
            raise ValueError("lab.server_url must be an http:// or https:// URL")
        if enabled and not code.strip():
            raise ValueError("lab.code is required when lab.enabled = true")
        threshold = data.get("stuck_after_questions", DEFAULT_STUCK_AFTER_QUESTIONS)
        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, int)
            or not 1 <= threshold <= 20
        ):
            raise ValueError("lab.stuck_after_questions must be an integer from 1 to 20")
        poll = data.get("poll_seconds", 3.0)
        if isinstance(poll, bool) or not isinstance(poll, int | float) or not 1 <= poll <= 60:
            raise ValueError("lab.poll_seconds must be a number from 1 to 60")
        return cls(
            enabled=enabled,
            server_url=server_url,
            code=code.strip(),
            stuck_after_questions=threshold,
            poll_seconds=float(poll),
        )


@dataclass(frozen=True, slots=True)
class LabStep:
    index: int
    title: str


@dataclass(frozen=True, slots=True)
class LabHint:
    """A TA's hint. ``target`` names what to point at; empty means "use the text"."""

    id: int
    step: int
    text: str
    target: str = ""

    @classmethod
    def from_payload(cls, data: Any) -> LabHint | None:
        if not isinstance(data, dict):
            return None
        hint_id, step = data.get("id"), data.get("step")
        text, target = data.get("text"), data.get("target", "")
        if not isinstance(hint_id, int) or not isinstance(step, int):
            return None
        if not isinstance(text, str) or not text.strip() or not isinstance(target, str):
            return None
        return cls(hint_id, step, text.strip()[:MAX_HINT_TEXT], target.strip()[:MAX_HINT_TARGET])


def parse_steps(data: Any) -> tuple[LabStep, ...]:
    if not isinstance(data, list):
        return ()
    steps = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("index"), int):
            title = item.get("title")
            if isinstance(title, str):
                steps.append(LabStep(item["index"], title))
    return tuple(steps)


@dataclass
class LabTracker:
    """The student's lab progress, as reported to the instructor.

    ``step`` is 0 until known. It comes from the model's [LAB:k] tag (it can
    see the screen and the lab's step list) or from the tray menu. Moving to
    a new step clears ``stuck``; asking for a person or repeating questions
    on one step sets it.
    """

    stuck_after_questions: int = DEFAULT_STUCK_AFTER_QUESTIONS
    on_change: Callable[[], None] | None = None
    lab_name: str = ""
    steps: tuple[LabStep, ...] = ()
    step: int = 0
    stuck: bool = False
    questions_on_step: int = field(default=0, repr=False)

    def _changed(self) -> None:
        if self.on_change is not None:
            self.on_change()

    def set_lab(self, name: str, steps: tuple[LabStep, ...]) -> None:
        if (name, steps) == (self.lab_name, self.steps):
            return
        self.lab_name, self.steps = name, steps
        if self.step and not self.valid_step(self.step):
            self.step = 0
        self._changed()

    def valid_step(self, index: int) -> bool:
        return any(step.index == index for step in self.steps)

    def set_step(self, index: int) -> None:
        if index == self.step or not self.valid_step(index):
            return
        self.step = index
        self.questions_on_step = 0
        self.stuck = False
        self._changed()

    def set_stuck(self, stuck: bool) -> None:
        if stuck == self.stuck:
            return
        self.stuck = stuck
        if not stuck:
            self.questions_on_step = 0
        self._changed()

    def record_turn(self, text: str, inferred_step: int | None, *, is_question: bool) -> None:
        """Update from one answered turn.

        ``is_question`` is False for walkthrough continuations and hint
        deliveries: those move the step along but aren't the student asking.
        """
        if inferred_step is not None:
            self.set_step(inferred_step)
        if not is_question or self.stuck:
            return
        self.questions_on_step += 1
        if asks_for_human(text) or self.questions_on_step >= self.stuck_after_questions:
            self.set_stuck(True)

    def wants_hint(self, hint: LabHint) -> bool:
        """False once the student has moved on to a different known step."""
        return hint.step == 0 or self.step in (0, hint.step)

    def prompt_context(self) -> str | None:
        if not self.steps:
            return None
        lines = "\n".join(f"{step.index}. {step.title}" for step in self.steps)
        name = f' called "{self.lab_name}"' if self.lab_name else ""
        current = f" they last seemed to be on step {self.step}." if self.step else ""
        return (
            f"\nlab mode:\nthe user is a student doing a class lab{name}. its steps are:\n"
            f"{lines}\n"
            f"from their screen and question, judge which lab step they're working on.{current} "
            "add [LAB:k] with that step number right before the POINT tag. if you can't tell, "
            "leave it out. help them understand the step, but don't do graded work for them."
        )


def hint_spoken_text(hint: LabHint) -> str:
    where = f" for step {hint.step}" if hint.step else ""
    return f"hint from your TA{where}. {hint.text}"


def hint_point_request(hint: LabHint) -> str:
    """The request that asks the model where the hint's target is on this screen.

    The model only locates; the TA's own words are what gets spoken.
    """
    target = hint.target or "whatever on screen this hint is about"
    return (
        f'(this isn\'t a question. my lab TA sent this hint: "{hint.text}". '
        f"find {target} on my screen and point at it. reply with only the POINT tag, "
        "or [POINT:none] if it isn't visible.)"
    )


_LAB_RE = re.compile(r"\s*\[LAB:\s*(\d+)\s*\]")


def parse_lab_tag(response: str) -> tuple[str, int | None]:
    """Remove a [LAB:k] tag from anywhere in the response."""
    m = _LAB_RE.search(response)
    if not m:
        return (response, None)
    rest = (response[: m.start()] + response[m.end():]).rstrip()
    index = int(m.group(1))
    return (rest, index if index >= 1 else None)
