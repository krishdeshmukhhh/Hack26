"""Global hold-to-talk input monitoring and key release handling."""

from __future__ import annotations

import ctypes
import logging
import threading
from enum import Enum, auto

from pynput import keyboard
from PySide6.QtCore import QObject, Qt, Signal, Slot

logger = logging.getLogger(__name__)

try:
    _get_async_key_state = ctypes.windll.user32.GetAsyncKeyState
    _vk_key_scan = ctypes.windll.user32.VkKeyScanW
    _vk_key_scan.restype = ctypes.c_short
except AttributeError:  # not Windows
    _get_async_key_state = None
    _vk_key_scan = None

# Virtual-key codes to ask Windows about for the merged modifier names.
_VK_SHIFT = 0x10
_VK_MENU = 0x12  # either Alt


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

    # keyboard.KeyCode — regular character keys. Prefer the virtual-key
    # code: the char changes with Shift, so "Shift down, I down, Shift up,
    # i up" would otherwise leave "I" held forever and block the hotkey.
    vk = getattr(key, "vk", None)
    char = getattr(key, "char", None)
    if vk is None and char and _vk_key_scan is not None:
        # Unicode-packet events (some IMEs, injected input) carry only a char.
        scanned = _vk_key_scan(char)
        if scanned != -1:
            vk = scanned & 0xFF
    if vk is not None:
        return f"vk{vk}"
    if char:
        return char.lower()
    return str(key)


def _key_vk(name: str, key: keyboard.Key | keyboard.KeyCode) -> int | None:
    """Virtual-key code for GetAsyncKeyState, matching _normalize_key's merging."""
    if name == "alt":
        return _VK_MENU
    if name == "shift":
        return _VK_SHIFT
    if isinstance(key, keyboard.Key):
        return getattr(key.value, "vk", None)
    return getattr(key, "vk", None)


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
    selection_cancelled = Signal()
    _input_event = Signal(object)

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
        self._held_vks: dict[str, int] = {}
        self._state: _HotkeyState = _HotkeyState.UNARMED
        self._listener: keyboard.Listener | None = None
        self._input_lock = threading.RLock()
        self._chord_serial = 0
        self._suppressed_chords: set[int] = set()
        self._lifecycle = 0
        self._input_event.connect(self._deliver_input, Qt.ConnectionType.QueuedConnection)

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Install the global keyboard hook. Idempotent."""
        if self._listener is not None:
            return
        lifecycle = self._lifecycle

        def guarded(callback):
            def invoke(key):
                with self._input_lock:
                    if self._listener is not None and lifecycle == self._lifecycle:
                        callback(key)
            return invoke

        self._listener = keyboard.Listener(
            on_press=guarded(self._on_press), on_release=guarded(self._on_release)
        )
        self._listener.start()

    def stop(self) -> None:
        """Remove the global keyboard hook and reset internal state."""
        with self._input_lock:
            listener = self._listener
            self._listener = None
            self._held.clear()
            self._held_vks.clear()
            self._state = _HotkeyState.UNARMED
            self._lifecycle += 1
            self._suppressed_chords.clear()
        if listener is not None:
            listener.stop()

    def suppress_for_selection(self) -> None:
        """Input-thread arbitration: invalidate even already-queued chord events.

        No Qt widget/manager calls here. Selection owns the mouse hook and calls
        this before suppressing the native press, regardless of the voice binding.
        """
        with self._input_lock:
            self._suppressed_chords.add(self._chord_serial)
            self._state = _HotkeyState.CANCELLED
            self._post_main("_emit_selection_cancelled")

    # ------------------------------------------------------------------
    # pynput callbacks (run on the listener's background thread)
    # ------------------------------------------------------------------
    def _on_press(self, key: keyboard.Key | keyboard.KeyCode | None) -> None:
        with self._input_lock:
            self._handle_press(key)

    def _handle_press(self, key: keyboard.Key | keyboard.KeyCode | None) -> None:
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
        vk = _key_vk(name, key)
        if vk is not None:
            self._held_vks[name] = vk
        logger.debug("key down %s (state=%s, held=%s)", name, self._state.name, sorted(self._held))

        if self._state == _HotkeyState.UNARMED:
            self._prune_released_keys(keep=name)
            if self._is_armed():
                self._chord_serial += 1
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
        with self._input_lock:
            self._handle_release(key)

    def _handle_release(self, key: keyboard.Key | keyboard.KeyCode | None) -> None:
        if key == keyboard.Key.esc:
            self._held.discard("esc")
            return

        name = _normalize_key(key)
        if name is None:
            return
        self._held.discard(name)
        self._held_vks.pop(name, None)
        logger.debug("key up %s (state=%s, held=%s)", name, self._state.name, sorted(self._held))

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
            self._prune_released_keys()
            if not self._held:
                self._state = _HotkeyState.UNARMED
            return

    def _prune_released_keys(self, keep: str | None = None) -> None:
        """Drop held keys whose key-up we never saw.

        Releases can go missing (an elevated window had focus, the
        workstation was locked mid-chord), and one phantom key blocks the
        strict "nothing else held" check forever. Ask Windows which keys
        are physically down. ``keep`` is the key being pressed right now:
        a low-level hook runs before Windows updates its key state, so it
        would look released.
        """
        if _get_async_key_state is None:
            return
        for name in list(self._held):
            vk = self._held_vks.get(name)
            if name == keep or vk is None:
                continue
            if not _get_async_key_state(vk) & 0x8000:
                logger.debug("dropping stale held key %s", name)
                self._held.discard(name)
                self._held_vks.pop(name, None)

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
    # marshal onto the main thread with _input_event using
    # a queued connection so that the slot (and therefore the signal
    # emit it performs) runs on the thread this QObject lives in —
    # normally the main thread. QTimer.singleShot does NOT work here
    # because it tries to post via the caller thread's event loop,
    # which pynput's background thread does not have.

    def _post_main(self, slot_name: str) -> None:
        self._input_event.emit((self._lifecycle, self._chord_serial, slot_name))

    @Slot(object)
    def _deliver_input(self, event) -> None:
        lifecycle, serial, slot_name = event
        if lifecycle != self._lifecycle:
            return
        with self._input_lock:
            suppressed = serial in self._suppressed_chords
            if slot_name == "_emit_pressed" and not suppressed:
                self._suppressed_chords.difference_update(
                    s for s in tuple(self._suppressed_chords) if s < serial
                )
        if suppressed and slot_name in ("_emit_pressed", "_emit_released", "_emit_cancelled"):
            return
        getattr(self, slot_name)()

    @Slot()
    def _emit_selection_cancelled(self) -> None:
        self.selection_cancelled.emit()

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
