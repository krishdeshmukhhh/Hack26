"""Intervention wording: autonomy-supportive templates, rotation, model rephrasing.

Every template offers a choice instead of giving an order (research doc,
section C). Templates are formatted with the learner's own words: {goal},
{cue}, {response}, {where} and {next}. Window titles never appear in a
message, so a rephrased message never sends one to the model.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable, Mapping

from curio.focus_contract import InterventionKind, ModelCall

NOT_A_DISTRACTION = "not a distraction"

# Word-bounded, case-insensitive. Used on every template (tests) and on every
# model rephrasing (runtime). The learner's own if-then words are not checked:
# "close it and stop scrolling" is their plan, quoted back to them.
BANNED_PHRASES: tuple[str, ...] = (
    "stop",
    "quit",
    "you must",
    "you should",
    "you shouldn't",
    "you need to",
    "you have to",
    "you'd better",
    "must",
    "don't",
    "do not",
    "get back to work",
    "focus up",
    "pay attention",
    "no more",
    "immediately",
    "right now",
    "enough",
    "lazy",
    "waste",
    "wasted",
    "wasting",
    "again?",
    "distracted again",
    "procrastinat",
    "productive",
    "productivity",
    "failed",
    "disappointed",
)

_BANNED_PATTERN = re.compile(
    "|".join(
        rf"\b{re.escape(phrase)}" + ("" if phrase.endswith(("?", "procrastinat")) else r"\b")
        for phrase in BANNED_PHRASES
    ),
    re.IGNORECASE,
)


def controlling_phrases(text: str) -> list[str]:
    """Return the banned phrases found in ``text`` (empty when it's fine)."""
    normalized = text.replace("’", "'")
    return [match.group(0).lower() for match in _BANNED_PATTERN.finditer(normalized)]


# Variants per kind, rotated in order. Keys are the fields a variant needs; the
# policy only picks variants whose fields it can fill.
TEMPLATES: Mapping[InterventionKind, tuple[str, ...]] = {
    InterventionKind.AMBIENT_CUE: (),  # pet animation only, nothing spoken
    InterventionKind.CHECK_IN: (
        "still on {goal}? we can get back to it, or take a real break.",
        "quick check: is this part of {goal}? happy to help you jump back in, or a break works.",
        "how's {goal} going? want to pick it back up, or would a proper break feel better?",
    ),
    InterventionKind.PLAN_REMINDER: (
        "you planned: if {cue}, then {response}. want to try that now?",
        "earlier you said: if {cue}, {response}. feel like giving it a go?",
    ),
    InterventionKind.RESUME: (
        "welcome back. you were on {where}, about to {next}.",
        "you were on {where}, about to {next}. want to pick it up from there?",
    ),
    InterventionKind.BREAK_START: (
        "time for a five-minute break, want to stretch?",
        "you've been at it a while. a short break could help you feel fresher, want one?",
        "good moment for a breather. want to stand up and stretch for a few minutes?",
    ),
    InterventionKind.BREAK_END: (
        "break's over whenever you're ready. you were on {where}, about to {next}.",
        "feeling rested? when you're ready: you were on {where}, about to {next}.",
    ),
    InterventionKind.METACOGNITIVE: (),  # phase-specific, see METACOGNITIVE_TEMPLATES
    InterventionKind.REFLECTION: (
        "what got in the way today, if anything?",
        "looking back, what helped and what got in the way?",
    ),
    InterventionKind.REVIEW: (),  # owned by the study coach
}

# Resume variants when only the plan is known (no "next" step).
PLAN_ONLY_TEMPLATES: Mapping[InterventionKind, tuple[str, ...]] = {
    InterventionKind.RESUME: (
        "welcome back. you were working on {where}.",
        "you were working on {where}. want to pick it up from there?",
    ),
    InterventionKind.BREAK_END: (
        "break's over whenever you're ready. you were working on {where}.",
        "feeling rested? when you're ready, {where} is waiting.",
    ),
}

METACOGNITIVE_TEMPLATES: Mapping[str, tuple[str, ...]] = {
    "start": (
        "before we start on {goal}: what's the first thing you'll do?",
        "for {goal}, what would a good first step be?",
    ),
    "halfway": (
        "about halfway through. how's it going against the plan?",
        "we're near the middle of the session. is {goal} going the way you expected?",
    ),
    "ending": (
        "we're almost at the end. how did {goal} go against the plan?",
        "nearly time. how close did you get to {goal}?",
    ),
}

CHOICES: Mapping[InterventionKind, tuple[str, ...]] = {
    InterventionKind.AMBIENT_CUE: ("back to it", NOT_A_DISTRACTION),
    InterventionKind.CHECK_IN: ("back to it", "take a break", NOT_A_DISTRACTION),
    InterventionKind.PLAN_REMINDER: ("back to it", "take a break", NOT_A_DISTRACTION),
    InterventionKind.RESUME: ("thanks", NOT_A_DISTRACTION),
    InterventionKind.BREAK_START: ("start break", "keep going"),
    InterventionKind.BREAK_END: ("back to it", "a few more minutes"),
    InterventionKind.METACOGNITIVE: ("answer", "skip"),
    InterventionKind.REFLECTION: ("answer", "skip"),
}

# Kinds whose rotated variants are announced once (HabitLab, section C).
ANNOUNCED_KINDS: frozenset[InterventionKind] = frozenset(
    {InterventionKind.CHECK_IN, InterventionKind.PLAN_REMINDER}
)
NEW_STYLE_NOTICE = "trying a new style of check-in. "


def all_templates() -> list[str]:
    """Every spoken or displayed template string, for wording tests."""
    texts: list[str] = []
    for table in (TEMPLATES, PLAN_ONLY_TEMPLATES, METACOGNITIVE_TEMPLATES):
        for variants in table.values():
            texts.extend(variants)
    for choices in CHOICES.values():
        texts.extend(choices)
    texts.append(NEW_STYLE_NOTICE)
    return texts


class MessageBook:
    """Rotates variants per kind and announces a new variant the first time."""

    def __init__(self, seen_variants: Iterable[str] = ()) -> None:
        self._next_index: dict[str, int] = {}
        self._seen: set[str] = set(seen_variants)

    @property
    def seen_variants(self) -> frozenset[str]:
        """Variant keys already shown; persist and pass back to keep notices one-time."""
        return frozenset(self._seen)

    def render(
        self,
        kind: InterventionKind,
        fields: Mapping[str, str],
        *,
        variants: tuple[str, ...] | None = None,
        family: str = "",
    ) -> str:
        options = TEMPLATES[kind] if variants is None else variants
        family_key = f"{kind.value}:{family}" if family else kind.value
        index = self._next_index.get(family_key, 0) % len(options)
        self._next_index[family_key] = index + 1
        variant_key = f"{family_key}:{index}"
        first_time = variant_key not in self._seen
        kind_seen_before = any(key.startswith(f"{family_key}:") for key in self._seen)
        self._seen.add(variant_key)
        text = options[index].format(**fields)
        if kind in ANNOUNCED_KINDS and first_time and kind_seen_before:
            text = NEW_STYLE_NOTICE + text
        return text


# --- Model rephrasing -----------------------------------------------------------

REPHRASE_SYSTEM_PROMPT = (
    "You rephrase one short message from a friendly study companion. Keep the "
    "meaning, the learner's own words and any question. Offer choices; never give "
    "orders, never say 'stop', 'you must' or 'you should', no guilt, no "
    "productivity claims. Lowercase, one sentence or two, under 25 words. Reply "
    "with the rephrased message only."
)
MAX_REPHRASE_CHARS = 180
MAX_REPHRASE_WORDS = 30
_MARKUP = re.compile(r"[<>*_`#\[\]{}]|https?://", re.IGNORECASE)


def validate_rephrase(text: str, *, original: str) -> str | None:
    """Return a cleaned rephrasing, or ``None`` if it can't be used."""
    cleaned = " ".join(text.split()).strip().strip("\"'").strip()
    if not cleaned or len(cleaned) > MAX_REPHRASE_CHARS:
        return None
    if len(cleaned.split()) > MAX_REPHRASE_WORDS:
        return None
    if _MARKUP.search(cleaned) or controlling_phrases(cleaned):
        return None
    if "?" in original and "?" not in cleaned:
        return None  # a question became a statement; it may have become an order
    return cleaned


async def rephrase(model: ModelCall | None, message: str, *, timeout_seconds: float = 4.0) -> str:
    """Ask the model for a fresh wording; fall back to the template on any problem."""
    if model is None:
        return message
    try:
        reply = await asyncio.wait_for(
            model(REPHRASE_SYSTEM_PROMPT, message), timeout=timeout_seconds
        )
    except Exception:  # any model failure means "use the template"
        return message
    return validate_rephrase(reply, original=message) or message
