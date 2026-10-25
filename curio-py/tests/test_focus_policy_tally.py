from datetime import UTC, datetime, timedelta

from curio.focus_contract import (
    FocusPlan,
    FocusSignal,
    Intervention,
    InterventionKind,
    InterventionResponse,
    SignalKind,
)
from curio.focus_policy import SessionTally

T0 = datetime(2026, 10, 24, 14, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def at(self, minutes: float) -> datetime:
        self.now = T0 + timedelta(minutes=minutes)
        return self.now


def setup():
    clock = FakeClock()
    plan = FocusPlan(goal="the excel assignment", duration=timedelta(minutes=30), started_at=T0)
    return clock, plan, SessionTally(plan, clock=clock)


def sig(clock, minutes, kind, **extra):
    return FocusSignal(kind=kind, at=clock.at(minutes), **extra)


def check_in(kind=InterventionKind.CHECK_IN):
    return Intervention(kind=kind, message="still on it?")


def test_full_session_timeline():
    clock, plan, tally = setup()
    tally.observe(sig(clock, 10, SignalKind.DRIFT_STARTED, drift_seconds=60))  # began at 9
    nudge = check_in()
    tally.record_intervention(nudge)
    tally.record_response(nudge, InterventionResponse.ACCEPTED)
    tally.observe(sig(clock, 14, SignalKind.RETURNED))
    offer = check_in(InterventionKind.BREAK_START)
    tally.record_intervention(offer)
    clock.at(20)
    tally.record_response(offer, InterventionResponse.ACCEPTED)
    tally.observe(sig(clock, 21, SignalKind.DRIFT_STARTED, drift_seconds=30))  # ignored
    tally.observe(sig(clock, 25, SignalKind.BREAK_OVER))
    clock.at(30)
    summary = tally.summary(reflection="group chat got in the way")
    assert summary.on_goal_seconds == (9 + 6 + 5) * 60
    assert summary.off_goal_seconds == 5 * 60
    assert summary.break_seconds == 5 * 60
    assert summary.drift_count == 1
    assert summary.interventions == 2
    assert summary.false_alarms == 0
    assert (summary.started_at, summary.ended_at) == (T0, T0 + timedelta(minutes=30))
    assert summary.goal == plan.goal and summary.plan_id == plan.id
    assert summary.reflection == "group chat got in the way"
    total = summary.on_goal_seconds + summary.off_goal_seconds + summary.break_seconds
    assert total == 30 * 60


def test_false_alarm_during_drift_moves_time_back_on_goal():
    clock, _, tally = setup()
    tally.observe(sig(clock, 5, SignalKind.DRIFT_STARTED, drift_seconds=60))
    nudge = check_in()
    tally.record_intervention(nudge)
    clock.at(7)
    tally.record_response(nudge, InterventionResponse.FALSE_ALARM)
    clock.at(10)
    summary = tally.summary()
    assert summary.off_goal_seconds == 0
    assert summary.on_goal_seconds == 10 * 60
    assert summary.drift_count == 0
    assert summary.false_alarms == 1


def test_false_alarm_after_return_undoes_that_drift_once():
    clock, _, tally = setup()
    tally.observe(sig(clock, 5, SignalKind.DRIFT_STARTED, drift_seconds=0))
    tally.observe(sig(clock, 8, SignalKind.RETURNED))
    resume = check_in(InterventionKind.RESUME)
    tally.record_response(resume, InterventionResponse.FALSE_ALARM)
    tally.record_response(resume, InterventionResponse.FALSE_ALARM)
    clock.at(10)
    summary = tally.summary()
    assert summary.off_goal_seconds == 0
    assert summary.on_goal_seconds == 10 * 60
    assert summary.false_alarms == 2
    assert summary.drift_count == 0


def test_drift_start_never_reaches_before_the_last_change():
    clock, _, tally = setup()
    tally.start_break(clock.at(1))
    tally.observe(sig(clock, 6, SignalKind.BREAK_OVER))
    tally.observe(sig(clock, 7, SignalKind.DRIFT_STARTED, drift_seconds=600))
    clock.at(9)
    summary = tally.summary()
    assert summary.break_seconds == 5 * 60
    assert summary.on_goal_seconds == 1 * 60
    assert summary.off_goal_seconds == 3 * 60


def test_break_during_a_drift_ends_the_drift():
    clock, _, tally = setup()
    tally.observe(sig(clock, 2, SignalKind.DRIFT_STARTED, drift_seconds=0))
    tally.start_break(clock.at(4))
    tally.observe(sig(clock, 5, SignalKind.RETURNED))  # not off-goal any more; ignored
    tally.observe(sig(clock, 9, SignalKind.BREAK_OVER))
    clock.at(10)
    summary = tally.summary()
    assert (summary.on_goal_seconds, summary.off_goal_seconds, summary.break_seconds) == (
        3 * 60,
        2 * 60,
        5 * 60,
    )


def test_concepts_are_deduplicated_in_order():
    clock, _, tally = setup()
    tally.add_concepts(["vlookup", "pivot tables"])
    tally.add_concepts(["vlookup", "charts"])
    assert tally.summary().concepts_practised == ("vlookup", "pivot tables", "charts")
