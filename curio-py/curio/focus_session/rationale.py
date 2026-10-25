"""One-line "why?" summaries of docs/focus-learning-research.md sections.

Intervention.rationale carries a section letter ("C", or "C, D"); the bubble's
"why?" link shows these lines. Keep them in step with the research doc and
never add a productivity claim the doc doesn't make.
"""

from __future__ import annotations

import re

SECTION_SUMMARIES: dict[str, str] = {
    "A": "If-then plans made at the start help people follow through on goals.",
    "B": "Curio only looks at the app and window title, and your corrections always win.",
    "C": "Curio waits for a natural pause before checking in, and offers choices, not orders.",
    "D": "Noting where you were and what's next makes it easier to pick the task back up.",
    "E": "Regular short breaks tend to leave people less tired; they're about energy, not output.",
    "F": "Seeing your own progress written down helps you stick to a goal.",
    "G": "Hints before answers and short quizzes with feedback help you remember it later.",
    "H": "The pet is just company while you work; it isn't a proven focus aid.",
}

_LETTER_RE = re.compile(r"\b([A-H])\b")


def why_text(rationale: str) -> str:
    """Summary lines for every section letter in ``rationale``, or a fallback."""
    letters = dict.fromkeys(_LETTER_RE.findall(rationale.upper()))
    lines = [SECTION_SUMMARIES[letter] for letter in letters]
    return " ".join(lines) or "Part of the focus session you set up."
