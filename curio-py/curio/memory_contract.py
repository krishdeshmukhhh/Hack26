"""Shared memory contracts only; no persistence, inference, or Qt dependencies.

See docs/memory-contract.md for behavioral requirements on implementations.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import uuid4


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MemoryType(StrEnum):
    FACT = "fact"
    PREFERENCE = "preference"
    PROJECT = "project"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class MemorySource(StrEnum):
    USER = "user"
    EXPLICIT_FEEDBACK = "explicit_feedback"
    AUTOMATIC = "automatic"
    IMPORT = "import"


class AutomaticLearningPolicy(StrEnum):
    OFF = "off"
    PROPOSE = "propose"  # Automatic candidates still require user approval.


class StorageMode(StrEnum):
    LOCAL = "local"
    SESSION = "session"


@dataclass(frozen=True, kw_only=True)
class MemoryRecord:
    type: MemoryType
    content: str
    source: MemorySource
    id: str = field(default_factory=lambda: str(uuid4()))
    confidence: float = 1.0
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime | None = None
    expires_at: datetime | None = None
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    source_id: str | None = None  # Optional turn/feedback/import reference, not raw input.
    preference_key: str | None = None  # Stable identity for preference replacements.

    def __post_init__(self) -> None:
        if self.updated_at is None:
            object.__setattr__(self, "updated_at", self.created_at)


@dataclass(frozen=True, kw_only=True)
class MemorySettings:
    enabled: bool = False
    storage_mode: StorageMode = StorageMode.LOCAL
    storage_path: Path | None = None  # None: platformdirs user_data_path / memory.sqlite3.
    automatic_learning: AutomaticLearningPolicy = AutomaticLearningPolicy.OFF
    default_expiration_days: int | None = None  # None: no automatic expiration.


@dataclass(frozen=True, kw_only=True)
class MemoryFilter:
    type: MemoryType | None = None
    approval_status: ApprovalStatus | None = None
    preference_key: str | None = None
    include_expired: bool = False


@dataclass(frozen=True, kw_only=True)
class ExplicitFeedback:
    text: str  # The user's explicit correction/instruction, not model-generated feedback.
    turn_id: str | None = None
    memory_id: str | None = None
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True, kw_only=True)
class ContradictionResolution:
    """Proposal only: approve replacement before superseding existing memories."""

    proposed_memory: MemoryRecord
    superseded_ids: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True, kw_only=True)
class MemorySelection:
    """prompt_text is the exact memory block counted against the token budget."""

    memories: tuple[MemoryRecord, ...] = ()
    prompt_text: str = ""
    token_count: int = 0


class MemoryStore(Protocol):
    async def create(self, record: MemoryRecord) -> MemoryRecord:
        """Insert; duplicate ID raises ValueError. Validate before writing."""
        ...

    async def retrieve(self, memory_id: str) -> MemoryRecord | None:
        """Exact administrative lookup, including expired/rejected records."""
        ...

    async def update(self, record: MemoryRecord) -> MemoryRecord:
        """Full replacement; preserve ID/created_at, advance updated_at; missing ID: KeyError."""
        ...

    async def delete(self, memory_id: str) -> bool:
        """Return whether a record was removed; missing ID is harmless."""
        ...

    async def list(
        self, *, filters: MemoryFilter | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[MemoryRecord, ...]:
        """Newest updated_at first, ID ascending on ties; paginate after filtering."""
        ...

    async def search(
        self, query: str, *, filters: MemoryFilter | None = None, limit: int = 20
    ) -> tuple[MemoryRecord, ...]:
        """Relevance descending; ties use list order. Empty query returns no matches."""
        ...

    async def clear(self) -> int:
        """Delete ALL memories, including expired/rejected ones; return removed count."""
        ...


class LearningEngine(Protocol):
    """All methods return proposals without changing the store or approving records."""

    async def process_explicit_feedback(
        self, feedback: ExplicitFeedback, *, settings: MemorySettings
    ) -> tuple[MemoryRecord, ...]: ...

    async def propose_memories(
        self,
        user_text: str,
        assistant_text: str,
        *,
        settings: MemorySettings,
        source_id: str | None = None,
    ) -> tuple[MemoryRecord, ...]: ...

    async def update_preferences(
        self,
        preference_key: str,
        content: str,
        *,
        feedback: ExplicitFeedback,
        existing: Sequence[MemoryRecord],
        settings: MemorySettings,
    ) -> ContradictionResolution | None: ...

    async def resolve_contradictions(
        self,
        candidate: MemoryRecord,
        existing: Sequence[MemoryRecord],
        *,
        settings: MemorySettings,
    ) -> ContradictionResolution | None: ...


TokenCounter = Callable[[str], int]


class MemoryRetriever(Protocol):
    async def select(
        self,
        query: str,
        *,
        settings: MemorySettings,
        token_budget: int,
        count_tokens: TokenCounter,
    ) -> MemorySelection:
        """Select approved, unexpired records; count complete rendered block, including labels."""
        ...


class MemoryEventType(StrEnum):
    CREATED = "created"
    UPDATED = "updated"  # Includes approvals/rejections.
    DELETED = "deleted"
    CLEARED = "cleared"
    SETTINGS_CHANGED = "settings_changed"


@dataclass(frozen=True, kw_only=True)
class MemoryEvent:
    type: MemoryEventType
    memory_ids: tuple[str, ...] = ()
    occurred_at: datetime = field(default_factory=_utc_now)


class NotificationLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, kw_only=True)
class MemoryNotification:
    code: str  # Stable machine-readable code, e.g. "memory.approval_required".
    message: str  # Short UI-safe text; no raw memory content or secrets.
    level: NotificationLevel = NotificationLevel.INFO
    memory_ids: tuple[str, ...] = ()


MemoryChangeCallback = Callable[[MemoryEvent], None]
MemoryNotificationCallback = Callable[[MemoryNotification], None]
Unsubscribe = Callable[[], None]


class MemoryEvents(Protocol):
    def subscribe_changes(self, callback: MemoryChangeCallback) -> Unsubscribe: ...

    def subscribe_notifications(self, callback: MemoryNotificationCallback) -> Unsubscribe: ...
