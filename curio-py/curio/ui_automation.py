"""Snap a model-provided POINT onto a real UI element via Windows UI Automation.

The local VLM often lands a few pixels (or a whole control) away from what it meant.
Given the point and its label, we look for nearby clickable elements whose accessible
name resembles the label and move the point to that element's center. Anything
uncertain returns None so the caller keeps the model's original point.

Coordinates are PHYSICAL screen pixels (what ``map_point_to_screen`` returns, from mss),
which is also what UIA reports for a DPI-aware process.

The selection logic is pure (``choose_snap``) and testable with fake candidates; the COM
work runs on one dedicated worker thread (MTA) and is bounded by a timeout.
"""

from __future__ import annotations

import asyncio
import difflib
import logging
import os
import re
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 0.15
SEARCH_RADIUS_PX = 120
MIN_SIMILARITY = 0.5
# Inside the element's rect the match may be looser: the model clearly meant this area.
MIN_INSIDE_SIMILARITY = 0.3
# Candidates this far from the point (fraction of the radius) need a near-exact name match.
FAR_FRACTION = 0.5
FAR_MIN_SIMILARITY = 0.75
# Elements wider/taller than this keep the model's coordinate on that axis.
MAX_SNAP_EXTENT_PX = 300
_NAME_MAX_LOG = 40

_STOPWORDS = frozenset({
    "icon", "button", "the", "a", "an", "tab", "menu", "link", "field", "box", "option",
    "item", "in", "of", "on", "to", "app", "bar", "toolbar", "label", "text", "area",
    "at", "for", "and", "window", "shortcut", "pinned", "running",
})


@dataclass(frozen=True)
class Candidate:
    """A UI element near the point: accessible name plus screen rect (physical px)."""

    name: str
    left: int
    top: int
    right: int
    bottom: int
    kind: str = ""

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom

    def distance_to(self, x: int, y: int) -> float:
        dx = max(self.left - x, 0, x - self.right)
        dy = max(self.top - y, 0, y - self.bottom)
        return (dx * dx + dy * dy) ** 0.5


@dataclass(frozen=True)
class SnapResult:
    x: int
    y: int
    name: str
    similarity: float
    elapsed_ms: float = 0.0


# ---------------------------------------------------------------------------
# Pure scoring / selection
# ---------------------------------------------------------------------------


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    kept = [w for w in words if w not in _STOPWORDS]
    return kept or words


def name_similarity(label: str, name: str) -> float:
    """0..1: how well an element name matches the model's label.

    Combines label-token coverage (every label word found in the name, allowing prefixes)
    with a whole-string difflib ratio, so "chrome icon" matches
    "Google Chrome - 1 running window".
    """
    label_tokens = _tokens(label)
    name_tokens = _tokens(name)
    if not label_tokens or not name_tokens:
        return 0.0
    hits = 0.0
    for lt in label_tokens:
        best = 0.0
        for nt in name_tokens:
            if lt == nt:
                best = 1.0
                break
            if len(lt) >= 3 and (nt.startswith(lt) or lt.startswith(nt)) and len(nt) >= 3:
                best = max(best, 0.85)
            else:
                fuzzy = difflib.SequenceMatcher(None, lt, nt).ratio()
                if fuzzy >= 0.8:  # typos/plurals only; "chrome" must not match "pycharm"
                    best = max(best, fuzzy * 0.9)
        hits += best
    coverage = hits / len(label_tokens)
    ratio = difflib.SequenceMatcher(None, " ".join(label_tokens), " ".join(name_tokens)).ratio()
    return max(coverage if coverage >= 0.5 else coverage * 0.8, ratio if ratio >= 0.6 else 0.0)


def _target_for(c: Candidate, x: int, y: int) -> tuple[int, int]:
    cx, cy = (c.left + c.right) // 2, (c.top + c.bottom) // 2
    if c.width > MAX_SNAP_EXTENT_PX:
        cx = min(max(x, c.left), c.right - 1)
    if c.height > MAX_SNAP_EXTENT_PX:
        cy = min(max(y, c.top), c.bottom - 1)
    return cx, cy


def choose_snap(
    x: int,
    y: int,
    label: str,
    candidates: list[Candidate],
    *,
    radius: int = SEARCH_RADIUS_PX,
    min_similarity: float = MIN_SIMILARITY,
) -> tuple[Candidate, float] | None:
    """Pick the best candidate for the model's point, or None to keep the point."""
    best: tuple[float, Candidate, float] | None = None
    for c in candidates:
        if c.width <= 0 or c.height <= 0 or not c.name.strip():
            continue
        sim = name_similarity(label, c.name)
        dist = c.distance_to(x, y)
        inside = c.contains(x, y)
        if inside:
            if sim < MIN_INSIDE_SIMILARITY:
                continue
        else:
            if dist > radius or sim < min_similarity:
                continue
            if dist > radius * FAR_FRACTION and sim < FAR_MIN_SIMILARITY:
                continue
        score = sim - 0.5 * (dist / radius)
        if inside:
            # Prefer the tightest enclosing element over a large container.
            score += 0.1 - min(c.width * c.height / 1_000_000, 0.1)
        if best is None or score > best[0]:
            best = (score, c, sim)
    if best is None:
        return None
    return best[1], best[2]


def _clip(name: str) -> str:
    name = " ".join(name.split())
    return name if len(name) <= _NAME_MAX_LOG else name[: _NAME_MAX_LOG - 1] + "…"


# ---------------------------------------------------------------------------
# UIA backend (comtypes)
# ---------------------------------------------------------------------------

# ControlType ids we treat as click targets.
_TARGET_TYPES = {
    50000: "Button", 50002: "CheckBox", 50003: "ComboBox", 50004: "Edit", 50005: "Hyperlink",
    50007: "ListItem", 50011: "MenuItem", 50013: "RadioButton", 50019: "TabItem",
    50024: "TreeItem", 50029: "DataItem", 50031: "SplitButton",
}
_UIA_ControlTypePropertyId = 30003
_UIA_IsOffscreenPropertyId = 30022
_UIA_NamePropertyId = 30005
_UIA_BoundingRectanglePropertyId = 30001
_UIA_WindowControlTypeId = 50032
_TreeScope_Descendants = 4
_MIN_CONTAINER_COVERAGE = 0.25


class _OwnWindow(Exception):
    pass


class _Backend:
    """Holds the IUIAutomation instance for the worker thread."""

    def __init__(self) -> None:
        import comtypes.client

        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as uia

        self.uia = uia
        self.auto = comtypes.client.CreateObject(
            uia.CUIAutomation, interface=uia.IUIAutomation
        )
        self.walker = self.auto.ControlViewWalker
        cache = self.auto.CreateCacheRequest()
        for prop in (
            _UIA_NamePropertyId, _UIA_ControlTypePropertyId, _UIA_BoundingRectanglePropertyId,
            _UIA_IsOffscreenPropertyId,
        ):
            cache.AddProperty(prop)
        self.cache = cache
        cond = None
        for type_id in _TARGET_TYPES:
            c = self.auto.CreatePropertyCondition(_UIA_ControlTypePropertyId, type_id)
            cond = c if cond is None else self.auto.CreateOrCondition(cond, c)
        onscreen = self.auto.CreatePropertyCondition(_UIA_IsOffscreenPropertyId, False)
        self.find_cond = self.auto.CreateAndCondition(cond, onscreen)

    @staticmethod
    def _rect_of(el) -> tuple[int, int, int, int]:
        r = el.CurrentBoundingRectangle
        return int(r.left), int(r.top), int(r.right), int(r.bottom)

    def _candidate(self, el, cached: bool) -> Candidate | None:
        try:
            ctype = el.CachedControlType if cached else el.CurrentControlType
            if ctype not in _TARGET_TYPES:
                return None
            name = el.CachedName if cached else el.CurrentName
            r = el.CachedBoundingRectangle if cached else el.CurrentBoundingRectangle
            if not name or r.right <= r.left or r.bottom <= r.top:
                return None
            return Candidate(
                name, int(r.left), int(r.top), int(r.right), int(r.bottom),
                _TARGET_TYPES[ctype],
            )
        except Exception:  # noqa: BLE001 - elements vanish mid-query
            return None

    def collect(self, x: int, y: int, radius: int, deadline: float) -> list[Candidate]:
        from ctypes import wintypes

        pt = wintypes.POINT(x, y)
        el = self.auto.ElementFromPoint(pt)
        if not el:
            return []
        if el.CurrentProcessId == os.getpid():
            raise _OwnWindow
        out: list[Candidate] = []
        c = self._candidate(el, cached=False)
        if c is not None:
            out.append(c)

        # Ancestor chain up to the top-level window (stop there, never the desktop root).
        chain = [el]
        cur = el
        for _ in range(30):
            if cur.CurrentControlType == _UIA_WindowControlTypeId:
                break
            parent = self.walker.GetParentElement(cur)
            if not parent:
                break
            chain.append(parent)
            cur = parent
            if time.monotonic() > deadline:
                return out
        for anc in chain[1:]:
            c = self._candidate(anc, cached=False)
            if c is not None:
                out.append(c)

        # Search the smallest ancestor that spans a useful part of the search square
        # (clipped to the top-level window), so big windows stay cheap. Any strictly
        # smaller ancestor is a toolbar/list/pane around the point.
        wl, wt, wr, wb = self._rect_of(chain[-1])
        sl, st = max(x - radius, wl), max(y - radius, wt)
        sr, sb = min(x + radius, wr), min(y + radius, wb)
        square = max((sr - sl) * (sb - st), 1)
        container = chain[-1]
        for anc in chain[1:]:
            lf, t, r, b = self._rect_of(anc)
            iw, ih = min(r, sr) - max(lf, sl), min(b, sb) - max(t, st)
            if iw > 0 and ih > 0 and iw * ih >= _MIN_CONTAINER_COVERAGE * square:
                container = anc
                break
        if time.monotonic() > deadline:
            return out
        found = container.FindAllBuildCache(_TreeScope_Descendants, self.find_cond, self.cache)
        for i in range(found.Length):
            c = self._candidate(found.GetElement(i), cached=True)
            if c is not None and c.distance_to(x, y) <= radius and c not in out:
                out.append(c)
        return out


_executor: ThreadPoolExecutor | None = None
_inflight = 0  # jobs queued/running on the single UIA thread
_inflight_lock = threading.Lock()
_backend: _Backend | None = None


def _init_thread() -> None:
    """Worker-thread initializer: join the COM multithreaded apartment."""
    try:
        if "comtypes" not in sys.modules:
            # comtypes initializes COM on first import; ask for MTA (0) on this thread.
            sys.coinit_flags = 0
            import comtypes  # noqa: F401
        else:
            import ctypes

            ctypes.windll.ole32.CoInitializeEx(None, 0x0)  # COINIT_MULTITHREADED
    except Exception:  # noqa: BLE001
        pass


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="uia", initializer=_init_thread
        )
    return _executor


def _get_backend() -> _Backend:
    global _backend
    if _backend is None:
        _backend = _Backend()
    return _backend


def _inflight_add(delta: int) -> None:
    global _inflight
    with _inflight_lock:
        _inflight += delta


def prewarm() -> None:
    """Load the UIA type library and create the automation object off the Qt thread."""
    if sys.platform != "win32":
        return
    # Counted as in-flight so a user turn never queues behind the slow first load.
    _inflight_add(1)
    try:
        cf = _get_executor().submit(_safe_get_backend)
    except Exception:  # noqa: BLE001
        _inflight_add(-1)
        return
    cf.add_done_callback(lambda _f: _inflight_add(-1))


def _safe_get_backend() -> None:
    try:
        _get_backend()
    except Exception as exc:  # noqa: BLE001
        logger.info("UIA prewarm failed: %s", exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

CollectFn = Callable[[int, int, int, float], list[Candidate]]


def _snap_sync(
    x: int, y: int, label: str, timeout_s: float, collect: CollectFn | None
) -> tuple[SnapResult | None, str]:
    start = time.monotonic()
    deadline = start + timeout_s
    try:
        fn = collect or _get_backend().collect
        candidates = fn(x, y, SEARCH_RADIUS_PX, deadline)
        picked = choose_snap(x, y, label, candidates)
    except _OwnWindow:
        return None, "own window"
    except Exception as exc:  # noqa: BLE001
        return None, f"error {type(exc).__name__}"
    ms = (time.monotonic() - start) * 1000
    if picked is None:
        return None, "no match"
    c, sim = picked
    nx, ny = _target_for(c, x, y)
    return SnapResult(nx, ny, c.name, sim, ms), ""


async def snap_point(
    x: int,
    y: int,
    label: str,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    collect: CollectFn | None = None,
) -> SnapResult | None:
    """Snap (x, y) onto the UI element named like ``label``; None keeps the original.

    Never raises and never blocks the event loop; a slow UIA tree just times out.
    ``collect`` replaces the UIA backend (tests).
    """
    start = time.monotonic()

    def _ms() -> float:
        return (time.monotonic() - start) * 1000

    if collect is None and sys.platform != "win32":
        return None
    with _inflight_lock:
        busy = _inflight > 0
    if busy:
        # A timed-out tree walk (or the prewarm) still owns the UIA thread.
        logger.info("POINT snap: none (busy, %.0f ms)", _ms())
        return None
    _inflight_add(1)
    try:
        cf = _get_executor().submit(_snap_sync, x, y, label, timeout_s, collect)
    except Exception as exc:  # noqa: BLE001
        _inflight_add(-1)
        logger.info("POINT snap: none (error %s, %.0f ms)", type(exc).__name__, _ms())
        return None
    # Fires on completion and on cancel (job still queued when the wait times out).
    cf.add_done_callback(lambda _f: _inflight_add(-1))
    try:
        result, reason = await asyncio.wait_for(asyncio.wrap_future(cf), timeout_s + 0.05)
    except TimeoutError:
        logger.info("POINT snap: none (timeout, %.0f ms)", _ms())
        return None
    except Exception as exc:  # noqa: BLE001
        logger.info("POINT snap: none (error %s, %.0f ms)", type(exc).__name__, _ms())
        return None
    if result is None:
        logger.info("POINT snap: none (%s, %.0f ms)", reason, _ms())
        return None
    logger.info(
        'POINT snap: (%d,%d) -> (%d,%d) "%s" (%.0f ms)',
        x, y, result.x, result.y, _clip(result.name), _ms(),
    )
    return result
