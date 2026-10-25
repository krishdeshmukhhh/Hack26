from datetime import timedelta

from curio.coaching_contract import AssistanceLevel
from curio.focus_contract import (
    COACHING_LEVEL,
    HELP_LADDER,
    BreakStyle,
    FocusPlan,
    Intervention,
    InterventionKind,
    TutoringMove,
)


def test_help_ladder_starts_with_least_help():
    assert HELP_LADDER[0] is TutoringMove.GUIDING_QUESTION
    assert HELP_LADDER[-1] is TutoringMove.WORKED_EXAMPLE


def test_every_ladder_rung_maps_to_a_coaching_level():
    assert set(HELP_LADDER) <= set(COACHING_LEVEL)
    assert COACHING_LEVEL[TutoringMove.WORKED_EXAMPLE] is AssistanceLevel.WORKED_EXAMPLE


def test_plan_defaults_never_block():
    plan = FocusPlan(goal="finish the pivot table assignment", duration=timedelta(minutes=50))
    assert plan.strict is False
    assert plan.break_style is BreakStyle.FIXED
    assert (plan.study_minutes, plan.break_minutes) == (25, 5)


def test_interventions_get_unique_ids():
    a = Intervention(kind=InterventionKind.CHECK_IN, message="still on it?")
    b = Intervention(kind=InterventionKind.CHECK_IN, message="still on it?")
    assert a.id != b.id
