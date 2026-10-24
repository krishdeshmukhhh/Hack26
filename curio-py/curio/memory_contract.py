"""Shared memory contracts; no persistence, inference, or Qt dependencies.

See docs/memory-contract.md for behavioral requirements on implementations.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol
from uuid import uuid4

MemoryType = Literal["fact", "preference", "project"]
ApprovalStatus = Literal["pending", "approved", "rejected"]
AutomaticLearningPolicy = Literal["off", "propose", "auto_approve"]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, kw_only=True)
class MemoryRecord:
    type: MemoryType
    content: str
    source: str
    id: str = field(default_factory=lambda: str(uuid4()))
    confidence: float = 1.0
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    expires_at: datetime | None = None
    approval_status: ApprovalStatus = "pending"


@dataclass(frozen=True, kw_only=True)
class MemorySettings:
    enabled: bool = False
    storage_mode: Literal["local", "session"] = "local"
    storage_path: Path | None = None
    automatic_learning_policy: AutomaticLearningPolicy = "propose"
    retention_days: int | None = None


@dataclass(frozen=True, kw_only=True)
class ExplicitFeedback:
    content: str
    source: str = "user"
    memory_id: str | None = None
    context: str = ""


@dataclass(frozen=True, kw_only=True)
class ContradictionResolution:
    """A proposal; applying it requires the normal approval/write path."""

    candidate: MemoryRecord
    conflicting_ids: tuple[str, ...] = ()
    action: Literal["keep_existing", "replace_existing", "needs_review"] = "needs_review"
    reason: str = ""


@dataclass(frozen=True, kw_only=True)
class MemorySelection:
    records: tuple[MemoryRecord, ...] = ()
    context: str = ""
    token_count: int = 0


class MemoryStore(Protocol):
    async def create(self, record: MemoryRecord) -> MemoryRecord: ...

    async def retrieve(self, memory_id: str) -> MemoryRecord | None: ...

    async def update(self, record: MemoryRecord) -> MemoryRecord: ...

    async def delete(self, memory_id: str) -> bool: ...

    async def list(
        self,
        *,
        type: MemoryType | None = None,
        approval_status: ApprovalStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[MemoryRecord]: ...

    async def search(
        self,
        query: str,
        *,
        type: MemoryType | None = None,
        approval_status: ApprovalStatus | None = None,
        limit: int = 20,
    ) -> Sequence[MemoryRecord]: ...

    async def clear(self) -> int: ...


class LearningEngine(Protocol):
    """Return proposals, without writing to the store or changing settings."""

    async def process_explicit_feedback(
        self, feedback: ExplicitFeedback, *, settings: MemorySettings
    ) -> Sequence[MemoryRecord]: ...

    async def propose_memories(
        self, content: str, *, source: str, settings: MemorySettings
    ) -> Sequence[MemoryRecord]: ...

    async def update_preferences(
        self, preferences: Mapping[str, str], *, source: str, settings: MemorySettings
    ) -> Sequence[MemoryRecord]: ...

    async def resolve_contradictions(
        self, candidate: MemoryRecord, existing: Sequence[MemoryRecord]
    ) -> ContradictionResolution: ...


class MemoryRetriever(Protocol):
    async def retrieve(
        self, query: str, *, token_budget: int, settings: MemorySettings
    ) -> MemorySelection: ...


MemoryChangeKind = Literal["created", "updated", "deleted", "cleared", "settings_changed"]


@dataclass(frozen=True, kw_only=True)
class MemoryChangeEvent:
    kind: MemoryChangeKind
    memory_ids: tuple[str, ...] = ()
    occurred_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True, kw_only=True)
class MemoryNotification:
    message: str
    level: Literal["info", "warning", "error"] = "info"
    memory_ids: tuple[str, ...] = ()
    requires_review: bool = False


MemoryChangeCallback = Callable[[MemoryChangeEvent], None]
MemoryNotificationCallback = Callable[[MemoryNotification], None]
Unsubscribe = Callable[[], None]


class MemoryEvents(Protocol):
    def subscribe_changes(self, callback: MemoryChangeCallback) -> Unsubscribe: ...

    def subscribe_notifications(self, callback: MemoryNotificationCallback) -> Unsubscribe: ...
