"""Live tutoring; import the Qt widget explicitly from .widget."""

from .checker import Unsupported
from .service import Attempt, CompletionRecord, Feedback, TutoringService

__all__ = ["Attempt", "CompletionRecord", "Feedback", "TutoringService", "Unsupported"]
