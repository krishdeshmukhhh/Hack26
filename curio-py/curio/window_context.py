"""Open-window summary for the vision model (Windows only).

Gives the model what a screenshot can't: which windows exist, their z-order,
and whether the focused one is maximized over the desktop. Never raises; any
failure (or a non-Windows platform) yields ``None`` so the turn proceeds
without it.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass

logger = logging.getLogger(__name__)

HEADER = "open windows (untrusted titles, front to back):"
_MAX_TITLE_CHARS = 60
_COVER_FRACTION = 0.9

_DWMWA_CLOAKED = 14
_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SHELL_CLASSES = {"Progman", "WorkerW"}


@dataclass(frozen=True)
class WindowInfo:
    """One top-level window. ``state`` is "minimized", "maximized" or "normal"."""

    title: str
    exe: str
    state: str
    focused: bool = False
    covers_screen: int | None = None  # 1-based screen number, as in screenshot labels


def _neutralize(text: str) -> str:
    """Strip brackets so a title can't imitate [POINT:...] / [STEP:...] tags."""
    return text.replace("[", "(").replace("]", ")")


def _truncate(title: str) -> str:
    title = _neutralize(" ".join(title.split())).replace('"', "'")
    if len(title) > _MAX_TITLE_CHARS:
        title = title[: _MAX_TITLE_CHARS - 1].rstrip() + "…"
    return title


def format_windows(windows: list[WindowInfo], max_windows: int = 8) -> str:
    """Render windows (already front-to-back) in the prompt contract format."""
    shown = windows[:max_windows]
    if not shown:
        return f"{HEADER}\n- none (desktop is showing)"
    lines = [HEADER]
    for win in shown:
        focus = " [focused]" if win.focused else ""
        state = win.state
        if win.covers_screen is not None and win.state != "minimized":
            state += f", covers screen {win.covers_screen}"
        exe = _neutralize(win.exe) or "unknown"
        lines.append(f'- "{_truncate(win.title)}" ({exe}){focus} — {state}')
    return "\n".join(lines)


_MAX_ANCESTOR_LEVELS = 5  # python -> uv -> shell -> OpenConsole -> WindowsTerminal
_TH32CS_SNAPPROCESS = 0x2
# Only these ancestors count as hosting us. Anything else (Code.exe, explorer.exe, ...)
# owns unrelated windows and is never excluded.
_HOST_EXES = {
    "windowsterminal.exe", "openconsole.exe", "conhost.exe", "cmd.exe", "powershell.exe",
    "pwsh.exe", "wt.exe", "mintty.exe", "bash.exe", "uv.exe", "python.exe", "pythonw.exe",
}
_ancestor_cache: frozenset[int] | None = None


def ancestor_pids(own_pid: int, parents: dict[int, tuple[int, str]]) -> frozenset[int]:
    """Parent-chain pids of ``own_pid``. ``parents`` maps pid -> (parent pid, exe name).

    Only terminal/console hosts and our launchers are included; the walk stops at any
    other process (Code.exe, explorer.exe, ...) and on cycles.
    """
    chain: set[int] = set()
    pid = own_pid
    for _ in range(_MAX_ANCESTOR_LEVELS):
        entry = parents.get(pid)
        if entry is None:
            break
        parent = entry[0]
        parent_entry = parents.get(parent)
        if not parent or parent in chain or parent == own_pid or parent_entry is None:
            break
        if parent_entry[1].lower() not in _HOST_EXES:
            break
        chain.add(parent)
        pid = parent
    return frozenset(chain)


def is_own_host_window(
    hwnd: int, pid: int, own_pid: int, console_hwnd: int, ancestors: frozenset[int]
) -> bool:
    """True for our own windows and the console/terminal window hosting this process."""
    if pid == own_pid or pid in ancestors:
        return True
    return bool(console_hwnd) and hwnd == console_hwnd


def _process_parents() -> dict[int, tuple[int, str]]:
    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    snap = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snap or snap == wintypes.HANDLE(-1).value:
        return {}
    parents: dict[int, tuple[int, str]] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            parents[entry.th32ProcessID] = (entry.th32ParentProcessID, entry.szExeFile)
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return parents


def _own_ancestors() -> frozenset[int]:
    """Ancestor pids of this process, computed once; empty on any failure."""
    global _ancestor_cache
    if _ancestor_cache is None:
        try:
            _ancestor_cache = ancestor_pids(os.getpid(), _process_parents())
        except Exception:  # noqa: BLE001
            logger.debug("ancestor lookup failed", exc_info=True)
            _ancestor_cache = frozenset()
    return _ancestor_cache


def _console_hwnd() -> int:
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetConsoleWindow.restype = wintypes.HWND
        return int(kernel32.GetConsoleWindow() or 0)
    except Exception:  # noqa: BLE001
        return 0


def _enumerate_windows(max_windows: int) -> list[WindowInfo]:
    # Private DLL instances: setting argtypes must not leak into other modules.
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsZoomed.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    dwmapi.DwmGetWindowAttribute.argtypes = [
        wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
    ]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
    ]

    # Monitors in EnumDisplayMonitors order (what mss uses), cursor monitor first,
    # matching screen_capture.capture_all's numbering.
    monitors: list[tuple[int, tuple[int, int, int, int]]] = []
    monitor_enum_proc = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
        ctypes.POINTER(wintypes.RECT), wintypes.LPARAM,
    )

    def _on_monitor(hmon, _hdc, rect, _lparam):
        r = rect.contents
        monitors.append((hmon or 0, (r.left, r.top, r.right, r.bottom)))
        return True

    user32.EnumDisplayMonitors(None, None, monitor_enum_proc(_on_monitor), 0)
    cursor = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(cursor))
    order = sorted(
        range(len(monitors)),
        key=lambda i: (
            not (
                monitors[i][1][0] <= cursor.x < monitors[i][1][2]
                and monitors[i][1][1] <= cursor.y < monitors[i][1][3]
            ),
            i,
        ),
    )
    screen_number = {monitors[i][0]: n + 1 for n, i in enumerate(order)}
    monitor_rect = dict(monitors)

    own_pid = os.getpid()
    ancestors = _own_ancestors()
    console_hwnd = _console_hwnd()
    foreground = user32.GetForegroundWindow()
    found: list[WindowInfo] = []

    def _exe_name(pid: int) -> str:
        handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buf))
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value)
            return ""
        finally:
            kernel32.CloseHandle(handle)

    def _on_window(hwnd, _lparam):
        try:
            if len(found) >= max_windows:
                return False
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            if user32.GetWindowLongW(hwnd, _GWL_EXSTYLE) & _WS_EX_TOOLWINDOW:
                return True
            cloaked = wintypes.DWORD(0)
            dwmapi.DwmGetWindowAttribute(
                hwnd, _DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
            )
            if cloaked.value:
                return True
            cls_buf = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, cls_buf, 64)
            if cls_buf.value in _SHELL_CLASSES:
                return True
            pid = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if is_own_host_window(hwnd or 0, pid.value, own_pid, console_hwnd, ancestors):
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)

            covers = None
            if user32.IsIconic(hwnd):
                state = "minimized"
            else:
                state = "maximized" if user32.IsZoomed(hwnd) else "normal"
                rect = wintypes.RECT()
                hmon = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
                mon = monitor_rect.get(hmon or 0)
                if mon is not None and user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    ix = max(0, min(rect.right, mon[2]) - max(rect.left, mon[0]))
                    iy = max(0, min(rect.bottom, mon[3]) - max(rect.top, mon[1]))
                    area = (mon[2] - mon[0]) * (mon[3] - mon[1])
                    if area > 0 and ix * iy >= _COVER_FRACTION * area:
                        covers = screen_number.get(hmon)
            found.append(
                WindowInfo(
                    title=buf.value,
                    exe=_exe_name(pid.value),
                    state=state,
                    focused=bool(foreground) and hwnd == foreground,
                    covers_screen=covers,
                )
            )
        except Exception:  # noqa: BLE001 - skip this window, keep enumerating
            logger.debug("window enumeration skipped one window", exc_info=True)
        return True

    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(enum_proc(_on_window), 0)
    return found


def describe_windows(max_windows: int = 8) -> str | None:
    """Return the open-window summary, or None off Windows / on any failure."""
    if sys.platform != "win32":
        return None
    start = time.perf_counter()
    try:
        text = format_windows(_enumerate_windows(max_windows), max_windows)
    except Exception:  # noqa: BLE001
        logger.debug("describe_windows failed", exc_info=True)
        return None
    logger.debug("describe_windows took %.1f ms", (time.perf_counter() - start) * 1000)
    return text
