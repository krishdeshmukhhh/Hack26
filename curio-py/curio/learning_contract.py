"""Shared contracts for walkthrough events, the task map and the skill model.

Standard library only; no Qt, persistence, network or model clients. Four
workstreams build against this file in parallel (see docs/parallel/README.md):

- integration records a ``StepEvent`` per walkthrough step and fans each
  finished ``WalkthroughSummary`` out to the task map and skill model;
- the task map turns reported completions into recorded ``TaskPath``s;
- opt-in map sync shares minimized references and recorded stuck signals;
- the skill model tracks per-concept mastery for this user only.

Change this file only through the integration workstream.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import uuid4


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


class StepOutcome(StrEnum):
    SUCCEEDED = "succeeded"  # model reported progression/completion, not independent proof
    RETRIED = "retried"  # the model gave the same step again: it didn't work
    ABANDONED = "abandoned"  # Esc, a new push-to-talk question, or an error
    TIMED_OUT = "timed_out"  # no click before the walkthrough timeout


class AssistanceLevel(StrEnum):
    """How much help a step got, most help first. Also the skill model's advice."""

    DID_IT = "did_it"  # reserved for performed actions; voice activation does not use this
    POINTED = "pointed"  # flew to the element and waited for the user's click
    HINTED = "hinted"  # spoken hint only, no pointing
    NONE = "none"  # user did it without help


ASSISTANCE_ORDER: tuple[AssistanceLevel, ...] = tuple(AssistanceLevel)

EVIDENCE_BASES = frozenset({
    "unknown", "model_inferred", "user_confirmed", "checked_success", "checked_failure",
})


@dataclass(frozen=True, kw_only=True)
class ElementRef:
    """The on-screen element a step targets.

    ``x``/``y`` are 0..1 fractions of the screenshot, so they survive different
    resolutions. ``window_title`` is local only and never leaves the device.
    """

    label: str
    x: float
    y: float
    window_title: str = ""


@dataclass(frozen=True, kw_only=True)
class StepEvent:
    walkthrough_id: str
    app: str  # app_key(), e.g. "excel"
    task: str  # task_key() of the user's original question
    step_index: int  # 1-based
    instruction: str  # spoken step text, tags removed
    assistance: AssistanceLevel
    outcome: StepOutcome
    element: ElementRef | None = None
    concepts: tuple[str, ...] = ()  # concept_key()s from the [CONCEPTS:...] tag
    app_version: str = ""
    id: str = field(default_factory=_new_id)
    occurred_at: datetime = field(default_factory=_utc_now)
    evidence_basis: str = "unknown"
    evidence_ref: str = ""  # opaque LOCAL verifier result reference; never exported to sync
    synthetic: bool = False  # unmarked origin is unknown, not proof of a real user

    def __post_init__(self) -> None:
        if self.evidence_basis not in EVIDENCE_BASES:
            raise ValueError("Unknown evidence basis")
        if self.evidence_basis.startswith("checked_"):
            expected = (StepOutcome.SUCCEEDED if self.evidence_basis == "checked_success"
                        else StepOutcome.RETRIED)
            if not self.evidence_ref.strip() or self.outcome != expected:
                raise ValueError("Checked evidence needs a result reference and matching outcome")
        if self.evidence_basis == "user_confirmed" and self.outcome != StepOutcome.SUCCEEDED:
            raise ValueError("User confirmation requires reported success")
        if not isinstance(self.synthetic, bool):
            raise ValueError("synthetic must be boolean")

    @property
    def independently_verified(self) -> bool:
        """A caller supplied checked evidence; the adapter remains responsible for truth."""
        return self.evidence_basis == "checked_success" and not self.synthetic


@dataclass(frozen=True, kw_only=True)
class WalkthroughSummary:
    """A finished lifecycle with separate completion origin; defaults remain unknown."""

    walkthrough_id: str
    app: str
    task: str
    steps: tuple[StepEvent, ...]
    completed: bool
    app_version: str = ""
    finished_at: datetime = field(default_factory=_utc_now)
    completed_basis: str = "unknown"
    synthetic: bool = False

    def __post_init__(self) -> None:
        if self.completed_basis not in EVIDENCE_BASES:
            raise ValueError("Unknown completion basis")
        if not isinstance(self.synthetic, bool):
            raise ValueError("synthetic must be boolean")


@dataclass(frozen=True, kw_only=True)
class PathStep:
    index: int  # 1-based
    instruction: str
    element: ElementRef | None = None
    concepts: tuple[str, ...] = ()
    difficulty: float | None = None  # recorded stuck-event rate 0..1; None = unknown


class PathSource(StrEnum):
    LOCAL = "local"
    SHARED = "shared"


@dataclass(frozen=True, kw_only=True)
class TaskPath:
    app: str
    task: str
    steps: tuple[PathStep, ...]
    verified_count: int = 1  # model-completed walkthrough count; legacy name, not verification
    source: PathSource = PathSource.LOCAL
    app_version: str = ""
    id: str = field(default_factory=_new_id)
    updated_at: datetime = field(default_factory=_utc_now)
    evidence_basis: str = "unknown"

    @property
    def report_count(self) -> int:
        """Clear alias for legacy verified_count, never independent verification."""
        return self.verified_count


@dataclass(frozen=True, kw_only=True)
class SkillState:
    concept: str
    mastery: float  # unvalidated familiarity estimate 0..1, not measured knowledge
    attempts: int
    last_practiced: datetime | None = None
    apps: tuple[str, ...] = ()


# --- Protocols ---------------------------------------------------------------


class EventLog(Protocol):
    """Local, append-only store of step events. Owned by integration."""

    async def append(self, event: StepEvent) -> None: ...

    async def walkthrough(self, walkthrough_id: str) -> tuple[StepEvent, ...]: ...

    async def recent(self, limit: int = 200, app: str | None = None) -> tuple[StepEvent, ...]: ...

    async def clear(self) -> None: ...


class TaskMap(Protocol):
    """Recorded task paths; completion is model-reported, not independently verified."""

    async def record(self, summary: WalkthroughSummary) -> TaskPath | None:
        """Learn from a finished walkthrough; returns the path it created or reinforced."""
        ...

    async def find(self, app: str, task: str) -> TaskPath | None:
        """Best known path for a task, matched loosely on the task text."""
        ...

    async def paths(self, app: str | None = None) -> tuple[TaskPath, ...]: ...

    async def merge(self, shared: Sequence[TaskPath]) -> int:
        """Merge paths pulled from map sync; returns how many changed."""
        ...


class DifficultyProvider(Protocol):
    """Crowd difficulty for a step. Sync, cached: called on the UI thread."""

    def step_difficulty(self, app: str, task: str, step_index: int) -> float | None: ...


class MapSync(DifficultyProvider, Protocol):
    """Client for the shared map server. Every method must fail soft when offline."""

    async def push(self, summary: WalkthroughSummary) -> bool: ...

    async def pull(self, app: str | None = None) -> tuple[TaskPath, ...]: ...


class SkillModel(Protocol):
    """Per-user concept mastery. Never leaves the device."""

    async def observe(self, summary: WalkthroughSummary) -> None: ...

    async def snapshot(self) -> tuple[SkillState, ...]: ...

    async def recommend_assistance(self, app: str, concepts: Sequence[str]) -> AssistanceLevel: ...

    async def prompt_context(self, app: str, concepts: Sequence[str]) -> str | None:
        """One or two plain sentences for the system prompt, or None.

        For example: "the model estimates familiarity with layers; transfer to
        frames in figma is a hypothesis, not measured knowledge."
        """
        ...

    async def reset(self) -> None: ...


# --- Normalisation and wire format -------------------------------------------

_NON_WORD_RE = re.compile(r"[^a-z0-9]+")
_FILLER_RE = re.compile(
    r"^(hey curio|curio|ok|okay|so|um|uh|please|can you|could you|"
    r"how do i|how can i|how to|show me how to|walk me through|i want to|help me)\s+"
)
_TITLE_SEPARATORS = (" - ", " — ", " | ")


def app_key(window_title: str) -> str:
    """Stable app identifier from a foreground window title.

    Windows titles usually end with the app name ("Book1 - Excel"), so the last
    segment is used. Lowercase, non-alphanumerics collapsed to single spaces.
    """
    title = window_title.strip()
    for sep in _TITLE_SEPARATORS:
        if sep in title:
            title = title.rsplit(sep, 1)[1]
            break
    return _NON_WORD_RE.sub(" ", title.lower()).strip()


def task_key(question: str) -> str:
    """Normalised task text: lowercase, no punctuation, leading filler removed."""
    text = _NON_WORD_RE.sub(" ", question.lower()).strip()
    previous = None
    while previous != text:
        previous = text
        text = _FILLER_RE.sub("", text).strip()
    return text


def concept_key(concept: str) -> str:
    return _NON_WORD_RE.sub(" ", concept.lower()).strip()


WIRE_VERSION = 1


def _element_to_wire(element: ElementRef | None) -> dict[str, Any] | None:
    if element is None:
        return None
    # window_title is deliberately dropped: titles carry file and document names.
    return {"label": element.label, "x": element.x, "y": element.y}


def _element_from_wire(raw: dict[str, Any] | None) -> ElementRef | None:
    if raw is None:
        return None
    return ElementRef(label=str(raw["label"]), x=float(raw["x"]), y=float(raw["y"]))


def summary_to_wire(summary: WalkthroughSummary) -> dict[str, Any]:
    """Minimized v1 payload; local evidence references/bases are never exported.

    Optional synthetic marking requires the updated server. Unmarked origins
    stay unknown; free text is not guaranteed anonymous.
    """
    return {
        "v": WIRE_VERSION,
        "app": summary.app,
        "app_version": summary.app_version,
        "task": summary.task,
        "completed": summary.completed,
        **({"synthetic": True} if summary.synthetic or any(s.synthetic for s in summary.steps)
           else {}),
        "steps": [
            {
                "index": s.step_index,
                "instruction": s.instruction,
                "element": _element_to_wire(s.element),
                "concepts": list(s.concepts),
                "assistance": s.assistance.value,
                "outcome": s.outcome.value,
            }
            for s in summary.steps
        ],
    }


def path_to_wire(path: TaskPath) -> dict[str, Any]:
    return {
        "v": WIRE_VERSION,
        "app": path.app,
        "app_version": path.app_version,
        "task": path.task,
        "verified_count": path.verified_count,
        **({"evidence_basis": "model_reported"}
           if path.evidence_basis == "model_reported" else {}),
        "steps": [
            {
                "index": s.index,
                "instruction": s.instruction,
                "element": _element_to_wire(s.element),
                "concepts": list(s.concepts),
                "difficulty": s.difficulty,
            }
            for s in path.steps
        ],
    }


def path_from_wire(raw: dict[str, Any]) -> TaskPath:
    """Parse a shared path. Raises ValueError/KeyError/TypeError on malformed input."""
    if raw.get("v") != WIRE_VERSION:
        raise ValueError(f"unsupported wire version: {raw.get('v')!r}")
    steps = tuple(
        PathStep(
            index=int(s["index"]),
            instruction=str(s["instruction"]),
            element=_element_from_wire(s.get("element")),
            concepts=tuple(concept_key(str(c)) for c in s.get("concepts", ())),
            difficulty=None if s.get("difficulty") is None else float(s["difficulty"]),
        )
        for s in raw["steps"]
    )
    return TaskPath(
        app=str(raw["app"]),
        task=str(raw["task"]),
        steps=steps,
        verified_count=int(raw.get("verified_count", 1)),
        source=PathSource.SHARED,
        evidence_basis=("model_reported" if raw.get("evidence_basis") == "model_reported"
                        else "unknown"),
        app_version=str(raw.get("app_version", "")),
    )
