"""Application coordinator: serialized store access, learning, settings and events."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from pathlib import Path

from curio.learning import RuleBasedLearningEngine
from curio.memory_contract import (
    ApprovalStatus,
    MemoryChangeCallback,
    MemoryEvent,
    MemoryEventType,
    MemoryFilter,
    MemoryNotification,
    MemoryNotificationCallback,
    MemoryRecord,
    MemorySettings,
    TokenCounter,
    Unsubscribe,
)
from curio.memory_conversation import ConversationMemory, persist_proposal
from curio.memory_settings import save_memory_settings
from curio.memory_store import SQLiteMemoryStore

logger = logging.getLogger(__name__)


class MemoryRuntime:
    """Own on the qasync loop. Every UI/conversation write uses the same lock."""

    def __init__(
        self,
        settings: MemorySettings,
        *,
        config_path: Path,
        count_tokens: TokenCounter | None = None,
    ) -> None:
        self.settings = settings
        self.config_path = config_path
        self._store = SQLiteMemoryStore(settings)
        self._lock = asyncio.Lock()
        self._changes: list[MemoryChangeCallback] = []
        self._notifications: list[MemoryNotificationCallback] = []
        self.engine = RuleBasedLearningEngine(snapshot_provider=self.snapshot)
        self.conversation = ConversationMemory(
            self,
            settings=settings,
            # Conservative byte units for the configured byte/subword providers.
            # An exact model counter can be supplied without changing the contract.
            count_tokens=count_tokens or (lambda text: len(text.encode("utf-8"))),
            learning=self.engine,
            proposal_sink=self.persist_proposal,
        )

    @staticmethod
    def _subscribe(listeners, callback):
        listeners.append(callback)

        def unsubscribe():
            if callback in listeners:
                listeners.remove(callback)

        return unsubscribe

    def subscribe_changes(self, callback: MemoryChangeCallback) -> Unsubscribe:
        return self._subscribe(self._changes, callback)

    def subscribe_notifications(self, callback: MemoryNotificationCallback) -> Unsubscribe:
        return self._subscribe(self._notifications, callback)

    @staticmethod
    def _publish(listeners, payload):
        for callback in tuple(listeners):
            try:
                callback(payload)
            except Exception:
                logger.warning("Memory listener failed")

    def _changed(self, kind, *ids):
        self._publish(self._changes, MemoryEvent(type=kind, memory_ids=ids))

    async def snapshot(self) -> tuple[MemoryRecord, ...]:
        records = []
        async with self._lock:
            while True:
                page = await self._store.list(limit=100, offset=len(records))
                records.extend(page)
                if len(page) < 100:
                    return tuple(records)

    async def create(self, record: MemoryRecord) -> MemoryRecord:
        async with self._lock:
            if not self.settings.enabled:
                raise PermissionError("Memory disabled")
            result = await self._store.create(record)
            self._changed(MemoryEventType.CREATED, result.id)
            self._publish(
                self._notifications,
                MemoryNotification(
                    code="memory.approval_required",
                    message="New memory awaiting approval.",
                    memory_ids=(result.id,),
                ),
            )
            return result

    async def persist_proposal(self, proposal: MemoryRecord) -> None:
        async with self._lock:
            if not self.settings.enabled:
                raise PermissionError("Memory disabled")
            result = await persist_proposal(self._store, proposal)
            kind = MemoryEventType.CREATED if result.id == proposal.id else MemoryEventType.UPDATED
            self._changed(kind, result.id)
            self._publish(
                self._notifications,
                MemoryNotification(
                    code="memory.approval_required",
                    message="New memory awaiting approval.",
                    memory_ids=(result.id,),
                ),
            )

    async def retrieve(self, memory_id: str) -> MemoryRecord | None:
        async with self._lock:
            return await self._store.retrieve(memory_id)

    async def update(self, record: MemoryRecord) -> MemoryRecord:
        async with self._lock:
            previous = await self._store.retrieve(record.id)
            if previous is None:
                raise KeyError(record.id)
            # Approval retires conflicts only after the replacement has been persisted.
            conflicts = ()
            if record.approval_status == ApprovalStatus.APPROVED:
                existing = []
                while True:
                    page = await self._store.list(limit=100, offset=len(existing))
                    existing.extend(page)
                    if len(page) < 100:
                        break
                resolution = await self.engine.resolve_contradictions(
                    previous, [r for r in existing if r.id != record.id], settings=self.settings
                )
                conflicts = resolution.superseded_ids if resolution else ()
            result = await self._store.update(record)
            self._changed(MemoryEventType.UPDATED, result.id)
            if result.approval_status == ApprovalStatus.APPROVED:
                for memory_id in conflicts:
                    old = await self._store.retrieve(memory_id)
                    if old is not None:
                        await self._store.update(
                            replace(old, approval_status=ApprovalStatus.REJECTED)
                        )
                        self._changed(MemoryEventType.UPDATED, memory_id)
            return result

    async def delete(self, memory_id: str) -> bool:
        async with self._lock:
            removed = await self._store.delete(memory_id)
            if removed:
                self.engine.reset_signals()
                self._changed(MemoryEventType.DELETED, memory_id)
            return removed

    async def clear(self) -> int:
        async with self._lock:
            count = await self._store.clear()
            self.engine.reset_signals()
            if count:
                self._changed(MemoryEventType.CLEARED)
            return count

    async def list(
        self, *, filters: MemoryFilter | None = None, limit: int = 100, offset: int = 0
    ) -> tuple[MemoryRecord, ...]:
        async with self._lock:
            return await self._store.list(filters=filters, limit=limit, offset=offset)

    async def search(
        self, query: str, *, filters: MemoryFilter | None = None, limit: int = 20
    ) -> tuple[MemoryRecord, ...]:
        async with self._lock:
            return await self._store.search(query, filters=filters, limit=limit)

    async def save_settings(self, settings: MemorySettings) -> None:
        async with self._lock:
            # Persist first; a failed save leaves all components on the old settings.
            await asyncio.to_thread(save_memory_settings, self.config_path, settings)
            if (settings.storage_mode, settings.storage_path) == (
                self.settings.storage_mode,
                self.settings.storage_path,
            ):
                self._store.reconfigure(settings)
            else:
                await self._store.close()
                self._store = SQLiteMemoryStore(settings)
            self.settings = settings
            self.conversation.settings = settings
            self.engine.reset_signals()
            self._changed(MemoryEventType.SETTINGS_CHANGED)

    async def close(self) -> None:
        async with self._lock:
            await self._store.close()
        self._changes.clear()
        self._notifications.clear()
