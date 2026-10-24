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


@dataclass(frozen=True, slots=True)
class StepTag:
    """Position in a guided walkthrough: step ``index`` of an estimated ``total``."""

    index: int
    total: int

    @property
    def has_more(self) -> bool:
        return self.index < self.total


_STEP_RE = re.compile(r"\s*\[STEP:\s*(\d+)\s*/\s*(\d+)\s*\]")
# Any complete control tag, or an unfinished one at the very end of a
# still-streaming response (e.g. "... [POI").
_ANY_TAG_RE = re.compile(r"\s*\[(?:POINT|STEP):[^\]]*\]")
_PARTIAL_TAG_RE = re.compile(r"\s*\[(?:[A-Z]{0,5}|(?:POINT|STEP):[^\]]*)$")


def parse_step_tag(response: str) -> tuple[str, StepTag | None]:
    """Remove a [STEP:k/n] tag from anywhere in the response.

    Returns (response_without_tag, tag_or_none). Run this before
    ``parse_point_tag``, which expects the POINT tag at the very end.
    """
    m = _STEP_RE.search(response)
    if not m:
        return (response, None)
    index, total = int(m.group(1)), int(m.group(2))
    rest = (response[: m.start()] + response[m.end():]).rstrip()
    if index < 1:
        return (rest, None)
    return (rest, StepTag(index=index, total=max(total, index)))


def strip_tags_for_display(text: str) -> str:
    """Text safe to show on screen: control tags removed, even half-streamed ones."""
    text = _ANY_TAG_RE.sub("", text)
    return _PARTIAL_TAG_RE.sub("", text).strip()
