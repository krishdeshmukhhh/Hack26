"""Time-based, bounded pursuit with a brief pause before choosing to follow."""

from __future__ import annotations

import math


class PursuitMotion:
    """Move independently toward the newest destination without queued paths.

    Bounds describe valid window origins, already reduced by the window size.
    POINT movement bypasses hesitation; reduced motion bypasses decorative travel.
    """

    def __init__(self) -> None:
        self.position = (0.0, 0.0)
        self.moving = False
        self._waiting = 0.0
        self._chasing = False
        self._arrived = False
        self.velocity = 0.0
        self._elapsed = 0.0
        self.just_arrived = False

    def reset(self) -> None:
        """Forget pursuit intent without changing the current ground position."""
        self.moving = False
        self._waiting = 0.0
        self._chasing = False
        self._arrived = False
        self.velocity = 0.0
        self._elapsed = 0.0
        self.just_arrived = False

    def update(
        self,
        dt: float,
        target: tuple[float, float],
        bounds: tuple[float, float, float, float],
        *,
        immediate: bool = False,
        reduced: bool = False,
        delay: float = 0.45,
        speed: float = 180.0,
        arrival_radius: float = 16.0,
    ) -> tuple[float, float]:
        dt = max(0.0, dt)
        arrival_radius = max(0.0, arrival_radius)
        left, top, right, bottom = bounds
        target = (max(left, min(right, target[0])), max(top, min(bottom, target[1])))
        x, y = self.position
        self.moving = False
        self.just_arrived = False
        if reduced or not (left <= x <= right and top <= y <= bottom):
            self.position = target
            self.reset()
            self._arrived = True
            return self.position

        distance = math.dist(self.position, target)
        threshold = arrival_radius + (12.0 if self._arrived and not immediate else 0.0)
        if distance <= arrival_radius + 1e-8:
            self.reset()
            self._arrived = True
            return self.position
        if not self._chasing and distance <= threshold:
            self._waiting = 0.0
            return self.position

        elapsed_before = self._elapsed
        self._elapsed += dt
        travel_dt = dt
        if immediate:
            self._chasing = True
            self._waiting = 0.0
        elif not self._chasing:
            previous_wait = self._waiting
            self._waiting += dt
            if self._waiting <= max(0.0, delay):
                return self.position
            self._chasing = True
            self._arrived = False
            # Only elapsed time after hesitation is available for movement.
            travel_dt = max(0.0, dt - max(0.0, delay - previous_wait))

        # Catch up faster at long distances, ramping rather than snapping speed.
        # Walking is retained nearby; distance and a five-second budget drive catch-up.
        base = max(0.0, speed)
        boost = 1.0 + min(9.0, max(0.0, distance - 240.0) / 220.0)
        desired = base * boost * min(1.0, distance / (arrival_radius + 60.0))
        remaining = max(travel_dt, 5.0 - elapsed_before)
        required = 2.0 * max(0.0, distance - arrival_radius) / max(remaining, 1e-9)
        desired = max(desired, required)
        rate = max(base * 12.0, required * 4.0) if desired > self.velocity else base * 20.0
        change = max(-rate * travel_dt, min(rate * travel_dt, desired - self.velocity))
        self.velocity += change
        # After ramp-up, keep enough progress to meet the original deadline.
        # Updating the cursor never queues work or restarts the budget.
        if self._elapsed >= 1.0:
            self.velocity = max(self.velocity, required)
        travel = min(max(0.0, distance - arrival_radius), self.velocity * travel_dt)
        if travel > 0.0:
            self.position = (
                max(left, min(right, x + (target[0] - x) * travel / distance)),
                max(top, min(bottom, y + (target[1] - y) * travel / distance)),
            )
            self.moving = True
        if math.dist(self.position, target) <= arrival_radius + 1e-8:
            self.reset()
            self._arrived = True
            self.just_arrived = True
        return self.position
