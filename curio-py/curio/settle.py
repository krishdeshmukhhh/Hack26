"""Adaptive wait after a walkthrough click: continue once the screen has settled.

Polls a cheap downscaled grab of the target monitor. Returns as soon as the
screen visibly changed and then stayed stable (menus finished animating), never
before ``SETTLE_MIN_SECONDS`` and never after ``SETTLE_MAX_SECONDS``. If nothing
changes it waits the full maximum, like the old fixed delay.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

SETTLE_BASELINE_DELAY = 0.03  # let our own spotlight finish hiding before the baseline
SETTLE_START_DELAY = 0.15     # first comparison this long after the click
SETTLE_POLL_SECONDS = 0.1
SETTLE_STABLE_SECONDS = 0.15  # no change for this long after a change = settled
SETTLE_MIN_SECONDS = 0.25
SETTLE_MAX_SECONDS = 0.8
# Our companion and pill animate around the cursor; ignore that area (screen px).
SETTLE_MASK_RADIUS_PX = 200


async def wait_for_settle(
    grab: Callable[[], Awaitable[Any | None]],
    *,
    max_seconds: float = SETTLE_MAX_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> float:
    """Wait for the screen to settle; returns the seconds waited.

    ``grab`` returns frames with ``differs_from(other) -> bool`` (or None when
    grabbing fails, which degrades to the fixed ``max_seconds`` wait).
    Cancellation propagates from ``sleep``/``grab``.
    """
    t0 = clock()

    async def safe_grab() -> Any | None:
        try:
            return await grab()
        except Exception as exc:  # noqa: BLE001 - probing must never break a turn
            logger.debug("settle probe failed: %s", exc)
            return None

    async def finish() -> float:
        remaining = max_seconds - (clock() - t0)
        if remaining > 0:
            await sleep(remaining)
        return clock() - t0

    await sleep(SETTLE_BASELINE_DELAY)
    prev = await safe_grab()
    if prev is None:
        return await finish()
    wait = SETTLE_START_DELAY - (clock() - t0)
    if wait > 0:
        await sleep(wait)

    changed = False
    last_change = t0
    while True:
        frame = await safe_grab()
        now = clock()
        if frame is not None:
            if frame.differs_from(prev):
                changed = True
                last_change = now
            prev = frame
        elapsed = now - t0
        if changed and now - last_change >= SETTLE_STABLE_SECONDS and elapsed >= SETTLE_MIN_SECONDS:
            return elapsed
        if elapsed + SETTLE_POLL_SECONDS > max_seconds:
            return await finish()
        await sleep(SETTLE_POLL_SECONDS)
