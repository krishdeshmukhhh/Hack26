"""Study coach: tutoring moves, end-of-session quizzes and spaced review.

See docs/study-coach.md. No Qt; the scheduler does its SQLite work off the
event loop.
"""

from .coach import (
    EvidenceBasedCoach,
    mastery_for,
    mastery_from_skill_model,
    teach_back_directive,
)
from .quiz import generate_review_items, parse_review_items, template_items
from .scheduler import ReviewScheduler, SqliteReviewScheduler, interleave, similar

__all__ = [
    "EvidenceBasedCoach",
    "ReviewScheduler",
    "SqliteReviewScheduler",
    "generate_review_items",
    "interleave",
    "mastery_for",
    "mastery_from_skill_model",
    "parse_review_items",
    "similar",
    "teach_back_directive",
    "template_items",
]
