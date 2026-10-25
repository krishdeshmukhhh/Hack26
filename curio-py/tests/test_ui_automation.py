"""UIA point snapping: pure selection logic, async wrapper, config and manager wiring."""

from __future__ import annotations

import asyncio
import dataclasses
import time

import pytest

from curio import companion_manager, ui_automation
from curio.config import Config, ConfigError, LocalConfig
from curio.ui_automation import (
    Candidate,
    choose_snap,
    name_similarity,
    snap_point,
)
from tests.test_settle_and_early_flight import _streaming_manager
from tests.test_walkthrough import _ask, _manager, _settle, qt_app  # noqa: F401


def cand(name: str, left: int, top: int, right: int, bottom: int) -> Candidate:
    return Candidate(name, left, top, right, bottom, "Button")


# ---- similarity ----

def test_similarity_matches_label_inside_long_name() -> None:
    assert name_similarity("chrome icon", "Google Chrome - 1 running window pinned") >= 0.9
    assert name_similarity("start button", "Start") >= 0.9


def test_similarity_rejects_unrelated_and_empty() -> None:
    assert name_similarity("chrome icon", "PyCharm Community pinned") < 0.3
    assert name_similarity("", "Save") == 0.0
    assert name_similarity("save", "") == 0.0


# ---- selection ----

def test_snaps_to_matching_neighbor_within_radius() -> None:
    save, other = cand("Save", 200, 100, 240, 130), cand("Open", 100, 100, 140, 130)
    got = choose_snap(170, 115, "save button", [other, save])
    assert got is not None and got[0] is save


def test_name_mismatch_returns_none() -> None:
    assert choose_snap(170, 115, "save", [cand("Open", 160, 100, 200, 130)]) is None


def test_distance_gate() -> None:
    far = cand("Save", 500, 100, 540, 130)
    assert choose_snap(100, 115, "save", [far]) is None


def test_far_but_within_radius_needs_strong_match() -> None:
    c = cand("Save As", 200, 100, 240, 130)  # ~100 px away: > radius/2
    assert choose_snap(100, 115, "save as", [c]) is not None
    assert choose_snap(100, 115, "saves", [cand("Savings", 200, 100, 240, 130)]) is None


def test_inside_rect_accepts_looser_match() -> None:
    c = cand("Google Chrome", 100, 100, 150, 150)
    assert choose_snap(120, 120, "chrome browser", [c]) is not None
    assert choose_snap(120, 120, "totally different", [c]) is None


def test_prefers_tightest_enclosing_element() -> None:
    big = cand("Save", 0, 0, 600, 200)
    small = cand("Save", 100, 100, 140, 130)
    got = choose_snap(120, 115, "save", [big, small])
    assert got is not None and got[0] is small


def test_ignores_empty_rect_and_unnamed() -> None:
    items = [cand("Save", 10, 10, 10, 30), cand(" ", 0, 0, 50, 50)]
    assert choose_snap(10, 10, "save", items) is None


# ---- async wrapper ----

def _run(coro):
    return asyncio.run(coro)


def test_snap_point_returns_element_center() -> None:
    def collect(x, y, radius, deadline):
        return [cand("Save", 200, 100, 240, 130)]

    res = _run(snap_point(190, 115, "save", collect=collect))
    assert res is not None and (res.x, res.y) == (220, 115)


def test_large_element_keeps_model_coordinate_on_long_axis() -> None:
    def collect(x, y, radius, deadline):
        return [cand("Search", 0, 100, 1000, 130)]

    res = _run(snap_point(300, 90, "search", collect=collect))
    assert res is not None and (res.x, res.y) == (300, 115)


def test_collect_exception_returns_none() -> None:
    def collect(*a):
        raise RuntimeError("COM exploded")

    assert _run(snap_point(1, 1, "save", collect=collect)) is None


def test_timeout_returns_none_quickly_and_then_busy() -> None:
    def slow(*a):
        time.sleep(0.5)
        return [cand("Save", 0, 0, 10, 10)]

    async def go():
        start = time.monotonic()
        first = await snap_point(5, 5, "save", timeout_s=0.05, collect=slow)
        elapsed = time.monotonic() - start
        second = await snap_point(5, 5, "save", timeout_s=0.05, collect=slow)
        return first, elapsed, second

    first, elapsed, second = _run(go())
    assert first is None and second is None
    assert elapsed < 0.3
    time.sleep(0.6)  # let the abandoned job finish so later tests aren't "busy"


def test_queued_job_cancelled_on_timeout_releases_inflight() -> None:
    import threading

    gate = threading.Event()
    blocker = ui_automation._get_executor().submit(gate.wait, 5)
    ui_automation._inflight_add(1)  # as prewarm does
    blocker.add_done_callback(lambda _f: ui_automation._inflight_add(-1))

    def collect(*a):
        return [cand("Save", 0, 0, 10, 10)]

    async def go():
        busy = await snap_point(5, 5, "save", timeout_s=0.05, collect=collect)
        gate.set()
        blocker.result(timeout=2)
        time.sleep(0.05)
        return busy, await snap_point(5, 5, "save", timeout_s=1.0, collect=collect)

    busy, after = _run(go())
    assert busy is None
    assert ui_automation._inflight == 0
    assert after is not None


def test_queued_snap_timeout_does_not_leak_inflight() -> None:
    import threading

    gate = threading.Event()
    blocker = ui_automation._get_executor().submit(gate.wait, 5)

    def collect(*a):
        return [cand("Save", 0, 0, 10, 10)]

    async def go():
        first = await snap_point(5, 5, "save", timeout_s=0.05, collect=collect)
        gate.set()
        blocker.result(timeout=2)
        time.sleep(0.05)
        return first, await snap_point(5, 5, "save", timeout_s=1.0, collect=collect)

    first, after = _run(go())
    assert first is None and ui_automation._inflight == 0 and after is not None


def test_own_window_returns_none() -> None:
    def collect(*a):
        raise ui_automation._OwnWindow

    assert _run(snap_point(1, 1, "save", collect=collect)) is None


# ---- config ----

def test_point_snap_config_default_and_validation() -> None:
    assert LocalConfig.from_dict({}).point_snap is True
    assert LocalConfig.from_dict({"point_snap": False}).point_snap is False
    with pytest.raises(ConfigError):
        LocalConfig.from_dict({"point_snap": "yes"})


# ---- manager wiring ----

def _enable_snap(manager, fn) -> None:
    local = LocalConfig.from_dict({"point_coords": "pixel"})
    manager._config = dataclasses.replace(manager._config, local=local)
    assert manager._config.point_snap
    manager._snap_fn = fn


def test_end_path_flies_to_snapped_coords(qt_app, monkeypatch) -> None:  # noqa: F811
    manager, parts = _manager(["see it? [POINT:40,120:save button]"], monkeypatch)
    seen = []

    async def fake_snap(x, y, label):
        seen.append((x, y, label))
        return ui_automation.SnapResult(11, 22, "Save", 1.0)

    _enable_snap(manager, fake_snap)

    async def run():
        _ask(manager, "what is that")
        await _settle(manager)

    asyncio.run(run())
    assert len(parts["overlays"].flights) == 1
    assert parts["overlays"].flights[0][:2] == (11, 22)
    assert seen and seen[0][2] == "save button"


def test_early_path_flies_once_to_snapped_coords(qt_app, monkeypatch) -> None:  # noqa: F811
    reply = "click new. [POINT:40,120:new button] [STEP:1/2] [CONCEPTS:folders]"
    manager, parts = _streaming_manager(reply, 3, monkeypatch)

    async def fake_snap(x, y, label):
        await asyncio.sleep(0.01)
        return ui_automation.SnapResult(7, 8, "New", 1.0)

    _enable_snap(manager, fake_snap)

    async def run():
        _ask(manager, "how")
        await _settle(manager)

    asyncio.run(run())
    flights = parts["overlays"].flights
    assert len(flights) == 1 and flights[0][:2] == (7, 8)
    assert flights[0][2:] == (True, (1, 2))


@pytest.mark.parametrize("mode", ["none", "raise", "disabled"])
def test_unchanged_when_snap_fails_or_disabled(qt_app, monkeypatch, mode) -> None:  # noqa: F811
    manager, base = _manager(["see it? [POINT:40,120:save]"], monkeypatch)
    baseline_manager, baseline = _manager(["see it? [POINT:40,120:save]"], monkeypatch)

    async def fake_snap(x, y, label):
        if mode == "raise":
            raise RuntimeError("boom")
        return None

    if mode != "disabled":
        _enable_snap(manager, fake_snap)
    else:
        called = []
        manager._snap_fn = lambda *a: called.append(a)

    async def run(m):
        _ask(m, "what")
        await _settle(m)

    asyncio.run(run(manager))
    asyncio.run(run(baseline_manager))
    assert base["overlays"].flights == baseline["overlays"].flights
    assert len(base["overlays"].flights) == 1


def test_config_dataclass_replace_sanity() -> None:
    assert dataclasses.is_dataclass(Config) and companion_manager.snap_point is snap_point
