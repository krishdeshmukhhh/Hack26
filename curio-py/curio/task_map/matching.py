"""Loose task matching: token overlap plus difflib, standard library only.

Both sides go through ``task_key``, a small synonym table ("make" ≈ "create",
"turn on" ≈ "enable"), stopword removal and naive plural stripping. Tasks
that differ by an opposite verb ("enable" vs "disable") never match.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from curio.learning_contract import task_key

MATCH_THRESHOLD = 0.7
_OVERLAP_WEIGHT = 0.6  # the rest goes to SequenceMatcher on the canonical text

# Phrase replacements, applied longest first on whole words.
_SYNONYMS: dict[str, str] = {
    "turn on": "enable",
    "switch on": "enable",
    "activate": "enable",
    "turn off": "disable",
    "switch off": "disable",
    "deactivate": "disable",
    "make": "create",
    "add": "insert",
    "put": "insert",
    "remove": "delete",
    "erase": "delete",
    "get rid of": "delete",
    "set up": "configure",
    "setup": "configure",
    "modify": "change",
    "edit": "change",
    "launch": "open",
    "unhide": "show",
}
_SYNONYM_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in sorted(_SYNONYMS, key=len, reverse=True)) + r")\b"
)
_OPPOSITES: tuple[frozenset[str], ...] = tuple(
    frozenset(pair)
    for pair in (
        ("enable", "disable"),
        ("show", "hide"),
        ("open", "close"),
        ("insert", "delete"),
        ("create", "delete"),
        ("increase", "decrease"),
        ("lock", "unlock"),
        ("undo", "redo"),
    )
)
_STOPWORDS = frozenset(
    ("a", "an", "the", "my", "this", "that", "these", "those", "to", "in", "into", "on",
     "of", "for", "with", "it", "some", "me", "i", "new")
)


def _stem(token: str) -> str:
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def canonical_tokens(task: str, app: str = "") -> tuple[str, ...]:
    """Task text reduced to comparable tokens; the app's own name is dropped."""
    text = _SYNONYM_RE.sub(lambda m: _SYNONYMS[m.group(1)], task_key(task))
    app_tokens = set(app.split())
    return tuple(
        _stem(t) for t in text.split() if t not in _STOPWORDS and t not in app_tokens
    )


def task_similarity(a: str, b: str, app: str = "") -> float:
    """0..1 similarity between two task texts for the same app."""
    if task_key(a) == task_key(b):
        return 1.0
    ta, tb = canonical_tokens(a, app), canonical_tokens(b, app)
    if not ta or not tb:
        return 0.0
    sa, sb = set(ta), set(tb)
    if any(len(pair & sa) == 1 and len(pair & sb) == 1 and pair & sa != pair & sb
           for pair in _OPPOSITES):
        return 0.0
    overlap = len(sa & sb) / len(sa | sb)
    ratio = SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()
    return _OVERLAP_WEIGHT * overlap + (1 - _OVERLAP_WEIGHT) * ratio


def tasks_match(a: str, b: str, app: str = "") -> bool:
    return task_similarity(a, b, app) >= MATCH_THRESHOLD
