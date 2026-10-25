from datetime import UTC, datetime, time, timedelta

import pytest

from curio.focus_contract import (
    ActivitySample,
    BreakpointKind,
    BreakStyle,
    FocusPlan,
    FocusSignal,
    IfThenPlan,
    InterventionKind,
    InterventionResponse,
    ResumeNote,
    SignalKind,
)
from curio.focus_policy import (
    NOT_A_DISTRACTION,
    AdaptiveFocusPolicy,
    PolicySettings,
    QuietHours,
)
from curio.focus_policy.wording import NEW_STYLE_NOTICE, controlling_phrases

T0 = datetime(2026, 10, 24, 14, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self, start: datetime = T0) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def make_plan(**overrides) -> FocusPlan:
    values = {
        "goal": "the excel assignment",
        "duration": timedelta(minutes=50),
        "started_at": T0,
        "if_then": (
            IfThenPlan(cue="i open youtube", response="i'll say back to it", cue_apps=("youtube",)),
        ),
    }
    values.update(overrides)
    return FocusPlan(**values)


def sample(clock: FakeClock, app: str = "youtube", title: str = ""):
    return ActivitySample(
        app=app,
        window_title=title or f"{app} - home",
        idle_seconds=0,
        input_events=3,
        is_switch=True,
        at=clock(),
    )


def signal(
    clock: FakeClock, kind: SignalKind, app: str = "youtube", title: str = "", **extra
) -> FocusSignal:
    if kind is SignalKind.BREAKPOINT:
        extra.setdefault("breakpoint", BreakpointKind.APP_SWITCH)
    return FocusSignal(kind=kind, sample=sample(clock, app, title), at=clock(), **extra)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def new_policy(clock: FakeClock, **kwargs) -> AdaptiveFocusPolicy:
    return AdaptiveFocusPolicy(clock=clock, **kwargs)


def start_drift(policy, clock, plan, app="youtube", title=""):
    drift = signal(clock, SignalKind.DRIFT_STARTED, app, title, drift_seconds=45)
    return policy.decide(drift, plan)


# --- deciding whether to step in ------------------------------------------------


def test_drift_starts_with_a_silent_ambient_cue(clock):
    policy, plan = new_policy(clock), make_plan()
    cue = start_drift(policy, clock, plan)
    assert cue.kind is InterventionKind.AMBIENT_CUE
    assert cue.message == ""
    assert NOT_A_DISTRACTION in cue.choices
    assert cue.rationale == "C"
    assert policy.drifting


def test_no_spoken_check_in_mid_thought(clock):
    policy, plan = new_policy(clock), make_plan()
    start_drift(policy, clock, plan)
    for _ in range(5):  # still drifting, no breakpoint, inside the cap
        clock.advance(30)
        assert policy.decide(signal(clock, SignalKind.DRIFT_CONTINUING), plan) is None


def test_check_in_at_the_breakpoint_after_a_drift(clock):
    policy, plan = new_policy(clock), make_plan()
    start_drift(policy, clock, plan)
    clock.advance(70)
    check_in = policy.decide(signal(clock, SignalKind.BREAKPOINT), plan)
    assert check_in.kind is InterventionKind.CHECK_IN
    assert "the excel assignment" in check_in.message
    assert check_in.choices == ("back to it", "take a break", NOT_A_DISTRACTION)


def test_breakpoint_before_the_spacing_waits(clock):
    policy, plan = new_policy(clock), make_plan()
    start_drift(policy, clock, plan)
    clock.advance(30)
    assert policy.decide(signal(clock, SignalKind.BREAKPOINT), plan) is None


def test_check_in_allowed_without_breakpoint_after_the_cap(clock):
    policy, plan = new_policy(clock), make_plan()
    start_drift(policy, clock, plan)
    clock.advance(60 + 119)
    assert policy.decide(signal(clock, SignalKind.DRIFT_CONTINUING), plan) is None
    clock.advance(2)
    check_in = policy.decide(signal(clock, SignalKind.DRIFT_CONTINUING), plan)
    assert check_in.kind is InterventionKind.CHECK_IN


def run_ladder(policy, clock, plan, app="youtube", title="", step=61):
    kinds = [start_drift(policy, clock, plan, app, title).kind]
    for _ in range(4):
        clock.advance(step)
        intervention = policy.decide(signal(clock, SignalKind.BREAKPOINT, app, title), plan)
        if intervention is not None:
            kinds.append(intervention.kind)
    return kinds


def test_escalation_order_with_matching_if_then_plan(clock):
    policy, plan = new_policy(clock), make_plan()
    assert run_ladder(policy, clock, plan) == [
        InterventionKind.AMBIENT_CUE,
        InterventionKind.CHECK_IN,
        InterventionKind.PLAN_REMINDER,
    ]


def test_plan_reminder_uses_the_learners_own_words(clock):
    policy, plan = new_policy(clock), make_plan()
    start_drift(policy, clock, plan)
    clock.advance(61)
    policy.decide(signal(clock, SignalKind.BREAKPOINT), plan)
    clock.advance(61)
    reminder = policy.decide(signal(clock, SignalKind.BREAKPOINT), plan)
    assert "i open youtube" in reminder.message
    assert "i'll say back to it" in reminder.message
    assert reminder.rationale == "A"
    assert NOT_A_DISTRACTION in reminder.choices


def test_no_plan_reminder_without_an_if_then_for_this_app(clock):
    policy, plan = new_policy(clock), make_plan()
    assert run_ladder(policy, clock, plan, app="reddit") == [
        InterventionKind.AMBIENT_CUE,
        InterventionKind.CHECK_IN,
    ]


def test_if_then_matches_window_title_substring(clock):
    policy = new_policy(clock)
    plan = make_plan(if_then=(IfThenPlan(cue="cats", response="close it", cue_apps=("cats",)),))
    kinds = run_ladder(policy, clock, plan, app="chrome", title="Funny Cats - Chrome")
    assert kinds[-1] is InterventionKind.PLAN_REMINDER


def test_hourly_limit_on_spoken_check_ins(clock):
    policy, plan = new_policy(clock), make_plan()
    first = run_ladder(policy, clock, plan)
    policy.decide(signal(clock, SignalKind.RETURNED, "excel"), plan)
    clock.advance(60)
    second = run_ladder(policy, clock, plan)
    spoken = [k for k in first + second if k is not InterventionKind.AMBIENT_CUE]
    assert len(spoken) == 3
    assert second == [InterventionKind.AMBIENT_CUE, InterventionKind.CHECK_IN]
    policy.decide(signal(clock, SignalKind.RETURNED, "excel"), plan)
    clock.advance(3600)
    assert InterventionKind.CHECK_IN in run_ladder(policy, clock, plan)


def test_snooze_silences_for_n_minutes(clock):
    policy = new_policy(clock, settings=PolicySettings(snooze=timedelta(minutes=10)))
    plan = make_plan()
    cue = start_drift(policy, clock, plan)
    policy.record_response(cue, InterventionResponse.SNOOZED)
    clock.advance(9 * 60)
    assert policy.decide(signal(clock, SignalKind.BREAKPOINT), plan) is None
    clock.advance(61)
    check_in = policy.decide(signal(clock, SignalKind.BREAKPOINT), plan)
    assert check_in.kind is InterventionKind.CHECK_IN


def test_quiet_hours_allow_only_silent_cues():
    clock = FakeClock(datetime(2026, 10, 24, 23, 0, tzinfo=UTC))
    quiet = QuietHours(start=time(22, 0), end=time(7, 0), tz=UTC)
    policy = new_policy(clock, settings=PolicySettings(quiet_hours=(quiet,)))
    plan = make_plan(started_at=clock())
    assert start_drift(policy, clock, plan).kind is InterventionKind.AMBIENT_CUE
    clock.advance(200)
    assert policy.decide(signal(clock, SignalKind.BREAKPOINT), plan) is None
    assert policy.decide(signal(clock, SignalKind.BREAK_DUE), plan) is None


def test_quiet_hours_wrap_past_midnight():
    quiet = QuietHours(start=time(22, 0), end=time(7, 0), tz=UTC)
    assert quiet.contains(datetime(2026, 10, 24, 23, 30, tzinfo=UTC))
    assert quiet.contains(datetime(2026, 10, 25, 6, 59, tzinfo=UTC))
    assert not quiet.contains(datetime(2026, 10, 25, 7, 0, tzinfo=UTC))
    daytime = QuietHours(start=time(12, 0), end=time(13, 0), tz=UTC)
    assert daytime.contains(datetime(2026, 10, 24, 12, 30, tzinfo=UTC))
    assert not daytime.contains(datetime(2026, 10, 24, 13, 30, tzinfo=UTC))


def test_strict_mode_shortens_spacing_and_never_blocks(clock):
    plan = make_plan(strict=True)
    policy = new_policy(clock)
    start_drift(policy, clock, plan)
    clock.advance(31)
    check_in = policy.decide(signal(clock, SignalKind.BREAKPOINT), plan)
    assert check_in.kind is InterventionKind.CHECK_IN
    relaxed_clock = FakeClock()
    relaxed = new_policy(relaxed_clock)
    start_drift(relaxed, relaxed_clock, make_plan())
    relaxed_clock.advance(31)
    assert relaxed.decide(signal(relaxed_clock, SignalKind.BREAKPOINT), make_plan()) is None
    # strict mode still only offers choices
    assert NOT_A_DISTRACTION in check_in.choices
    assert not controlling_phrases(check_in.message)
    assert not any("block" in name for name in dir(policy))


def test_interaction_frequency_scales_spacing_and_limit(clock):
    eager = new_policy(clock, interaction_frequency=1.0)
    plan = make_plan()
    start_drift(eager, clock, plan)
    clock.advance(41)  # 60s / 1.5
    assert (
        eager.decide(signal(clock, SignalKind.BREAKPOINT), plan).kind is InterventionKind.CHECK_IN
    )
    assert eager._hourly_limit() == 4

    shy_clock = FakeClock()
    level = {"value": 0.0}
    shy = new_policy(shy_clock, interaction_frequency=lambda: level["value"])
    start_drift(shy, shy_clock, plan)
    shy_clock.advance(100)  # 60s / 0.5 = 120s
    assert shy.decide(signal(shy_clock, SignalKind.BREAKPOINT), plan) is None
    assert shy._hourly_limit() == 2
    level["value"] = 0.5  # adaptive values can change mid-session
    assert shy._hourly_limit() == 3


# --- learning from responses ------------------------------------------------------


def test_false_alarm_ends_the_episode_and_slows_that_app(clock):
    policy, plan = new_policy(clock), make_plan()
    start_drift(policy, clock, plan)
    clock.advance(61)
    check_in = policy.decide(signal(clock, SignalKind.BREAKPOINT), plan)
    policy.record_response(check_in, InterventionResponse.FALSE_ALARM)
    clock.advance(61)
    assert policy.decide(signal(clock, SignalKind.BREAKPOINT), plan) is None  # no reminder
    assert policy.decide(signal(clock, SignalKind.RETURNED, "excel"), plan) is None  # no resume

    clock.advance(600)
    assert start_drift(policy, clock, plan) is None  # ambient cue delayed by 60s
    clock.advance(61)
    cue = policy.decide(signal(clock, SignalKind.DRIFT_CONTINUING), plan)
    assert cue.kind is InterventionKind.AMBIENT_CUE
    clock.advance(61)
    assert policy.decide(signal(clock, SignalKind.BREAKPOINT), plan) is None  # spacing doubled
    clock.advance(60)
    assert (
        policy.decide(signal(clock, SignalKind.BREAKPOINT), plan).kind is InterventionKind.CHECK_IN
    )


def test_false_alarm_does_not_slow_other_apps(clock):
    policy, plan = new_policy(clock), make_plan()
    cue = start_drift(policy, clock, plan, app="youtube")
    policy.record_response(cue, InterventionResponse.FALSE_ALARM)
    policy.decide(signal(clock, SignalKind.RETURNED, "excel"), plan)
    clock.advance(60)
    assert start_drift(policy, clock, plan, app="reddit").kind is InterventionKind.AMBIENT_CUE


def test_repeated_ignored_check_ins_back_off(clock):
    policy, plan = new_policy(clock), make_plan()
    gaps = []
    for _ in range(3):
        start_drift(policy, clock, plan, app="reddit")
        waited = 0
        check_in = None
        while check_in is None:
            clock.advance(10)
            waited += 10
            check_in = policy.decide(signal(clock, SignalKind.BREAKPOINT, "reddit"), plan)
        gaps.append(waited)
        policy.record_response(check_in, InterventionResponse.IGNORED)
        policy.decide(signal(clock, SignalKind.RETURNED, "excel"), plan)
        clock.advance(3600)  # clear the hourly window
    assert gaps == [60, 120, 240]


def test_a_response_resets_the_ignored_backoff(clock):
    policy, plan = new_policy(clock), make_plan()
    start_drift(policy, clock, plan, app="reddit")
    clock.advance(61)
    check_in = policy.decide(signal(clock, SignalKind.BREAKPOINT, "reddit"), plan)
    policy.record_response(check_in, InterventionResponse.IGNORED)
    policy.record_response(check_in, InterventionResponse.ACCEPTED)
    assert policy._spacing(plan, "reddit") == timedelta(seconds=60)


def test_dismissing_a_check_in_stops_escalation(clock):
    policy, plan = new_policy(clock), make_plan()
    start_drift(policy, clock, plan)
    clock.advance(61)
    check_in = policy.decide(signal(clock, SignalKind.BREAKPOINT), plan)
    policy.record_response(check_in, InterventionResponse.DISMISSED)
    clock.advance(300)
    assert policy.decide(signal(clock, SignalKind.BREAKPOINT), plan) is None


# --- resume notes -----------------------------------------------------------------


def test_resume_note_from_context_is_read_back_on_return(clock):
    policy, plan = new_policy(clock), make_plan()
    policy.start_session(plan)
    policy.set_context(where="step three", next_action="add the row fields")
    clock.advance(30)
    start_drift(policy, clock, plan)
    assert policy.resume_note().where == "step three"
    clock.advance(30)
    resume = policy.decide(signal(clock, SignalKind.RETURNED, "excel"), plan)
    assert resume.kind is InterventionKind.RESUME
    assert "you were on step three, about to add the row fields." in resume.message
    assert resume.rationale == "D"
    assert NOT_A_DISTRACTION in resume.choices


def test_resume_note_falls_back_to_the_plan(clock):
    policy, plan = new_policy(clock), make_plan()
    start_drift(policy, clock, plan)
    note = policy.resume_note()
    assert (note.where, note.source) == ("the excel assignment", "plan")
    resume = policy.decide(signal(clock, SignalKind.RETURNED, "excel"), plan)
    assert "you were working on the excel assignment" in resume.message


def test_spoken_note_newer_than_context_is_kept(clock):
    policy, plan = new_policy(clock), make_plan()
    policy.set_context(where="step two", next_action="pick a chart")
    clock.advance(5)
    spoken = ResumeNote(where="the summary tab", next_action="fix the totals", at=clock())
    policy.set_resume_note(spoken)
    clock.advance(5)
    start_drift(policy, clock, plan)
    assert policy.resume_note() is spoken


def test_only_the_newest_note_is_kept(clock):
    policy, plan = new_policy(clock), make_plan()
    policy.set_resume_note(ResumeNote(where="a", next_action="b", at=clock()))
    clock.advance(1)
    policy.set_context(where="step four", next_action="sort the column")
    clock.advance(1)
    start_drift(policy, clock, plan)
    assert policy.resume_note().where == "step four"


def test_no_resume_without_a_drift(clock):
    policy, plan = new_policy(clock), make_plan()
    policy.set_resume_note(ResumeNote(where="a", next_action="b", at=clock()))
    assert policy.decide(signal(clock, SignalKind.RETURNED, "excel"), plan) is None


# --- breaks -----------------------------------------------------------------------


def test_fixed_break_cycle(clock):
    policy, plan = new_policy(clock), make_plan()
    policy.start_session(plan)
    policy.set_context(where="step five", next_action="label the axes")
    clock.advance(25 * 60)
    offer = policy.decide(signal(clock, SignalKind.BREAK_DUE, "excel"), plan)
    assert offer.kind is InterventionKind.BREAK_START
    assert offer.choices == ("start break", "keep going")
    assert offer.rationale == "E"
    policy.record_response(offer, InterventionResponse.ACCEPTED)
    assert policy.on_break
    assert start_drift(policy, clock, plan) is None  # breaks aren't drifts
    clock.advance(5 * 60)
    end = policy.decide(signal(clock, SignalKind.BREAK_OVER, "excel"), plan)
    assert end.kind is InterventionKind.BREAK_END
    assert "you were on step five, about to label the axes." in end.message
    assert not policy.on_break


def test_keep_going_is_respected(clock):
    policy, plan = new_policy(clock), make_plan()
    clock.advance(25 * 60)
    offer = policy.decide(signal(clock, SignalKind.BREAK_DUE, "excel"), plan)
    policy.record_response(offer, InterventionResponse.DISMISSED)
    assert policy.decide(signal(clock, SignalKind.BREAK_OVER, "excel"), plan) is None
    clock.advance(5 * 60)
    assert policy.decide(signal(clock, SignalKind.BREAK_DUE, "excel"), plan) is None
    clock.advance(15 * 60)
    assert policy.decide(signal(clock, SignalKind.BREAK_DUE, "excel"), plan) is not None


def test_self_paced_breaks_only_after_a_long_stretch(clock):
    plan = make_plan(break_style=BreakStyle.SELF_PACED, duration=timedelta(hours=3))
    policy = new_policy(clock)
    policy.start_session(plan)
    clock.advance(20 * 60)
    assert policy.decide(signal(clock, SignalKind.BREAK_DUE, "excel"), plan) is None
    assert policy.decide(signal(clock, SignalKind.BREAKPOINT, "excel"), plan) is None
    clock.advance(31 * 60)
    offer = policy.decide(signal(clock, SignalKind.BREAKPOINT, "excel"), plan)
    assert offer.kind is InterventionKind.BREAK_START
    assert "stretch" in offer.message
    policy.record_response(offer, InterventionResponse.ACCEPTED)
    clock.advance(5 * 60)
    end = policy.decide(signal(clock, SignalKind.BREAK_OVER, "excel"), plan)
    assert end.kind is InterventionKind.BREAK_END
    clock.advance(10 * 60)
    assert policy.decide(signal(clock, SignalKind.BREAKPOINT, "excel"), plan) is None
    clock.advance(41 * 60)
    assert policy.decide(signal(clock, SignalKind.BREAK_DUE, "excel"), plan) is not None


def test_no_break_prompts_when_breaks_are_off(clock):
    policy, plan = new_policy(clock), make_plan(break_style=BreakStyle.NONE)
    clock.advance(60 * 60)
    assert policy.decide(signal(clock, SignalKind.BREAK_DUE, "excel"), plan) is None


# --- metacognitive prompts --------------------------------------------------------


def test_metacognitive_timing(clock):
    policy, plan = new_policy(clock), make_plan()
    start = policy.start_session(plan)
    assert start.kind is InterventionKind.METACOGNITIVE
    assert "first" in start.message and "the excel assignment" in start.message
    assert start.rationale == "F"
    clock.advance(10 * 60)
    assert policy.decide(signal(clock, SignalKind.BREAKPOINT, "excel"), plan) is None
    clock.advance(15 * 60)
    halfway = policy.decide(signal(clock, SignalKind.BREAKPOINT, "excel"), plan)
    assert halfway.kind is InterventionKind.METACOGNITIVE
    clock.advance(60)
    assert policy.decide(signal(clock, SignalKind.BREAKPOINT, "excel"), plan) is None  # once
    clock.advance(24 * 60)
    ending = policy.decide(signal(clock, SignalKind.SESSION_ENDING, "excel"), plan)
    assert ending.kind is InterventionKind.METACOGNITIVE
    reflection = policy.reflection_prompt(plan)
    assert reflection.kind is InterventionKind.REFLECTION
    assert "got in the way" in reflection.message


def test_no_metacognitive_prompts_during_a_drift_or_break(clock):
    policy, plan = new_policy(clock), make_plan()
    policy.start_session(plan)
    clock.advance(26 * 60)
    start_drift(policy, clock, plan)
    clock.advance(5)
    assert policy.decide(signal(clock, SignalKind.SESSION_ENDING), plan) is None
    policy.decide(signal(clock, SignalKind.RETURNED, "excel"), plan)
    policy.begin_break()
    halfway = policy.decide(signal(clock, SignalKind.BREAKPOINT, "excel"), plan)
    assert halfway is None
    assert policy.decide(signal(clock, SignalKind.SESSION_ENDING, "excel"), plan) is None


# --- wording rotation -------------------------------------------------------------


def check_in_messages(clock, policy, count):
    plan = make_plan(if_then=())
    messages = []
    for _ in range(count):
        start_drift(policy, clock, plan, app="reddit")
        clock.advance(61)
        messages.append(policy.decide(signal(clock, SignalKind.BREAKPOINT, "reddit"), plan).message)
        policy.decide(signal(clock, SignalKind.RETURNED, "excel"), plan)
        clock.advance(3600)
    return messages


def test_check_ins_rotate_with_a_one_time_new_style_notice(clock):
    messages = check_in_messages(clock, new_policy(clock), 4)
    assert not messages[0].startswith(NEW_STYLE_NOTICE)
    assert messages[1].startswith(NEW_STYLE_NOTICE)
    assert messages[2].startswith(NEW_STYLE_NOTICE)
    assert not messages[3].startswith(NEW_STYLE_NOTICE)  # back to the first variant
    assert len({m.removeprefix(NEW_STYLE_NOTICE) for m in messages[:3]}) == 3
    assert messages[3] == messages[0]


def test_seen_variants_carry_over_so_notices_stay_one_time(clock):
    first = new_policy(clock)
    check_in_messages(clock, first, 3)
    second = new_policy(clock, seen_variants=first.seen_variants)
    assert not any(m.startswith(NEW_STYLE_NOTICE) for m in check_in_messages(clock, second, 3))


def test_every_intervention_has_a_rationale_and_drift_ones_a_way_out(clock):
    policy, plan = new_policy(clock), make_plan()
    seen = [policy.start_session(plan)]
    policy.set_context(where="step one", next_action="open the data")
    for _ in range(2):
        seen.append(start_drift(policy, clock, plan))
        for _ in range(2):
            clock.advance(61)
            seen.append(policy.decide(signal(clock, SignalKind.BREAKPOINT), plan))
        seen.append(policy.decide(signal(clock, SignalKind.RETURNED, "excel"), plan))
        clock.advance(25 * 60)
    seen.append(policy.decide(signal(clock, SignalKind.BREAK_DUE, "excel"), plan))
    seen.append(policy.reflection_prompt(plan))
    seen = [i for i in seen if i is not None]
    assert {i.kind for i in seen} >= {
        InterventionKind.AMBIENT_CUE,
        InterventionKind.CHECK_IN,
        InterventionKind.PLAN_REMINDER,
        InterventionKind.RESUME,
        InterventionKind.METACOGNITIVE,
    }
    for intervention in seen:
        assert intervention.rationale in set("ABCDEFGH")
        assert not controlling_phrases(intervention.message.replace("i'll say back to it", ""))
        if intervention.kind in {
            InterventionKind.AMBIENT_CUE,
            InterventionKind.CHECK_IN,
            InterventionKind.PLAN_REMINDER,
            InterventionKind.RESUME,
        }:
            assert NOT_A_DISTRACTION in intervention.choices


def test_new_plan_resets_session_state(clock):
    policy, plan = new_policy(clock), make_plan()
    start_drift(policy, clock, plan)
    other = make_plan(goal="reading chapter four")
    assert policy.decide(signal(clock, SignalKind.RETURNED, "excel"), other) is None
    assert not policy.drifting
