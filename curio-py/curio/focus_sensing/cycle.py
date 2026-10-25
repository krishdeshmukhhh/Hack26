"""Fixed study/break cycle arithmetic shared by the classifier and drift tracker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from curio.focus_contract import BreakStyle, FocusPlan


@dataclass(frozen=True, kw_only=True)
class BreakPhase:
    on_break: bool
    cycle: int  # 0-based study/break cycle index
    phase_ends_at: datetime | None  # None when the plan has no fixed cycle


def break_phase(plan: FocusPlan, at: datetime) -> BreakPhase:
    """Where ``at`` falls in the plan's fixed cycle (section E).

    Self-paced and no-break plans are never on a scheduled break. Time before
    the session starts counts as study.
    """
    study = timedelta(minutes=plan.study_minutes)
    rest = timedelta(minutes=plan.break_minutes)
    if plan.break_style != BreakStyle.FIXED or study <= timedelta(0) or rest <= timedelta(0):
        return BreakPhase(on_break=False, cycle=0, phase_ends_at=None)
    elapsed = max(at - plan.started_at, timedelta(0))
    period = study + rest
    cycle, position = divmod(elapsed, period)
    cycle_start = plan.started_at + cycle * period
    if position < study:
        return BreakPhase(on_break=False, cycle=cycle, phase_ends_at=cycle_start + study)
    return BreakPhase(on_break=True, cycle=cycle, phase_ends_at=cycle_start + period)
