"""End-of-session retrieval questions (research doc, section G).

``generate_review_items`` asks the injected ``ModelCall`` for two or three
short recall questions as JSON and parses the reply defensively. Without a
model, or when the reply is unusable, it falls back to template questions.
Answers are always shown after the learner responds; integration does that.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime

from curio.focus_contract import ModelCall, ReviewItem
from curio.learning_contract import concept_key

MIN_ITEMS = 2
MAX_ITEMS = 3
_MAX_QUESTION = 200
_MAX_ANSWER = 300
_MAX_CONTEXT = 2000

QUIZ_SYSTEM_PROMPT = (
    "You write short retrieval-practice questions for a learner who just finished a study "
    "session. Each question must make them recall the answer from memory: no multiple choice, "
    "no yes/no or true/false, and don't put the answer in the question. Keep each question "
    "under 20 words and each answer to one sentence. Reply with only a JSON array of objects "
    'with the keys "concept", "question" and "answer", using the concepts given.'
)

TEMPLATES: tuple[str, ...] = (
    "Where do you find {concept}{in_app}?",
    "What is {concept} for, and when would you use it?",
    "What steps did you take to use {concept} today?",
)
FALLBACK_ANSWER = "Compare with how you did it in today's session."

_RECOGNITION = re.compile(
    r"^\s*(is|are|does|do|did|can|was|were|true or false)\b"
    r"|which of the following|\(\s*[a-d]\s*\)|\b[a-d]\)\s",
    re.IGNORECASE,
)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


async def generate_review_items(
    concepts: Sequence[str],
    context: str | Sequence[str] = (),
    model_call: ModelCall | None = None,
    *,
    app: str = "",
    now: datetime | None = None,
    count: int = MAX_ITEMS,
    timeout: float = 20.0,
) -> tuple[ReviewItem, ...]:
    """Two or three recall questions on ``concepts``, due at ``now`` (quiz right away).

    ``context`` is optional notes such as walkthrough step text; it is sent to
    the model, so integration must pass only text the user allows to leave.
    """
    keys = list(dict.fromkeys(k for k in (concept_key(c) for c in concepts) if k))
    if not keys:
        return ()
    count = max(MIN_ITEMS, min(MAX_ITEMS, count))
    notes = [context] if isinstance(context, str) else list(context)
    notes = [" ".join(n.split()) for n in notes if isinstance(n, str) and n.strip()]
    due = now or datetime.now(UTC)
    items: list[ReviewItem] = []
    if model_call is not None:
        try:
            reply = await asyncio.wait_for(
                model_call(QUIZ_SYSTEM_PROMPT, _user_text(keys, notes, app, count)), timeout
            )
        except Exception:
            reply = ""
        items = parse_review_items(reply, keys, due)[:count]
    if len(items) < MIN_ITEMS:
        items = _merge(items, template_items(keys, notes, app, due), count)
    return tuple(items)


def parse_review_items(reply: object, concepts: Sequence[str], due: datetime) -> list[ReviewItem]:
    """Valid recall questions from a model reply; malformed parts are dropped."""
    if not isinstance(reply, str):
        return []
    text = _FENCE.sub("", reply.strip())
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        raw = json.loads(text[start : end + 1])
    except (ValueError, RecursionError):
        return []
    if not isinstance(raw, list):
        return []
    keys = [concept_key(c) for c in concepts]
    items: list[ReviewItem] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        question, answer = entry.get("question"), entry.get("answer")
        if not isinstance(question, str) or not isinstance(answer, str):
            continue
        question, answer = " ".join(question.split()), " ".join(answer.split())
        if not question or not answer or len(question) > _MAX_QUESTION:
            continue
        if _RECOGNITION.search(question) or question.casefold() in seen:
            continue
        concept = entry.get("concept")
        concept = concept_key(concept) if isinstance(concept, str) else ""
        if concept not in keys:
            concept = _guess_concept(question, keys)
        seen.add(question.casefold())
        items.append(
            ReviewItem(
                concept=concept, question=question, answer=answer[:_MAX_ANSWER], due_at=due
            )
        )
    return items


def template_items(
    concepts: Sequence[str], notes: Sequence[str], app: str, due: datetime
) -> list[ReviewItem]:
    """Template questions, round-robin over concepts; answers come from matching notes."""
    keys = [k for k in (concept_key(c) for c in concepts) if k]
    in_app = f" in {app.strip()}" if app.strip() else ""
    items: list[ReviewItem] = []
    for index in range(MAX_ITEMS):
        if not keys:
            break
        concept = keys[index % len(keys)]
        template = TEMPLATES[(index // len(keys)) % len(TEMPLATES)]
        matching = [n for n in notes if _mentions(n, concept)]
        answer = "; ".join(matching)[:_MAX_ANSWER] if matching else FALLBACK_ANSWER
        items.append(
            ReviewItem(
                concept=concept,
                question=template.format(concept=concept, in_app=in_app),
                answer=answer,
                due_at=due,
            )
        )
    return items


def _user_text(keys: Sequence[str], notes: Sequence[str], app: str, count: int) -> str:
    lines = [f"Write {count} questions.", f"Concepts: {', '.join(keys)}"]
    if app.strip():
        lines.append(f"App: {app.strip()}")
    if notes:
        lines.append("Session notes:\n" + "\n".join(f"- {n}" for n in notes)[:_MAX_CONTEXT])
    return "\n".join(lines)


def _merge(model: list[ReviewItem], templates: list[ReviewItem], count: int) -> list[ReviewItem]:
    items = list(model)
    asked = {i.question.casefold() for i in items}
    for item in templates:
        if len(items) >= count:
            break
        if item.question.casefold() not in asked:
            items.append(item)
    return items


def _mentions(note: str, concept: str) -> bool:
    # "pivot table" should match "PivotTable", so compare without spaces too
    note = concept_key(note)
    return concept in note or concept.replace(" ", "") in note.replace(" ", "")


def _guess_concept(question: str, keys: Sequence[str]) -> str:
    for key in keys:
        if _mentions(question, key):
            return key
    return keys[0]
