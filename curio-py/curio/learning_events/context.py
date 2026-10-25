"""Prompt lines for the skill model's advice in one request."""

from __future__ import annotations

from curio.learning_contract import AssistanceLevel

_HINT_ONLY = (
    "the skill model suggests trying brief hints (an estimate, not verified knowledge): "
    "give a short spoken hint for each step and use "
    "[POINT:none] unless they ask where something is. keep the step tags."
)
_ASSISTANCE_LINES = {
    AssistanceLevel.NONE: _HINT_ONLY,
    AssistanceLevel.HINTED: _HINT_ONLY,
    AssistanceLevel.POINTED: None,
    AssistanceLevel.DID_IT: (
        "the skill model suggests more support (an estimate): "
        "keep each step small, say exactly what to click, "
        "and point at every step."
    ),
}


def assistance_line(level: AssistanceLevel) -> str | None:
    """One prompt line for the skill model's advice; None keeps the default (point)."""
    return _ASSISTANCE_LINES[level]


def learning_prompt_text(
    *,
    path_text: str | None,
    assistance: AssistanceLevel,
    skill_context: str | None,
) -> str | None:
    """Everything learned for this request, or None when there's nothing to add."""
    parts = []
    if path_text:
        parts.append(path_text)
    line = assistance_line(assistance)
    if line:
        parts.append(line)
    if skill_context:
        parts.append(f"estimated familiarity, not measured mastery: {skill_context.strip()}")
    return "\n\n".join(parts) if parts else None
