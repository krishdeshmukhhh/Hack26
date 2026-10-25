"""Adaptive step settle, early POINT flight and LLM warm-up."""

from __future__ import annotations

import asyncio

import pytest

from curio import companion_manager
from curio.point_parser import find_point_tag
from curio.screen_capture import ProbeFrame
from curio.settle import SETTLE_MAX_SECONDS, SETTLE_MIN_SECONDS, wait_for_settle
from curio.state import VoiceState
from tests.test_walkthrough import FakeLLM, _ask, _manager, _settle, qt_app  # noqa: F401


class FakeFrame:
    def __init__(self, value: int) -> None:
        self.value = value

    def differs_from(self, other: FakeFrame) -> bool:
        return self.value != other.value


class FakeTime:
    """A fake clock whose sleep advances time; frames follow a time -> value script."""

    def __init__(self, script) -> None:
        self.now = 0.0
        self.script = script

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds

    async def grab(self) -> FakeFrame:
        return FakeFrame(self.script(self.now))


def test_settle_continues_early_after_change_then_stable() -> None:
    t = FakeTime(lambda now: 0 if now < 0.2 else (1 if now < 0.3 else 2))
    waited = asyncio.run(wait_for_settle(t.grab, clock=t.clock, sleep=t.sleep))
    assert SETTLE_MIN_SECONDS <= waited < SETTLE_MAX_SECONDS
    assert waited < 0.6


def test_settle_waits_max_when_nothing_changes() -> None:
    t = FakeTime(lambda now: 0)
    waited = asyncio.run(wait_for_settle(t.grab, clock=t.clock, sleep=t.sleep))
    assert waited == pytest.approx(SETTLE_MAX_SECONDS)


def test_settle_respects_max_when_screen_keeps_changing() -> None:
    t = FakeTime(lambda now: int(now * 100))
    waited = asyncio.run(wait_for_settle(t.grab, clock=t.clock, sleep=t.sleep))
    assert waited == pytest.approx(SETTLE_MAX_SECONDS)


def test_settle_falls_back_to_max_when_grab_fails() -> None:
    t = FakeTime(lambda now: 0)

    async def broken():
        raise OSError("no display")

    waited = asyncio.run(wait_for_settle(broken, clock=t.clock, sleep=t.sleep))
    assert waited == pytest.approx(SETTLE_MAX_SECONDS)


def test_settle_cancellation_propagates() -> None:
    async def run() -> bool:
        async def grab():
            return FakeFrame(0)

        task = asyncio.ensure_future(wait_for_settle(grab))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return True
        return False

    assert asyncio.run(run())


def test_probe_frame_ignores_masked_area() -> None:
    w, h = 10, 10
    base = bytes([0] * (w * h))
    changed = bytearray(base)
    for y in range(2, 5):
        for x in range(2, 5):
            changed[y * w + x] = 255
    mask = (0, 0, 6, 6)
    masked_a = ProbeFrame(w, h, base, mask)
    assert masked_a.differs_from(ProbeFrame(w, h, bytes(changed), mask)) is False
    assert ProbeFrame(w, h, base).differs_from(ProbeFrame(w, h, bytes(changed))) is True


def test_manager_settle_uses_adaptive_wait(qt_app, monkeypatch) -> None:  # noqa: F811
    replies = ["a. [POINT:40,120:new] [STEP:1/2]", "done. [POINT:none]"]
    manager, parts = _manager(replies, monkeypatch)
    monkeypatch.setattr(companion_manager, "WALKTHROUGH_SETTLE_SECONDS", 0.8)
    monkeypatch.setattr(companion_manager, "cursor_position", lambda: (0, 0))
    seen = []

    async def fake_wait(grab, *, max_seconds):
        seen.append(max_seconds)
        return 0.31

    monkeypatch.setattr(companion_manager, "wait_for_settle", fake_wait)

    async def run() -> None:
        _ask(manager, "how do i make a folder")
        await _settle(manager)
        parts["clicks"].clicked.emit()
        await _settle(manager)

    asyncio.run(run())
    assert seen == [0.8]
    assert manager._state == VoiceState.IDLE


class StreamingLLM(FakeLLM):
    """Emits the reply in fixed-size deltas, noting when the flight happened."""

    def __init__(self, replies, size, overlays) -> None:
        super().__init__(replies)
        self.size = size
        self.overlays = overlays
        self.deltas_at_flight: list[int] = []
        self.total_deltas = 0

    async def send(self, messages, system, model, max_tokens=1024) -> str:
        text = self.replies.pop(0)
        sent = 0
        for i in range(0, len(text), self.size):
            before = len(self.overlays.flights)
            self.delta.emit(text[i:i + self.size])
            sent += 1
            if len(self.overlays.flights) > before:
                self.deltas_at_flight.append(sent)
            await asyncio.sleep(0)
        self.total_deltas = sent
        return text


def _streaming_manager(reply: str, size: int, monkeypatch):
    manager, parts = _manager([], monkeypatch)
    llm = StreamingLLM([reply], size, parts["overlays"])
    manager._llm.delta.disconnect(manager._on_llm_delta)
    manager._llm = llm
    llm.delta.connect(manager._on_llm_delta)
    parts["llm"] = llm
    return manager, parts


def test_find_point_tag_needs_complete_tag() -> None:
    assert find_point_tag("hi [POINT:12,3") is None
    assert find_point_tag("hi [POINT:12,3:save btn:screen2] [STEP:1/2]").screen == 2
    assert find_point_tag("hi [POINT:none]") is None


@pytest.mark.parametrize("size", [1, 3, 7])
def test_early_flight_once_with_split_tags(qt_app, monkeypatch, size) -> None:  # noqa: F811
    reply = "click new in the toolbar. [POINT:40,120:new button] [STEP:1/2] [CONCEPTS:folders]"
    manager, parts = _streaming_manager(reply, size, monkeypatch)

    async def run() -> None:
        _ask(manager, "how do i make a new folder")
        await _settle(manager)

    asyncio.run(run())
    llm = parts["llm"]
    flights = parts["overlays"].flights
    assert len(flights) == 1
    assert flights[0][2:] == (True, (1, 2))
    # Flew before the stream finished, not at llm_done.
    assert llm.deltas_at_flight and llm.deltas_at_flight[0] < llm.total_deltas
    assert parts["annotations"] == [("new button", 1, 2)]
    assert manager._state == VoiceState.GUIDING


def test_early_flight_without_step_uses_concepts_and_no_hold(qt_app, monkeypatch) -> None:  # noqa: F811
    reply = "that is the save icon. [POINT:40,120:save] [CONCEPTS:saving]"
    manager, parts = _streaming_manager(reply, 4, monkeypatch)

    async def run() -> None:
        _ask(manager, "what is that")
        await _settle(manager)

    asyncio.run(run())
    assert [f[2:] for f in parts["overlays"].flights] == [(False, None)]


def test_tag_at_very_end_still_flies_once_at_end(qt_app, monkeypatch) -> None:  # noqa: F811
    manager, parts = _streaming_manager("see that? [POINT:40,120:save]", 5, monkeypatch)

    async def run() -> None:
        _ask(manager, "what is that")
        await _settle(manager)

    asyncio.run(run())
    assert len(parts["overlays"].flights) == 1


def test_point_none_and_garbage_do_not_fly(qt_app, monkeypatch) -> None:  # noqa: F811
    for reply in ("hello. [POINT:none]", "hello. [POINT:oops"):
        manager, parts = _streaming_manager(reply, 3, monkeypatch)

        async def run(manager=manager) -> None:
            _ask(manager, "hi")
            await _settle(manager)

        asyncio.run(run())
        assert parts["overlays"].flights == []


def test_warm_up_runs_once_and_does_not_block(qt_app, monkeypatch) -> None:  # noqa: F811
    manager, _ = _manager([], monkeypatch)
    calls: list[str] = []

    async def warm(model: str) -> None:
        calls.append(model)
        await asyncio.sleep(0.05)

    manager._llm.warm_up = warm

    async def run() -> None:
        task = asyncio.ensure_future(manager.warm_up_llm())
        await asyncio.sleep(0)
        assert not task.done()  # runs in the background; the caller was not blocked
        await task
        await manager.warm_up_llm()

    asyncio.run(run())
    assert calls == ["m"]


def test_warm_up_swallows_errors_and_skips_clients_without_it(qt_app, monkeypatch) -> None:  # noqa: F811
    manager, _ = _manager([], monkeypatch)
    asyncio.run(manager.warm_up_llm())  # FakeLLM has no warm_up

    async def boom(model: str) -> None:
        raise RuntimeError("tunnel down")

    manager._llm.warm_up = boom
    asyncio.run(manager.warm_up_llm())


def test_walkthrough_completed_only_on_success(qt_app, monkeypatch) -> None:  # noqa: F811
    done = []
    manager, parts = _manager(
        ["a. [POINT:40,120:new] [STEP:1/2]", "all done. [POINT:none]"], monkeypatch
    )
    manager.walkthrough_completed.connect(lambda: done.append(1))

    async def run() -> None:
        _ask(manager, "how do i make a folder")
        await _settle(manager)
        assert done == []
        parts["clicks"].clicked.emit()
        await _settle(manager)

    asyncio.run(run())
    assert done == [1]


def test_walkthrough_completed_not_on_cancel_or_timeout(qt_app, monkeypatch) -> None:  # noqa: F811
    done = []
    manager, parts = _manager(["a. [POINT:40,120:new] [STEP:1/2]"] * 2, monkeypatch)
    manager.walkthrough_completed.connect(lambda: done.append(1))

    async def run() -> None:
        _ask(manager, "how do i make a folder")
        await _settle(manager)
        manager._on_escape()
        _ask(manager, "how do i make a folder")
        await _settle(manager)
        manager._on_walkthrough_timeout()
        _ask(manager, "how do i make a folder")

    asyncio.run(run())
    assert done == []
