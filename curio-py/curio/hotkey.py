"""Global hold-to-talk input monitoring and key release handling."""

from __future__ import annotations

from enum import Enum, auto

from pynput import keyboard
from PySide6.QtCore import QMetaObject, QObject, Qt, Signal, Slot


class _HotkeyState(Enum):
    UNARMED = auto()
    ARMED = auto()
    CANCELLED = auto()


def _normalize_key(key: keyboard.Key | keyboard.KeyCode | None) -> str | None:
    """Map a pynput key object to a stable string identifier.

    Returns ``None`` if the key cannot be identified (e.g. a dead key
    event with no char on some layouts).
    """
    if key is None:
        return None

    if isinstance(key, keyboard.Key):
        if key == keyboard.Key.ctrl_l:
            return "ctrl_l"
        if key == keyboard.Key.ctrl_r:
            return "ctrl_r"
        if key in (keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr):
            # alt_gr on international layouts is synthesised as Ctrl+Alt
            # by Windows; pynput still reports it as alt_gr. Map to
            # "alt" so Ctrl+AltGr behaves like Ctrl+Alt. Users on intl
            # layouts who hit false positives should switch to the
            # right_ctrl binding (see config.example.toml).
            return "alt"
        if key in (keyboard.Key.shift_l, keyboard.Key.shift_r):
            return "shift"
        # pynput uses Key.cmd for Windows key on Windows; also expose
        # cmd_l / cmd_r for completeness in case of platform drift.
        if key == keyboard.Key.cmd:
            return "win"
        cmd_l = getattr(keyboard.Key, "cmd_l", None)
        cmd_r = getattr(keyboard.Key, "cmd_r", None)
        if cmd_l is not None and key == cmd_l:
            return "win"
        if cmd_r is not None and key == cmd_r:
            return "win"
        return str(key)

    # keyboard.KeyCode — regular character keys.
    char = getattr(key, "char", None)
    if char:
        return char
    return str(key)


class HotkeyMonitor(QObject):
    """Qt-friendly global hotkey monitor backed by pynput.

    Signals
    -------
    pressed
        The configured chord just became fully armed.
    released
        A previously armed chord ended because a required modifier was
        released.
    cancelled
        A previously armed chord was invalidated because the user
        pressed an additional key. ``released`` is **not** emitted in
        this case.
    """

    pressed = Signal()
    released = Signal()
    cancelled = Signal()
    # Fired on any Escape keypress — used by the UI layer to dismiss the
    # floating panel reliably, since Qt focus semantics for frameless
    # Tool windows on Windows 11 don't guarantee keyPressEvent delivery.
    escape_pressed = Signal()

    _VALID_BINDINGS: frozenset[str] = frozenset({"ctrl+alt", "right_ctrl"})

    def __init__(self, binding: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        if binding not in self._VALID_BINDINGS:
            raise ValueError(
                f"Unknown hotkey binding {binding!r}; "
                f"expected one of {sorted(self._VALID_BINDINGS)}"
            )
        self._binding = binding
        self._held: set[str] = set()
        self._state: _HotkeyState = _HotkeyState.UNARMED
        self._listener: keyboard.Listener | None = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Install the global keyboard hook. Idempotent."""
        if self._listener is not None:
            return
        self._listener = keyboard.Listener(
            on_press=self._on_press, on_release=self._on_release
        )
        self._listener.start()

    def stop(self) -> None:
        """Remove the global keyboard hook and reset internal state."""
        listener = self._listener
        self._listener = None
        if listener is not None:
            listener.stop()
        self._held.clear()
        self._state = _HotkeyState.UNARMED

    # ------------------------------------------------------------------
    # pynput callbacks (run on the listener's background thread)
    # ------------------------------------------------------------------
    def _on_press(self, key: keyboard.Key | keyboard.KeyCode | None) -> None:
        # Escape is a special global signal for the UI layer (panel
        # dismissal). Emit it on every fresh press regardless of hotkey
        # state; auto-repeat is filtered below.
        if key == keyboard.Key.esc:
            # Track it in _held so the auto-repeat filter applies.
            if "esc" not in self._held:
                self._held.add("esc")
                self._post_main("_emit_escape")
            return

        name = _normalize_key(key)
        if name is None:
            return
        # pynput fires on_press repeatedly while a key is held. Only
        # the first press (set insertion) matters for the state machine.
        already_held = name in self._held
        self._held.add(name)
        if already_held:
            return

        if self._state == _HotkeyState.UNARMED:
            if self._is_armed():
                self._state = _HotkeyState.ARMED
                self._post_main("_emit_pressed")
            return

        if self._state == _HotkeyState.ARMED:
            # Any new key press while armed that breaks the strict
            # modifier-only condition cancels. _is_armed() re-checks
            # both "required mods present" and "nothing else held".
            if not self._is_armed():
                self._state = _HotkeyState.CANCELLED
                self._post_main("_emit_cancelled")
            return

        # CANCELLED — absorb further presses until everything is lifted.

    def _on_release(self, key: keyboard.Key | keyboard.KeyCode | None) -> None:
        if key == keyboard.Key.esc:
            self._held.discard("esc")
            return

        name = _normalize_key(key)
        if name is None:
            return
        self._held.discard(name)

        if self._state == _HotkeyState.ARMED:
            # Releasing any of the required modifiers ends the press.
            if not self._required_mods_all_held():
                self._state = _HotkeyState.UNARMED
                self._post_main("_emit_released")
            return

        if self._state == _HotkeyState.CANCELLED:
            # Wait until every key is lifted before re-arming is
            # allowed. This prevents a partial release from sliding
            # straight back into ARMED without the user intending a
            # new press.
            if not self._held:
                self._state = _HotkeyState.UNARMED
            return

    # ------------------------------------------------------------------
    # arming predicates
    # ------------------------------------------------------------------
    def _required_mods_all_held(self) -> bool:
        if self._binding == "ctrl+alt":
            has_ctrl = "ctrl_l" in self._held or "ctrl_r" in self._held
            return has_ctrl and "alt" in self._held
        # right_ctrl
        return "ctrl_r" in self._held

    def _is_armed(self) -> bool:
        """True iff the currently-held set matches the binding exactly.

        "Exactly" means: all required modifiers are held AND no other
        key (modifier or regular) is held.
        """
        if not self._required_mods_all_held():
            return False

        if self._binding == "ctrl+alt":
            allowed: set[str] = {"alt"}
            # Accept either or both Ctrl variants; disallow everything else.
            if "ctrl_l" in self._held:
                allowed.add("ctrl_l")
            if "ctrl_r" in self._held:
                allowed.add("ctrl_r")
            return self._held <= allowed and self._held.issuperset({"alt"})

        # right_ctrl: held set must be exactly {"ctrl_r"}.
        return self._held == {"ctrl_r"}

    # ------------------------------------------------------------------
    # thread-safe signal emission
    # ------------------------------------------------------------------
    # pynput callbacks run on the listener's background thread. We
    # marshal onto the main thread with QMetaObject.invokeMethod using
    # a queued connection so that the slot (and therefore the signal
    # emit it performs) runs on the thread this QObject lives in —
    # normally the main thread. QTimer.singleShot does NOT work here
    # because it tries to post via the caller thread's event loop,
    # which pynput's background thread does not have.

    def _post_main(self, slot_name: str) -> None:
        QMetaObject.invokeMethod(
            self, slot_name, Qt.ConnectionType.QueuedConnection
        )

    @Slot()
    def _emit_pressed(self) -> None:
        self.pressed.emit()

    @Slot()
    def _emit_released(self) -> None:
        self.released.emit()

    @Slot()
    def _emit_cancelled(self) -> None:
        self.cancelled.emit()

    @Slot()
    def _emit_escape(self) -> None:
        self.escape_pressed.emit()
