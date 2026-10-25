"""Keyboard step-finish detection: watcher logic and the hotkey tap filter."""

from __future__ import annotations

import asyncio

import pytest
from pynput import keyboard
from PySide6.QtCore import QCoreApplication, QObject, Signal

from curio import hotkey as hotkey_module
from curio.hotkey import HotkeyMonitor
from curio.key_finish_watcher import (
    TYPING_IDLE_SECONDS,
    KeyFinishWatcher,
)
from curio.state import VoiceState
from tests.test_walkthrough import TWO_STEPS, _ask, _manager, _settle


@pytest.fixture
def qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


class FakeTapHotkey(QObject):
    typing_enter = Signal()
    typing_printable = Signal()
    typing_tap_enabled = False


class Clock:
    now = 100.0

    def __call__(self) -> float:
        return self.now


def _watcher(qt_app):
    hk, clock = FakeTapHotkey(), Clock()
    w = KeyFinishWatcher(hk, clock=clock)
    hits: list[int] = []
    w.finished.connect(lambda: hits.append(1))
    return hk, clock, w, hits


def test_enter_finishes(qt_app) -> None:
    hk, _, w, hits = _watcher(qt_app)
    w.start()
    assert hk.typing_tap_enabled
    hk.typing_enter.emit()
    assert hits == [1]
    assert not hk.typing_tap_enabled and not w.active


def test_idle_after_typing_finishes(qt_app) -> None:
    hk, clock, w, hits = _watcher(qt_app)
    w.start()
    hk.typing_printable.emit()
    clock.now += 0.5
    hk.typing_printable.emit()
    clock.now += TYPING_IDLE_SECONDS - 0.1
    w.tick()
    assert hits == []
    clock.now += 0.2
    w.tick()
    w.tick()
    assert hits == [1]


def test_single_key_does_not_finish_on_idle(qt_app) -> None:
    hk, clock, w, hits = _watcher(qt_app)
    w.start()
    hk.typing_printable.emit()
    clock.now += 60
    w.tick()
    assert hits == []


def test_not_armed_ignored(qt_app) -> None:
    hk, clock, w, hits = _watcher(qt_app)
    hk.typing_enter.emit()
    hk.typing_printable.emit()
    hk.typing_printable.emit()
    clock.now += 60
    w.tick()
    w.start()
    w.stop()
    hk.typing_enter.emit()
    assert hits == []


def test_rearm_resets_count(qt_app) -> None:
    hk, clock, w, hits = _watcher(qt_app)
    w.start()
    hk.typing_printable.emit()
    hk.typing_printable.emit()
    w.start()
    clock.now += 60
    w.tick()
    assert hits == []


# --- the hotkey-side filter -------------------------------------------------


def _tap_monitor(monkeypatch, qt_app):
    monkeypatch.setattr(hotkey_module, "_get_async_key_state", None)
    mon = HotkeyMonitor("ctrl+alt")
    mon.typing_tap_enabled = True
    posted: list[str] = []
    monkeypatch.setattr(mon, "_post_main", posted.append)
    return mon, posted


def _char(c: str) -> keyboard.KeyCode:
    return keyboard.KeyCode.from_char(c)


def test_monitor_classifies_plain_typing(monkeypatch, qt_app) -> None:
    mon, posted = _tap_monitor(monkeypatch, qt_app)
    mon._on_press(_char("a"))
    mon._on_release(_char("a"))
    mon._on_press(keyboard.Key.space)
    mon._on_release(keyboard.Key.space)
    mon._on_press(keyboard.Key.enter)
    assert posted == ["_emit_typing_printable", "_emit_typing_printable", "_emit_typing_enter"]


def test_monitor_ignores_shortcuts_and_hotkey(monkeypatch, qt_app) -> None:
    mon, posted = _tap_monitor(monkeypatch, qt_app)
    mon._on_press(keyboard.Key.ctrl_l)
    mon._on_press(_char("c"))
    assert "_emit_typing_printable" not in posted
    mon._on_release(_char("c"))
    mon._on_press(keyboard.Key.alt_l)  # push-to-talk armed
    mon._on_press(keyboard.Key.enter)
    assert "_emit_typing_enter" not in posted
    mon._on_release(keyboard.Key.alt_l)
    mon._on_release(keyboard.Key.ctrl_l)
    mon._on_press(keyboard.Key.cmd)
    mon._on_press(_char("r"))
    assert "_emit_typing_printable" not in posted


def test_monitor_disabled_tap_posts_nothing(monkeypatch, qt_app) -> None:
    mon, posted = _tap_monitor(monkeypatch, qt_app)
    mon.typing_tap_enabled = False
    mon._on_press(_char("a"))
    mon._on_press(keyboard.Key.enter)
    assert posted == []


# --- manager integration ----------------------------------------------------


def test_click_and_keyboard_together_continue_once(qt_app, monkeypatch) -> None:
    manager, parts = _manager(TWO_STEPS, monkeypatch)
    hk = FakeTapHotkey()
    watcher = KeyFinishWatcher(hk)
    manager._key_watcher = watcher
    watcher.finished.connect(manager._on_walkthrough_click)

    async def run() -> None:
        _ask(manager, "how do i make a new folder")
        await _settle(manager)
        assert manager._state == VoiceState.GUIDING
        assert watcher.active
        hk.typing_enter.emit()
        parts["clicks"].clicked.emit()
        assert manager._state == VoiceState.PROCESSING
        assert not watcher.active and not parts["clicks"].active
        await _settle(manager)
        assert watcher.active  # re-armed for step 2
        hk.typing_enter.emit()
        parts["clicks"].clicked.emit()
        await _settle(manager)

    asyncio.run(run())
    assert len(parts["llm"].requests) == 3
    assert not watcher.active


def test_escape_disarms_key_watcher(qt_app, monkeypatch) -> None:
    manager, parts = _manager(TWO_STEPS, monkeypatch)
    hk = FakeTapHotkey()
    watcher = KeyFinishWatcher(hk)
    manager._key_watcher = watcher
    watcher.finished.connect(manager._on_walkthrough_click)

    async def run() -> None:
        _ask(manager, "how do i make a new folder")
        await _settle(manager)
        assert watcher.active
        parts["hotkey"].escape_pressed.emit()
        assert not watcher.active and not hk.typing_tap_enabled
        hk.typing_enter.emit()

    asyncio.run(run())
    assert len(parts["llm"].requests) == 1
