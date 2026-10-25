"""Geometry for the companion's flights.

The companion flies along a quadratic bezier arc that bows upward, eases in
and out with smoothstep, turns the triangle to face its direction of travel,
and swells to 1.3x at the midpoint. Flight time scales with distance.
These are pure functions so they can be unit-tested without a window.
"""

from __future__ import annotations

import math

Point = tuple[float, float]

# Where the companion sits relative to the mouse cursor.
FOLLOW_OFFSET = (35, 25)
# Land beside the target rather than on top of it.
LANDING_OFFSET = (8, 12)
# Triangle angle when not flying: tip up-left like a mouse pointer.
REST_ROTATION_DEGREES = -35.0
# During the return flight, moving the mouse this far cancels it.
RETURN_CANCEL_DISTANCE = 100.0


def flight_duration_seconds(start: Point, end: Point) -> float:
    """Short hops are quick, long flights more dramatic: 0.6-1.4 s."""
    distance = math.dist(start, end)
    return min(max(distance / 800.0, 0.6), 1.4)


def arc_control_point(start: Point, end: Point) -> Point:
    """Bezier control point above the midpoint, so the path bows upward."""
    distance = math.dist(start, end)
    arc_height = min(distance * 0.2, 80.0)
    return ((start[0] + end[0]) / 2, (start[1] + end[1]) / 2 - arc_height)


def smoothstep(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)


def flight_frame(start: Point, end: Point, linear_progress: float) -> tuple[Point, float, float]:
    """Position, triangle rotation (degrees) and scale at ``linear_progress`` in 0..1."""
    p = max(0.0, min(1.0, linear_progress))
    control = arc_control_point(start, end)
    t = smoothstep(p)
    u = 1.0 - t
    x = u * u * start[0] + 2 * u * t * control[0] + t * t * end[0]
    y = u * u * start[1] + 2 * u * t * control[1] + t * t * end[1]
    # Face along the curve's tangent; +90 because the triangle's tip points
    # up at 0 degrees while atan2 gives 0 for rightward motion.
    tangent_x = 2 * u * (control[0] - start[0]) + 2 * t * (end[0] - control[0])
    tangent_y = 2 * u * (control[1] - start[1]) + 2 * t * (end[1] - control[1])
    if tangent_x == 0 and tangent_y == 0:
        rotation = REST_ROTATION_DEGREES
    else:
        rotation = math.degrees(math.atan2(tangent_y, tangent_x)) + 90.0
    scale = 1.0 + math.sin(p * math.pi) * 0.3
    return (x, y), rotation, scale


def follow_center(
    cursor: Point, screen: tuple[int, int, int, int], margin: int = 24
) -> Point:
    """Companion centre beside the cursor, flipped to stay on screen.

    ``screen`` is (left, top, width, height).
    """
    left, top, width, height = screen
    x = cursor[0] + FOLLOW_OFFSET[0]
    y = cursor[1] + FOLLOW_OFFSET[1]
    if x > left + width - margin:
        x = cursor[0] - FOLLOW_OFFSET[0]
    if y > top + height - margin:
        y = cursor[1] - FOLLOW_OFFSET[1]
    return (x, y)


def landing_point(
    target: Point, screen: tuple[int, int, int, int], padding: int = 20
) -> Point:
    """Where to land when pointing at ``target``: just below-right, kept on screen."""
    left, top, width, height = screen
    x = target[0] + LANDING_OFFSET[0]
    y = target[1] + LANDING_OFFSET[1]
    x = max(left + padding, min(x, left + width - padding))
    y = max(top + padding, min(y, top + height - padding))
    return (x, y)
