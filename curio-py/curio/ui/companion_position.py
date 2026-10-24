from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CompanionPlacement:
    x: int
    y: int
    flipped_x: bool
    flipped_y: bool


def compute_position(
    cursor_x: int,
    cursor_y: int,
    screen_rect: tuple[int, int, int, int],  # (left, top, width, height)
    companion_size: tuple[int, int],  # (width, height)
    offset: int = 20,
    edge_margin: int = 80,
) -> CompanionPlacement:
    """Compute companion widget position relative to cursor with edge-flipping."""
    screen_left, screen_top, screen_w, screen_h = screen_rect
    screen_right = screen_left + screen_w
    screen_bottom = screen_top + screen_h
    comp_w, comp_h = companion_size

    # Flip when cursor is within edge_margin of screen edge
    flipped_x = (screen_right - cursor_x) < edge_margin
    flipped_y = (screen_bottom - cursor_y) < edge_margin

    if flipped_x:
        x = cursor_x - offset - comp_w
    else:
        x = cursor_x + offset

    if flipped_y:
        y = cursor_y - offset - comp_h
    else:
        y = cursor_y + offset

    return CompanionPlacement(x=x, y=y, flipped_x=flipped_x, flipped_y=flipped_y)


def should_update(
    prev_x: int, prev_y: int, cur_x: int, cur_y: int, dead_zone: int = 3
) -> bool:
    """Return True if cursor moved more than dead_zone pixels from previous position."""
    dx = cur_x - prev_x
    dy = cur_y - prev_y
    return math.hypot(dx, dy) > dead_zone
