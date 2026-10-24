"""URL tutorial coaching services; widget is optional via .widget import."""

from .coach import Assessment, Coach, ModelProvider, Plan, Step, TranscriptProvider
from .content import Block, CoachError, PageFetcher, PageResponse, Source, extract_html

__all__ = [
    "Assessment",
    "Block",
    "Coach",
    "CoachError",
    "ModelProvider",
    "PageFetcher",
    "PageResponse",
    "Plan",
    "Source",
    "Step",
    "TranscriptProvider",
    "extract_html",
]
