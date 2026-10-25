"""Turns walkthrough answers into settled ``StepEvent``s. No Qt or I/O.

A step's outcome is only known when the next thing happens, so each answer
leaves a pending step that the next answer (or the walkthrough's end) settles.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from curio.learning_contract import (
    AssistanceLevel,
    ElementRef,
    StepEvent,
    StepOutcome,
    WalkthroughSummary,
)
from curio.point_parser import PointTag

if TYPE_CHECKING:
    from curio.screen_capture import ScreenshotImage


@dataclass(frozen=True, kw_only=True)
class PendingStep:
    step_index: int
    instruction: str
    assistance: AssistanceLevel
    element: ElementRef | None = None
    concepts: tuple[str, ...] = ()


def element_from_point(
    tag: PointTag,
    screenshots: list[ScreenshotImage],
    point_coords: str,
    window_title: str = "",
) -> ElementRef | None:
    """POINT tag → element at 0..1 fractions of its screenshot."""
    if not screenshots:
        return None
    if tag.screen is not None and 1 <= tag.screen <= len(screenshots):
        shot = screenshots[tag.screen - 1]
    else:
        shot = screenshots[0]
    if point_coords == "norm1000":
        x, y = tag.x / 1000, tag.y / 1000
    else:
        if shot.image_width_px <= 0 or shot.image_height_px <= 0:
            return None
        x, y = tag.x / shot.image_width_px, tag.y / shot.image_height_px
    return ElementRef(
        label=tag.label,
        x=min(max(x, 0.0), 1.0),
        y=min(max(y, 0.0), 1.0),
        window_title=window_title,
    )


class WalkthroughRecorder:
    """One walkthrough's events, from the opening answer to its end."""

    def __init__(self, *, app: str, task: str, app_version: str = "") -> None:
        self.walkthrough_id = str(uuid4())
        self.app = app
        self.task = task
        self.app_version = app_version
        self._events: list[StepEvent] = []
        self._pending: PendingStep | None = None

    @property
    def pending(self) -> PendingStep | None:
        return self._pending

    @property
    def events(self) -> tuple[StepEvent, ...]:
        return tuple(self._events)

    def step_answered(self, step: PendingStep) -> StepEvent | None:
        """Record a new step answer; returns the previous step, now settled.

        Index changes describe model-inferred progress or repetition only.
        The legacy outcome is retained for API compatibility; provenance must
        travel with it and must never be interpreted as an independent check.
        """
        settled = None
        if self._pending is not None:
            outcome = (
                StepOutcome.SUCCEEDED
                if step.step_index > self._pending.step_index
                else StepOutcome.RETRIED
            )
            settled = self._settle(outcome)
        self._pending = step
        return settled

    def finish(
        self, outcome: StepOutcome, *, completed: bool,
        evidence_basis: str = "model_inferred", evidence_ref: str = "",
    ) -> tuple[StepEvent | None, WalkthroughSummary]:
        """Settle the pending step with ``outcome`` and summarise the walkthrough."""
        settled = (
            self._settle(outcome, evidence_basis=evidence_basis, evidence_ref=evidence_ref)
            if self._pending is not None else None
        )
        summary = WalkthroughSummary(
            walkthrough_id=self.walkthrough_id,
            app=self.app,
            task=self.task,
            steps=tuple(self._events),
            completed=completed,
            completed_basis=evidence_basis if completed else "unknown",
            app_version=self.app_version,
        )
        return settled, summary

    def _settle(
        self, outcome: StepOutcome, *, evidence_basis: str = "model_inferred",
        evidence_ref: str = "",
    ) -> StepEvent:
        pending = self._pending
        assert pending is not None
        event = StepEvent(
            evidence_basis=evidence_basis,
            evidence_ref=evidence_ref,
            walkthrough_id=self.walkthrough_id,
            app=self.app,
            task=self.task,
            step_index=pending.step_index,
            instruction=pending.instruction,
            assistance=pending.assistance,
            outcome=outcome,
            element=pending.element,
            concepts=pending.concepts,
            app_version=self.app_version,
        )
        self._events.append(event)
        self._pending = None
        return event
