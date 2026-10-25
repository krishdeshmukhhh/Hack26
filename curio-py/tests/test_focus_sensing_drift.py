from datetime import UTC, datetime, timedelta

from curio.focus_contract import (
    ActivitySample,
    BreakpointKind,
    BreakStyle,
    FocusPlan,
    JudgmentSource,
    SignalKind,
    TrackAssessment,
    TrackJudgment,
)
from curio.focus_sensing import (
    DriftThresholds,
    ThresholdDriftTracker,
    break_phase,
    scripted_samples,
)

T0 = datetime(2026, 10, 24, 14, 0, tzinfo=UTC)

JUDGMENTS = {
    "excel": TrackJudgment.ON_GOAL,
    "youtube": TrackJudgment.OFF_GOAL,
    "reddit": TrackJudgment.OFF_GOAL,
    "docs": TrackJudgment.ON_GOAL,
    "mystery": TrackJudgment.UNSURE,
    "break": TrackJudgment.ON_BREAK,
}


def _plan(**kwargs) -> FocusPlan:
    defaults = dict(
        goal="excel assignment",
        duration=timedelta(minutes=60),
        break_style=BreakStyle.NONE,
        started_at=T0,
    )
    defaults.update(kwargs)
    return FocusPlan(**defaults)


def _assess(sample: ActivitySample) -> TrackAssessment:
    return TrackAssessment(
        judgment=JUDGMENTS[sample.app], confidence=0.9, source=JudgmentSource.RULE
    )


def _run(steps, plan=None, thresholds=None, start=T0):
    tracker = ThresholdDriftTracker(thresholds, plan or _plan())
    signals = []
    for sample in scripted_samples(steps, start=start):
        signals.extend(tracker.update(sample, _assess(sample)))
    return tracker, signals


def _kinds(signals, kind):
    return [s for s in signals if s.kind == kind]


def _breakpoints(signals, kind):
    return [s for s in signals if s.kind == SignalKind.BREAKPOINT and s.breakpoint == kind]


def test_youtube_drift_starts_after_sustained_off_goal_time():
    tracker, signals = _run([("excel", "Book1 - Excel", 20), ("youtube", "cats - YouTube", 120)])
    started = _kinds(signals, SignalKind.DRIFT_STARTED)
    assert len(started) == 1
    # 90 s of off-goal time: switched at t=20, so the drift is declared at t=110.
    assert started[0].at == T0 + timedelta(seconds=110)
    assert started[0].drift_seconds == 90
    assert started[0].assessment.judgment == TrackJudgment.OFF_GOAL
    assert tracker.drifting
    assert tracker.totals.drift_count == 1


def test_drift_continuing_and_returned_with_length():
    _, signals = _run(
        [
            ("excel", "Book1 - Excel", 10),
            ("youtube", "cats - YouTube", 250),
            ("excel", "Book1 - Excel", 30),
        ]
    )
    assert len(_kinds(signals, SignalKind.DRIFT_STARTED)) == 1
    continuing = _kinds(signals, SignalKind.DRIFT_CONTINUING)
    assert [c.at - T0 for c in continuing] == [timedelta(seconds=220)]
    returned = _kinds(signals, SignalKind.RETURNED)
    assert len(returned) == 1
    assert returned[0].drift_seconds == 250
    # Return is confirmed once 15 s of on-goal time has passed (next sample: 16 s).
    assert returned[0].at == T0 + timedelta(seconds=260 + 16)


def test_quick_lookup_is_not_drift():
    # A 30 s unsure detour and a minute in the docs: research, not drift.
    _, signals = _run(
        [
            ("excel", "Book1 - Excel", 20),
            ("mystery", "New Tab - Google Chrome", 30),
            ("docs", "VLOOKUP function - Microsoft Support", 60),
            ("excel", "Book1 - Excel", 60),
        ]
    )
    assert not _kinds(signals, SignalKind.DRIFT_STARTED)


def test_unsure_counts_at_half_weight():
    _, signals = _run([("excel", "x - Excel", 10), ("mystery", "Something", 200)])
    started = _kinds(signals, SignalKind.DRIFT_STARTED)
    assert len(started) == 1
    assert started[0].drift_seconds == 180  # 180 s of unsure = 90 weighted


def test_repeated_short_returns_trigger_drift():
    visit = [("excel", "Book1 - Excel", 30), ("reddit", "r/all - Reddit", 10)]
    _, signals = _run(visit * 3 + [("excel", "Book1 - Excel", 30)])
    started = _kinds(signals, SignalKind.DRIFT_STARTED)
    assert len(started) == 1
    # Only 20-ish seconds off goal, but the third visit within 3 minutes counts.
    assert started[0].at == T0 + timedelta(seconds=30 + 40 + 40)


def test_spread_out_visits_do_not_trigger_repeat_drift():
    visit = [("excel", "Book1 - Excel", 120), ("reddit", "r/all - Reddit", 6)]
    _, signals = _run(visit * 4)
    assert not _kinds(signals, SignalKind.DRIFT_STARTED)


def test_brief_switch_back_does_not_reset_drift():
    _, signals = _run(
        [
            ("excel", "Book1 - Excel", 10),
            ("youtube", "cats - YouTube", 100),
            ("excel", "Book1 - Excel", 6),  # glance back, shorter than the grace period
            ("youtube", "cats - YouTube", 20),
            ("excel", "Book1 - Excel", 30),
        ]
    )
    assert len(_kinds(signals, SignalKind.DRIFT_STARTED)) == 1
    returned = _kinds(signals, SignalKind.RETURNED)
    assert len(returned) == 1
    assert returned[0].drift_seconds == 126  # 100 + 6 + 20: one episode


def test_brief_switch_back_keeps_partial_score():
    # 60 s off, 6 s back, 40 s off again: crosses 90 without a full return.
    _, signals = _run(
        [
            ("excel", "Book1 - Excel", 10),
            ("youtube", "cats - YouTube", 60),
            ("excel", "Book1 - Excel", 6),
            ("youtube", "cats - YouTube", 40),
        ]
    )
    assert len(_kinds(signals, SignalKind.DRIFT_STARTED)) == 1


def test_full_return_resets_partial_score():
    _, signals = _run(
        [
            ("excel", "Book1 - Excel", 10),
            ("youtube", "cats - YouTube", 60),
            ("excel", "Book1 - Excel", 30),
            ("youtube", "cats - YouTube", 60),
        ]
    )
    assert not _kinds(signals, SignalKind.DRIFT_STARTED)


def test_idle_is_not_counted_as_drift():
    # Left YouTube open and walked away: idle climbs, no drift.
    steps = [("excel", "Book1 - Excel", 10)]
    steps += [("youtube", "cats - YouTube", 2, idle, 0) for idle in range(62, 400, 2)]
    tracker, signals = _run(steps)
    assert not _kinds(signals, SignalKind.DRIFT_STARTED)
    idle = _kinds(signals, SignalKind.IDLE)
    assert len(idle) == 1
    assert idle[0].sample.idle_seconds == 180
    assert tracker.totals.idle_seconds > 300
    assert tracker.totals.off_goal_seconds == 0


def test_idle_resume_breakpoint():
    steps = [("excel", "Book1 - Excel", 2, idle, 0) for idle in (30, 50, 70, 90)]
    steps += [("excel", "Book1 - Excel", 2, 0.5, 4)]
    _, signals = _run(steps)
    resumed = _breakpoints(signals, BreakpointKind.IDLE_RESUME)
    assert len(resumed) == 1
    assert resumed[0].sample.idle_seconds == 0.5


def test_no_idle_resume_after_short_idle():
    steps = [("excel", "Book1 - Excel", 2, idle, 0) for idle in (10, 20, 30)]
    steps += [("excel", "Book1 - Excel", 2, 0.5, 4)]
    _, signals = _run(steps)
    assert not _breakpoints(signals, BreakpointKind.IDLE_RESUME)


def test_app_switch_breakpoint():
    _, signals = _run([("excel", "Book1 - Excel", 4), ("docs", "MDN Web Docs", 4)])
    switches = _breakpoints(signals, BreakpointKind.APP_SWITCH)
    assert len(switches) == 1
    assert switches[0].sample.app == "docs"
    assert switches[0].assessment.judgment == TrackJudgment.ON_GOAL


def test_typing_pause_breakpoint_after_busy_stretch():
    steps = [("excel", "Book1 - Excel", 30, 0.2, 8), ("excel", "Book1 - Excel", 6, 5, 0)]
    _, signals = _run(steps)
    pauses = _breakpoints(signals, BreakpointKind.TYPING_PAUSE)
    assert len(pauses) == 1  # once per pause, not on every quiet sample
    assert pauses[0].at == T0 + timedelta(seconds=30)


def test_no_typing_pause_without_busy_stretch():
    steps = [("excel", "Book1 - Excel", 8, 0.2, 8), ("excel", "Book1 - Excel", 6, 5, 0)]
    _, signals = _run(steps)
    assert not _breakpoints(signals, BreakpointKind.TYPING_PAUSE)


def test_break_cycle_signals_and_break_time_is_not_drift():
    plan = _plan(study_minutes=1, break_minutes=1, break_style=BreakStyle.FIXED)

    def phase_assess(sample):
        if break_phase(plan, sample.at).on_break:
            return TrackAssessment(
                judgment=TrackJudgment.ON_BREAK, confidence=1, source=JudgmentSource.RULE
            )
        return _assess(sample)

    tracker = ThresholdDriftTracker(plan=plan)
    signals = []
    samples = scripted_samples(
        [("youtube", "cats - YouTube", 50), ("youtube", "cats - YouTube", 200)], start=T0
    )
    for sample in samples:
        signals.extend(tracker.update(sample, phase_assess(sample)))
    due = _kinds(signals, SignalKind.BREAK_DUE)
    over = _kinds(signals, SignalKind.BREAK_OVER)
    assert [s.at - T0 for s in due] == [timedelta(minutes=1), timedelta(minutes=3)]
    assert [s.at - T0 for s in over] == [timedelta(minutes=2), timedelta(minutes=4)]
    # 50 s of YouTube before the break, break clears it, 60 s after: never 90 s.
    assert not _kinds(signals, SignalKind.DRIFT_STARTED)
    assert tracker.totals.break_seconds == 120


def test_session_ending_fires_once():
    plan = _plan(duration=timedelta(minutes=4))
    _, signals = _run([("excel", "Book1 - Excel", 300)], plan=plan)
    ending = _kinds(signals, SignalKind.SESSION_ENDING)
    assert len(ending) == 1
    assert ending[0].at == T0 + timedelta(minutes=2)


def test_thresholds_are_configurable():
    thresholds = DriftThresholds(drift_after_seconds=20)
    _, signals = _run(
        [("excel", "Book1 - Excel", 4), ("youtube", "cats - YouTube", 30)], thresholds=thresholds
    )
    assert _kinds(signals, SignalKind.DRIFT_STARTED)[0].at == T0 + timedelta(seconds=24)


def test_low_confidence_off_goal_counts_as_unsure():
    tracker = ThresholdDriftTracker(plan=_plan())
    signals = []
    for sample in scripted_samples([("youtube", "cats", 120)], start=T0):
        weak = TrackAssessment(
            judgment=TrackJudgment.OFF_GOAL, confidence=0.3, source=JudgmentSource.MODEL
        )
        signals.extend(tracker.update(sample, weak))
    assert not _kinds(signals, SignalKind.DRIFT_STARTED)
    assert tracker.totals.unsure_seconds == 118


def test_sleep_gap_is_capped():
    tracker = ThresholdDriftTracker(plan=_plan())
    off = TrackAssessment(judgment=TrackJudgment.OFF_GOAL, confidence=1, source=JudgmentSource.RULE)
    a = ActivitySample(
        app="youtube", window_title="x", idle_seconds=0, input_events=3, is_switch=False, at=T0
    )
    b = ActivitySample(
        app="youtube",
        window_title="x",
        idle_seconds=0,
        input_events=3,
        is_switch=False,
        at=T0 + timedelta(hours=3),
    )
    tracker.update(a, off)
    assert not _kinds(tracker.update(b, off), SignalKind.DRIFT_STARTED)
    assert tracker.totals.off_goal_seconds == 10


def test_reset_clears_state_and_totals():
    tracker, _ = _run([("youtube", "cats - YouTube", 120)])
    assert tracker.drifting
    plan = _plan()
    tracker.reset(plan)
    assert not tracker.drifting
    assert tracker.plan is plan
    assert tracker.totals.drift_count == 0


def test_same_script_gives_same_signals():
    steps = [("excel", "a - Excel", 20), ("youtube", "b - YouTube", 150), ("excel", "a", 30)]
    assert _run(steps)[1] == _run(steps)[1]
