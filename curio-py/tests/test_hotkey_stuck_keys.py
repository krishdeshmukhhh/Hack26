"""Regression tests: a key whose char changes between press and release must not stick."""

from __future__ import annotations

from pynput import keyboard

from curio import hotkey
from curio.hotkey import HotkeyMonitor


def _monitor(monkeypatch) -> tuple[HotkeyMonitor, list[str]]:
    # No GetAsyncKeyState in unit tests — exercise the vk normalization alone.
    monkeypatch.setattr(hotkey, "_get_async_key_state", None)
    mon = HotkeyMonitor("ctrl+alt")
    events: list[str] = []
    monkeypatch.setattr(mon, "_post_main", events.append)
    return mon, events


def test_shift_released_before_letter_does_not_block_hotkey(monkeypatch) -> None:
    mon, events = _monitor(monkeypatch)
    mon._on_press(keyboard.Key.shift)
    mon._on_press(keyboard.KeyCode(vk=73, char="I"))
    mon._on_release(keyboard.Key.shift)
    mon._on_release(keyboard.KeyCode(vk=73, char="i"))
    assert mon._held == set()

    mon._on_press(keyboard.Key.ctrl_l)
    mon._on_press(keyboard.Key.alt_l)
    assert events == ["_emit_pressed"]


def test_stale_key_is_pruned_using_os_key_state(monkeypatch) -> None:
    mon, events = _monitor(monkeypatch)
    mon._on_press(keyboard.KeyCode(vk=65, char="a"))  # its key-up gets lost
    mon._on_press(keyboard.Key.ctrl_l)

    # Windows says only Ctrl is physically down.
    down = {keyboard.Key.ctrl_l.value.vk}
    monkeypatch.setattr(
        hotkey, "_get_async_key_state", lambda vk: 0x8000 if vk in down else 0
    )
    mon._on_press(keyboard.Key.alt_l)
    assert events == ["_emit_pressed"]
