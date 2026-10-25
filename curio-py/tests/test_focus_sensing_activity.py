import inspect
import sys
from datetime import UTC, datetime, timedelta

import pytest

from curio.focus_contract import ActivitySample
from curio.focus_sensing import (
    FakeActivitySource,
    RawActivity,
    WindowsActivitySource,
    activity,
    scripted_samples,
)
from curio.focus_sensing.activity import probe_windows, resolve_app

T0 = datetime(2026, 10, 24, 14, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=2)
        return self.now


class ScriptedProbe:
    def __init__(self, raws):
        self.raws = list(raws)

    def __call__(self) -> RawActivity:
        return self.raws.pop(0)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (RawActivity(title="Book1 - Excel", exe_path=r"C:\Office\EXCEL.EXE"), "excel"),
        (RawActivity(title="Doc - Word", exe_path=r"C:\Office\WINWORD.EXE"), "word"),
        (RawActivity(title="New Tab", exe_path=r"C:\Chrome\chrome.exe"), "google chrome"),
        (RawActivity(title="x - Google Chrome"), "google chrome"),
        (RawActivity(title="Calculator", exe_path=r"C:\W\ApplicationFrameHost.exe"), "calculator"),
        (RawActivity(title="anything", exe_path=r"C:\py\python.exe", own_window=True), "curio"),
        (RawActivity(), ""),
    ],
)
def test_resolve_app_prefers_exe_and_matches_title_keys(raw, expected):
    assert resolve_app(raw) == expected


def test_poll_builds_samples_with_switches_and_input_counts():
    raws = [
        RawActivity(title="Book1 - Excel", exe_path="EXCEL.EXE", window_id=1, last_input_tick=100),
        RawActivity(title="Book1* - Excel", exe_path="EXCEL.EXE", window_id=1, last_input_tick=150),
        RawActivity(
            title="a - YouTube - Google Chrome",
            exe_path="chrome.exe",
            window_id=2,
            idle_seconds=1.5,
            last_input_tick=150,
        ),
        RawActivity(
            title="b - Reddit - Google Chrome",
            exe_path="chrome.exe",
            window_id=2,
            idle_seconds=3,
            last_input_tick=150,
        ),
    ]
    ticks = iter([100, 110, 120, 130, 150, 150, 150, 150, 150, 150])
    source = WindowsActivitySource(
        clock=Clock(), probe=ScriptedProbe(raws), input_tick=lambda: next(ticks)
    )
    seen: list[ActivitySample] = []
    unsubscribe = source.subscribe(seen.append)

    source.poll_input()  # baseline tick 100
    first = source.poll_once()  # tick 110: one change since baseline
    for _ in range(2):
        source.poll_input()  # 120, 130
    second = source.poll_once()  # 150
    third = source.poll_once()
    unsubscribe()
    fourth = source.poll_once()

    assert seen == [first, second, third]
    assert (first.app, first.is_switch, first.input_events) == ("excel", False, 1)
    # Title edits inside the same window are not a switch...
    assert (second.is_switch, second.input_events) == (False, 3)
    assert (third.app, third.is_switch, third.input_events, third.idle_seconds) == (
        "google chrome",
        True,
        0,
        1.5,
    )
    # ...but a browser tab change is.
    assert fourth.is_switch
    assert [s.at for s in (first, second, third, fourth)] == [
        T0 + timedelta(seconds=2 * i) for i in range(1, 5)
    ]


def test_without_input_timer_counts_one_event_per_active_interval():
    raws = [RawActivity(title="a - Excel", last_input_tick=t) for t in (5, 9, 9)]
    source = WindowsActivitySource(input_poll_ms=0, clock=Clock(), probe=ScriptedProbe(raws))
    assert [source.poll_once().input_events for _ in range(3)] == [0, 1, 0]


def test_start_stop_is_idempotent_and_failing_subscribers_are_isolated():
    source = WindowsActivitySource(
        clock=Clock(), probe=lambda: RawActivity(title="a - Excel"), input_tick=lambda: 0
    )
    seen = []

    def broken(_sample):
        raise RuntimeError("boom")

    source.subscribe(broken)
    source.subscribe(seen.append)
    source.start()
    source.start()
    assert source.running
    source.poll_once()
    source.stop()
    assert not source.running
    assert len(seen) == 1


def test_probe_never_crashes():
    raw = probe_windows()
    assert isinstance(raw, RawActivity)
    if sys.platform != "win32":
        assert raw == RawActivity()


def test_default_source_runs_anywhere():
    sample = WindowsActivitySource(clock=Clock()).poll_once()
    assert isinstance(sample, ActivitySample)


def test_no_keyboard_hooks_or_key_reading():
    text = inspect.getsource(activity)
    for forbidden in ("pynput", "SetWindowsHookEx", "GetAsyncKeyState", "GetKeyState", "ToUnicode"):
        assert forbidden not in text


def test_fake_source_replays_script():
    samples = scripted_samples([("excel", "a - Excel", 4), ("youtube", "b - YouTube", 2)], start=T0)
    source = FakeActivitySource(samples)
    seen = []
    source.subscribe(seen.append)
    assert source.step() is None  # not started
    source.start()
    assert source.step() == samples[0]
    assert source.play() == samples[1:]
    assert seen == samples
    assert source.remaining == 0
    assert source.step() is None
    assert not source.running


def test_fake_source_loops_and_accepts_pushes():
    one = scripted_samples([("excel", "a - Excel", 2)], start=T0)[0]
    source = FakeActivitySource([one], loop=True)
    source.start()
    assert source.step() == one
    assert source.step() == one
    extra = scripted_samples([("docs", "MDN", 2)], start=T0)[0]
    source.push(extra)
    assert source.step() == extra


def test_scripted_samples_shape():
    samples = scripted_samples(
        [("excel", "a - Excel", 4), ("excel", "a - Excel", 2, 70, 0), ("docs", "MDN", 2)],
        start=T0,
    )
    assert [s.at - T0 for s in samples] == [timedelta(seconds=2 * i) for i in range(4)]
    assert [s.is_switch for s in samples] == [False, False, False, True]
    assert (samples[2].idle_seconds, samples[2].input_events) == (70, 0)
    assert samples[0].input_events == 3
