from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PointTag:
    x: int
    y: int
    label: str
    screen: int | None = None


_POINT_RE = re.compile(
    r"\[POINT:(?:none|(\d+)\s*,\s*(\d+)(?::([^\]:\s][^\]:]*?))?(?::screen(\d+))?)\]\s*$"
)


def parse_point_tag(response: str) -> tuple[str, PointTag | None]:
    """Parse a POINT tag from end of response. Returns (spoken_text, tag_or_none)."""
    m = _POINT_RE.search(response)
    if not m:
        return (response, None)

    spoken = response[: m.start()].rstrip()

    # [POINT:none] case — all capture groups are None
    if m.group(1) is None:
        return (spoken, None)

    x = int(m.group(1))
    y = int(m.group(2))
    label = m.group(3) or ""
    screen = int(m.group(4)) if m.group(4) else None

    return (spoken, PointTag(x=x, y=y, label=label, screen=screen))
