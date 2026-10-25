"""One visual language for the overlay: pointer pill, target ring, spotlight ring, flourish.

Defined once here so the pieces read as a single family in a screen recording.
"""

from __future__ import annotations

ACCENT = "#3380FF"  # DS.Colors.overlayCursorBlue in the Swift app
ERROR_RED = "#E5484D"

RING_WIDTH = 2.5        # px; target ring, spotlight ring and check flourish strokes
RIM_WIDTH = 1.5         # px; white rim around the pill and the triangle
GLOW_WIDTH = 9          # px; soft halo stroke behind the rings
GLOW_ALPHA = 0.5        # peak halo opacity for the pill (rings use a fraction of it)
CORNER_RADIUS = 8       # px; pill corners
