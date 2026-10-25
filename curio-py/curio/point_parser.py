from __future__ import annotations

import re
from dataclasses import dataclass

from curio.learning_contract import concept_key


@dataclass(frozen=True, slots=True)
class PointTag:
    x: int
    y: int
    label: str
    screen: int | None = None


_POINT_RE = re.compile(
    r"\[POINT:(?:none|(\d+)\s*,\s*(\d+)(?::([^\]:\s][^\]:]*?))?(?::screen(\d+))?)\]\s*$"
)


_POINT_ANYWHERE_RE = re.compile(
    r"\[POINT:(\d+)\s*,\s*(\d+)(?::([^\]:\s][^\]:]*?))?(?::screen(\d+))?\]"
)


def find_point_tag(text: str) -> PointTag | None:
    """Return the first complete [POINT:x,y...] tag anywhere in a (partial) stream."""
    m = _POINT_ANYWHERE_RE.search(text)
    if not m:
        return None
    return PointTag(
        x=int(m.group(1)),
        y=int(m.group(2)),
        label=m.group(3) or "",
        screen=int(m.group(4)) if m.group(4) else None,
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
_ANY_TAG_RE = re.compile(r"\s*\[(?:POINT|STEP|CONCEPTS):[^\]]*\]")
_PARTIAL_TAG_RE = re.compile(r"\s*\[(?:[A-Z]{0,8}|(?:POINT|STEP|CONCEPTS):[^\]]*)$")
_CONCEPTS_RE = re.compile(r"\s*\[CONCEPTS:([^\]]*)\]")
MAX_CONCEPTS = 3


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


def parse_concepts_tag(response: str) -> tuple[str, tuple[str, ...]]:
    """Remove a [CONCEPTS:a, b] tag from anywhere in the response.

    Returns (response_without_tag, concept_keys): at most three, normalised
    with ``concept_key``, duplicates and blanks dropped. Run this before
    ``parse_point_tag``, which expects the POINT tag at the very end.
    """
    m = _CONCEPTS_RE.search(response)
    if not m:
        return (response, ())
    rest = (response[: m.start()] + response[m.end():]).rstrip()
    concepts: list[str] = []
    for raw in m.group(1).split(","):
        key = concept_key(raw)
        if key and key not in concepts:
            concepts.append(key)
    return (rest, tuple(concepts[:MAX_CONCEPTS]))


def strip_tags_for_display(text: str) -> str:
    """Text safe to show on screen: control tags removed, even half-streamed ones."""
    text = _ANY_TAG_RE.sub("", text)
    return _PARTIAL_TAG_RE.sub("", text).strip()
