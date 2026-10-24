"""Active window title detection via Win32 API."""

from __future__ import annotations

import ctypes
import logging

logger = logging.getLogger(__name__)


def get_foreground_window_title() -> str:
    """Return the title of the current foreground window.

    Uses Win32 GetForegroundWindow + GetWindowTextW. Returns empty
    string if detection fails (e.g. no foreground window, or
    non-Windows platform).
    """
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return ""
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value
    except Exception:  # noqa: BLE001
        logger.debug("failed to get window title", exc_info=True)
        return ""
