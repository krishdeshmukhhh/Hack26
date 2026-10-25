"""Focus session: start plan, runtime, timeline, summary store.

Widgets are optional imports: ``.presenter``, ``.start_panel``,
``.session_window``, ``.summary_window`` and ``.history_window``.
"""

from .planning import (
    StartRequest,
    build_plan,
    format_if_then,
    parse_if_then_reply,
    parse_if_then_text,
    parse_start_request,
    past_distractions,
    suggest_if_then,
    template_if_then,
)
from .rationale import SECTION_SUMMARIES, why_text
from .runtime import FocusRuntime, Presenter, build_model_call
from .store import SqliteSessionStore
from .timeline import SessionTimeline, TimelineState

__all__ = [
    "SECTION_SUMMARIES",
    "FocusRuntime",
    "Presenter",
    "SessionTimeline",
    "SqliteSessionStore",
    "StartRequest",
    "TimelineState",
    "build_model_call",
    "build_plan",
    "format_if_then",
    "parse_if_then_reply",
    "parse_if_then_text",
    "parse_start_request",
    "past_distractions",
    "suggest_if_then",
    "template_if_then",
    "why_text",
]
