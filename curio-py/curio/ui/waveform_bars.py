"""Diamond-shaped waveform bar height calculator."""

from __future__ import annotations

DIAMOND_WEIGHTS: tuple[float, ...] = (0.5, 0.7, 0.9, 1.0, 1.0, 0.9, 0.7, 0.5)
BAR_COUNT: int = 8


def compute_bar_heights(
    rms: float, max_height: float, min_height: float = 2.0
) -> list[float]:
    """Compute 8 bar heights from RMS level in a diamond pattern.

    Args:
        rms: Audio RMS level, clamped to [0.0, 1.0].
        max_height: Maximum bar height in pixels.
        min_height: Minimum bar height in pixels (visible even when silent).

    Returns:
        List of 8 float heights.
    """
    rms = max(0.0, min(1.0, rms))
    return [max(min_height, rms * w * max_height) for w in DIAMOND_WEIGHTS]
