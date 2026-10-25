"""Foreground activity sampling for focus mode (section B).

``WindowsActivitySource`` polls the foreground window, its process name and
the system idle time on Qt timers, so callbacks always run on the Qt main
thread. Each Win32 call is a few microseconds, which is why the poll does not
need a worker thread. Input is only *counted*, from changes in
``GetLastInputInfo``'s timestamp: nothing hooks the keyboard and no key or
character is ever read. Off Windows the probe returns empty values, so the
source still runs (with empty samples) and tests work anywhere.

``FakeActivitySource`` replays scripted samples for tests and demos.
"""

from __future__ import annotations

import contextlib
import ctypes
import logging
import os
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PureWindowsPath

from PySide6.QtCore import QObject, QTimer

from curio.active_window import get_foreground_window_title
from curio.focus_contract import ActivitySample, Unsubscribe
from curio.learning_contract import app_key

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]

OWN_APP = "curio"

# Executable stems whose app_key differs from the name their window titles end
# with; mapping them keeps exe-based keys equal to title-based allowed_apps.
_EXE_ALIASES = {
    "winword": "word",
    "powerpnt": "powerpoint",
    "msedge": "microsoft edge",
    "chrome": "google chrome",
    "firefox": "mozilla firefox",
    "code": "visual studio code",
    "devenv": "visual studio",
    "acrord32": "adobe acrobat reader",
    "acrobat": "adobe acrobat",
    "applicationframehost": "",  # UWP host: the title is more informative
}

_BROWSERS = frozenset(
    {
        "google chrome",
        "microsoft edge",
        "mozilla firefox",
        "brave",
        "opera",
        "vivaldi",
        "arc",
    }
)


def is_browser(app: str) -> bool:
    return app in _BROWSERS


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, kw_only=True)
class RawActivity:
    """What one probe of the desktop returns. No keystroke content, by design."""

    title: str = ""
    exe_path: str = ""  # full image path of the foreground process, if readable
    window_id: int = 0  # foreground HWND, 0 if unknown
    idle_seconds: float = 0.0
    last_input_tick: int = 0  # GetLastInputInfo().dwTime; changes when any input arrives
    own_window: bool = False  # the foreground window belongs to this process


def resolve_app(raw: RawActivity) -> str:
    """app_key of the foreground window, preferring the executable name."""
    if raw.own_window:
        return OWN_APP
    if raw.exe_path:
        stem = PureWindowsPath(raw.exe_path).stem.lower()
        alias = _EXE_ALIASES.get(stem, stem)
        if alias:
            return app_key(alias)
    return app_key(raw.title)


# --- Win32 probe -----------------------------------------------------------------

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class _Win32:
    """Private WinDLL handles with explicit signatures (64-bit HANDLE safe)."""

    def __init__(self) -> None:
        from ctypes import wintypes

        self.wintypes = wintypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class LastInputInfo(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        self.LastInputInfo = LastInputInfo
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetForegroundWindow.argtypes = []
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetLastInputInfo.restype = wintypes.BOOL
        user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LastInputInfo)]
        kernel32.GetTickCount.restype = wintypes.DWORD
        kernel32.GetTickCount.argtypes = []
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.user32 = user32
        self.kernel32 = kernel32

    def last_input(self) -> tuple[int, float]:
        info = self.LastInputInfo()
        info.cbSize = ctypes.sizeof(info)
        if not self.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0, 0.0
        now = self.kernel32.GetTickCount()
        return int(info.dwTime), ((now - info.dwTime) & 0xFFFFFFFF) / 1000.0

    def foreground(self) -> tuple[int, int]:
        hwnd = self.user32.GetForegroundWindow()
        if not hwnd:
            return 0, 0
        pid = self.wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(hwnd), int(pid.value)

    def image_path(self, pid: int) -> str:
        if not pid:
            return ""
        handle = self.kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            size = self.wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(size.value)
            if not self.kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return ""
            return buf.value
        finally:
            self.kernel32.CloseHandle(handle)


_win32: _Win32 | None = None


def _api() -> _Win32 | None:
    global _win32
    if sys.platform != "win32":
        return None
    if _win32 is None:
        _win32 = _Win32()
    return _win32


def read_last_input_tick() -> int:
    """Cheap input-activity probe; 0 off Windows or on failure."""
    try:
        api = _api()
        return api.last_input()[0] if api else 0
    except Exception:  # noqa: BLE001
        logger.debug("GetLastInputInfo failed", exc_info=True)
        return 0


def probe_windows() -> RawActivity:
    """Read the foreground window and idle time. Empty off Windows or on failure."""
    try:
        api = _api()
        if api is None:
            return RawActivity()
        hwnd, pid = api.foreground()
        tick, idle = api.last_input()
        return RawActivity(
            title=get_foreground_window_title() if hwnd else "",
            exe_path=api.image_path(pid),
            window_id=hwnd,
            idle_seconds=idle,
            last_input_tick=tick,
            own_window=pid == os.getpid(),
        )
    except Exception:  # noqa: BLE001
        logger.debug("foreground probe failed", exc_info=True)
        return RawActivity()


# --- Sources ---------------------------------------------------------------------


class _Subscribers:
    def __init__(self) -> None:
        self._callbacks: list[Callable[[ActivitySample], None]] = []

    def subscribe(self, callback: Callable[[ActivitySample], None]) -> Unsubscribe:
        self._callbacks.append(callback)

        def unsubscribe() -> None:
            with contextlib.suppress(ValueError):
                self._callbacks.remove(callback)

        return unsubscribe

    def emit(self, sample: ActivitySample) -> None:
        for callback in tuple(self._callbacks):
            try:
                callback(sample)
            except Exception:  # noqa: BLE001
                logger.exception("activity subscriber failed")


class WindowsActivitySource(QObject):
    """ActivitySource that samples the Windows desktop on the Qt main thread.

    ``input_events`` counts the input-poll ticks (every ``input_poll_ms``)
    during which ``GetLastInputInfo`` reported new input: an activity level,
    not a keystroke count, and never keystroke content.
    """

    def __init__(
        self,
        *,
        interval_seconds: float = 2.0,
        input_poll_ms: int = 250,
        clock: Clock | None = None,
        probe: Callable[[], RawActivity] | None = None,
        input_tick: Callable[[], int] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._clock = clock or _utc_now
        self._probe = probe or probe_windows
        self._input_tick = input_tick or read_last_input_tick
        self._subscribers = _Subscribers()
        self._sample_timer = QTimer(self)
        self._sample_timer.setInterval(round(interval_seconds * 1000))
        self._sample_timer.timeout.connect(self.poll_once)
        self._input_timer = QTimer(self)
        self._input_timer.setInterval(max(input_poll_ms, 0))
        self._input_timer.timeout.connect(self.poll_input)
        self._use_input_timer = input_poll_ms > 0
        self._last_tick: int | None = None
        self._input_count = 0
        self._previous: RawActivity | None = None
        self._previous_app = ""

    @property
    def running(self) -> bool:
        return self._sample_timer.isActive()

    def subscribe(self, callback: Callable[[ActivitySample], None]) -> Unsubscribe:
        return self._subscribers.subscribe(callback)

    def start(self) -> None:
        """Start polling. Idempotent."""
        if self.running:
            return
        self._last_tick = None
        self._input_count = 0
        self._previous = None
        self._sample_timer.start()
        if self._use_input_timer:
            self._input_timer.start()

    def stop(self) -> None:
        self._sample_timer.stop()
        self._input_timer.stop()

    def poll_input(self) -> None:
        """Count one input event if GetLastInputInfo's timestamp moved."""
        tick = self._input_tick()
        if self._last_tick is not None and tick != self._last_tick:
            self._input_count += 1
        self._last_tick = tick

    def poll_once(self) -> ActivitySample:
        """Take one sample and deliver it to subscribers (public for tests)."""
        raw = self._probe()
        if not self._use_input_timer:
            # No sub-sampling: one "event" per sample interval that saw input.
            if self._last_tick is not None and raw.last_input_tick != self._last_tick:
                self._input_count = 1
            self._last_tick = raw.last_input_tick
        else:
            self.poll_input()
        app = resolve_app(raw)
        previous = self._previous
        is_switch = previous is not None and (
            raw.window_id != previous.window_id
            or app != self._previous_app
            # A browser tab change keeps the HWND but changes the title.
            or (is_browser(app) and raw.title != previous.title)
        )
        sample = ActivitySample(
            app=app,
            window_title=raw.title,
            idle_seconds=max(raw.idle_seconds, 0.0),
            input_events=self._input_count,
            is_switch=is_switch,
            at=self._clock(),
        )
        self._input_count = 0
        self._previous = raw
        self._previous_app = app
        self._subscribers.emit(sample)
        return sample


class FakeActivitySource(QObject):
    """Replays scripted samples. Drive it with ``step()``/``play()``, or give
    ``interval_seconds`` to replay on a Qt timer for demos."""

    def __init__(
        self,
        samples: Iterable[ActivitySample] = (),
        *,
        interval_seconds: float | None = None,
        loop: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._samples: list[ActivitySample] = list(samples)
        self._index = 0
        self._loop = loop
        self._started = False
        self._subscribers = _Subscribers()
        self._timer: QTimer | None = None
        if interval_seconds is not None:
            self._timer = QTimer(self)
            self._timer.setInterval(round(interval_seconds * 1000))
            self._timer.timeout.connect(self.step)

    @property
    def running(self) -> bool:
        return self._started

    @property
    def remaining(self) -> int:
        return len(self._samples) - self._index

    def subscribe(self, callback: Callable[[ActivitySample], None]) -> Unsubscribe:
        return self._subscribers.subscribe(callback)

    def start(self) -> None:
        self._started = True
        if self._timer is not None:
            self._timer.start()

    def stop(self) -> None:
        self._started = False
        if self._timer is not None:
            self._timer.stop()

    def push(self, sample: ActivitySample) -> None:
        self._samples.append(sample)

    def step(self) -> ActivitySample | None:
        """Emit the next sample, if started and any remain."""
        if not self._started:
            return None
        if self._index >= len(self._samples):
            if not (self._loop and self._samples):
                self.stop()
                return None
            self._index = 0
        sample = self._samples[self._index]
        self._index += 1
        self._subscribers.emit(sample)
        return sample

    def play(self) -> list[ActivitySample]:
        """Emit every remaining sample synchronously (starts the source if needed)."""
        if not self._started:
            self._started = True
        emitted = []
        while self._index < len(self._samples):
            sample = self.step()
            if sample is None:
                break
            emitted.append(sample)
        return emitted


def scripted_samples(
    steps: Sequence[tuple],
    *,
    start: datetime,
    interval_seconds: float = 2.0,
    input_events: int = 3,
) -> list[ActivitySample]:
    """Expand ``(app, title, seconds[, idle_seconds[, input_events]])`` steps into
    samples every ``interval_seconds``. ``is_switch`` is set on the first sample
    of each step whose app or title differs from the step before."""
    samples: list[ActivitySample] = []
    at = start
    previous: tuple[str, str] | None = None
    for step in steps:
        app, title, seconds = step[0], step[1], float(step[2])
        idle = float(step[3]) if len(step) > 3 else 0.0
        events = int(step[4]) if len(step) > 4 else input_events
        count = max(1, round(seconds / interval_seconds))
        for i in range(count):
            switch = i == 0 and previous is not None and previous != (app, title)
            samples.append(
                ActivitySample(
                    app=app,
                    window_title=title,
                    idle_seconds=idle,
                    input_events=events,
                    is_switch=switch,
                    at=at,
                )
            )
            at += timedelta(seconds=interval_seconds)
        previous = (app, title)
    return samples
