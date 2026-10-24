"""Deterministic, proposal-only learning. No Qt, database, or network dependencies."""

from __future__ import annotations

import math
import re
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from curio.memory_contract import (
    ApprovalStatus,
    AutomaticLearningPolicy,
    ContradictionResolution,
    ExplicitFeedback,
    MemoryRecord,
    MemorySettings,
    MemorySource,
    MemoryType,
)

Inference = Callable[[str], Awaitable[Sequence[MemoryRecord]]]
SnapshotProvider = Callable[[], Awaitable[Sequence[MemoryRecord]]]


def _normalize(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


def _without_negation(text: str) -> str:
    return re.sub(r"\b(?:(?:do|does|did) )?not\s+", "", text)


def _temporary(text: str) -> bool:
    return bool(
        re.search(r"\b(for now|this time|today|just now|for this|temporarily)\b", text, re.I)
    )


def _signal(text: str) -> tuple[str, str] | None:
    text = text.casefold()
    if re.search(r"\b(shorter|short|concise|brief)\b", text):
        return "response.verbosity", "short"
    if re.search(r"\b(longer|detailed|thorough)\b", text):
        return "response.verbosity", "long"
    if re.search(r"\b(interrupt|interrupting|interruptions)\b", text) and re.search(
        r"\b(stop|less|fewer|often)\b", text
    ):
        return "interaction.frequency", "low"
    return None


@dataclass(frozen=True)
class LearningPolicy:
    confidence_threshold: float = 0.8
    repeated_signals: int = 3
    max_tracked_signals: int = 128
    max_candidates: int = 8

    def __post_init__(self) -> None:
        if not math.isfinite(self.confidence_threshold) or not 0 <= self.confidence_threshold <= 1:
            raise ValueError("confidence_threshold must be finite and in [0, 1]")
        for value in (self.repeated_signals, self.max_tracked_signals, self.max_candidates):
            if type(value) is not int or value < 1:
                raise ValueError("learning limits must be positive integers")
        if self.repeated_signals < 2:
            raise ValueError("inferred preferences require at least two interactions")


@dataclass(frozen=True)
class AdaptiveBounds:
    verbosity_min: float = 0.2
    verbosity_max: float = 1.0
    frequency_min: float = 0.0
    frequency_max: float = 1.0

    def __post_init__(self) -> None:
        for low, high in (
            (self.verbosity_min, self.verbosity_max),
            (self.frequency_min, self.frequency_max),
        ):
            if not (math.isfinite(low) and math.isfinite(high) and 0 <= low <= high <= 1):
                raise ValueError("adaptive bounds must satisfy 0 <= min <= max <= 1")


@dataclass(frozen=True)
class AdaptiveValues:
    verbosity: float
    interruption_frequency: float


class RuleBasedLearningEngine:
    """Implements LearningEngine; returned records always require approval.

    snapshot_provider supplies current records, including pending proposals, for
    deduplication. Inference is opt-in and receives only user text. Signal evidence
    is bounded, session-local, and resettable; methods never mutate storage.
    """

    def __init__(
        self,
        *,
        snapshot_provider: SnapshotProvider | None = None,
        inference: Inference | None = None,
        policy: LearningPolicy | None = None,
        explicit_preferences: Mapping[str, str] | None = None,
        bounds: AdaptiveBounds | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._snapshot = snapshot_provider
        self._inference = inference
        self.policy = policy or LearningPolicy()
        self.bounds = bounds or AdaptiveBounds()
        self._explicit = dict(explicit_preferences or {})
        self._clock = clock or (lambda: datetime.now(UTC))
        self._signals: OrderedDict[tuple[str, str], set[str]] = OrderedDict()

    def reset_signals(self) -> None:
        """Call when disabling learning or clearing memories to discard evidence."""
        self._signals.clear()

    def _active(self, record: MemoryRecord) -> bool:
        return record.approval_status != ApprovalStatus.REJECTED and (
            record.expires_at is None or record.expires_at > self._clock()
        )

    @staticmethod
    def _priority(record: MemoryRecord) -> int:
        return 0 if record.source == MemorySource.AUTOMATIC else 1

    async def _existing(self) -> Sequence[MemoryRecord]:
        return await self._snapshot() if self._snapshot else ()

    def _candidate(
        self, content, kind, source, settings, *, key=None, source_id=None, confidence=0.98
    ) -> MemoryRecord:
        now = self._clock()
        expiration = (
            now + timedelta(days=settings.default_expiration_days)
            if settings.default_expiration_days is not None
            else None
        )
        return MemoryRecord(
            type=kind,
            content=content,
            source=source,
            confidence=confidence,
            preference_key=key,
            source_id=source_id,
            created_at=now,
            expires_at=expiration,
        )

    async def _accept(self, candidate, existing, settings) -> MemoryRecord | None:
        result = await self.resolve_contradictions(candidate, existing, settings=settings)
        return result.proposed_memory if result else None

    async def process_explicit_feedback(
        self,
        feedback: ExplicitFeedback,
        *,
        settings: MemorySettings,
    ) -> tuple[MemoryRecord, ...]:
        text = feedback.text.strip()
        if not settings.enabled or _temporary(text) or re.match(r"forget\b", text, re.I):
            return ()
        signal = _signal(text)
        candidate = None
        if signal and re.search(
            r"\b(i prefer|i like|always|stop|from now on|actually|instead)\b", text, re.I
        ):
            key, content = signal
            candidate = self._candidate(
                content,
                MemoryType.PREFERENCE,
                MemorySource.EXPLICIT_FEEDBACK,
                settings,
                key=key,
                source_id=feedback.id,
            )
        else:
            match = re.fullmatch(r"remember (?:that )?(.+?)[.!]?", text, re.I)
            if match:
                content = match[1].strip()
                kind = (
                    MemoryType.PROJECT
                    if re.search(r"\bworking on\b", content, re.I)
                    else MemoryType.FACT
                )
                candidate = self._candidate(
                    content, kind, MemorySource.EXPLICIT_FEEDBACK, settings, source_id=feedback.id
                )
        if candidate is None:
            return ()
        accepted = await self._accept(candidate, await self._existing(), settings)
        return (accepted,) if accepted else ()

    async def propose_memories(
        self,
        user_text: str,
        assistant_text: str,
        *,
        settings: MemorySettings,
        source_id: str | None = None,
    ) -> tuple[MemoryRecord, ...]:
        if not settings.enabled:
            self.reset_signals()
            return ()
        if settings.automatic_learning == AutomaticLearningPolicy.OFF or _temporary(user_text):
            return ()
        # Explicit commands must use the explicit path, never become behavioral evidence.
        if re.search(r"\b(remember|forget|i prefer|stop)\b", user_text, re.I):
            return ()
        signal = _signal(user_text)
        if signal is None or source_id is None:
            return ()
        evidence = self._signals.setdefault(signal, set())
        self._signals.move_to_end(signal)
        while len(self._signals) > self.policy.max_tracked_signals:
            self._signals.popitem(last=False)
        if source_id in evidence or len(evidence) >= self.policy.repeated_signals:
            return ()
        evidence.add(source_id)
        if len(evidence) < self.policy.repeated_signals:
            return ()
        key, content = signal
        candidate = self._candidate(
            content,
            MemoryType.PREFERENCE,
            MemorySource.AUTOMATIC,
            settings,
            key=key,
            source_id=source_id,
            confidence=0.85,
        )
        candidates = [candidate]
        if self._inference:
            # Optional inference may refine only the repeatedly observed preference.
            extras = await self._inference(user_text)
            candidates.extend(
                r
                for r in extras[: self.policy.max_candidates - 1]
                if r.type == MemoryType.PREFERENCE
                and r.preference_key == key
                and r.content == content
            )
        existing = list(await self._existing())
        accepted = []
        for record in candidates:
            record = replace(
                record, source=MemorySource.AUTOMATIC, approval_status=ApprovalStatus.PENDING
            )
            result = await self._accept(record, existing, settings)
            if result:
                accepted.append(result)
                existing.append(result)
        return tuple(accepted)

    async def update_preferences(
        self,
        preference_key: str,
        content: str,
        *,
        feedback: ExplicitFeedback,
        existing: Sequence[MemoryRecord],
        settings: MemorySettings,
    ) -> ContradictionResolution | None:
        if not settings.enabled or not preference_key.strip() or not content.strip():
            return None
        candidate = self._candidate(
            content,
            MemoryType.PREFERENCE,
            MemorySource.EXPLICIT_FEEDBACK,
            settings,
            key=preference_key,
            source_id=feedback.id,
        )
        return await self.resolve_contradictions(candidate, existing, settings=settings)

    async def resolve_contradictions(
        self,
        candidate: MemoryRecord,
        existing: Sequence[MemoryRecord],
        *,
        settings: MemorySettings,
    ) -> ContradictionResolution | None:
        if (
            not settings.enabled
            or not candidate.content.strip()
            or not math.isfinite(candidate.confidence)
            or not self.policy.confidence_threshold <= candidate.confidence <= 1
            or not self._active(candidate)
        ):
            return None
        if candidate.type == MemoryType.PREFERENCE and not candidate.preference_key:
            return None
        if candidate.preference_key in self._explicit:
            return None
        conflicts = []
        for old in existing:
            if not self._active(old):
                continue
            same_key = (
                candidate.type == MemoryType.PREFERENCE
                and old.preference_key == candidate.preference_key
            )
            comparable = same_key or (
                candidate.type != MemoryType.PREFERENCE and old.type == candidate.type
            )
            if comparable and _normalize(old.content) == _normalize(candidate.content):
                return None
            if same_key:
                if candidate.source == MemorySource.AUTOMATIC:
                    return None
                conflicts.append(old.id)
            elif comparable:
                # Conservative obvious fact negation; leave subtle semantics for review.
                a, b = _normalize(old.content), _normalize(candidate.content)
                if _without_negation(a) == b or _without_negation(b) == a:
                    if candidate.source == MemorySource.AUTOMATIC:
                        return None
                    conflicts.append(old.id)
        return ContradictionResolution(
            proposed_memory=replace(candidate, approval_status=ApprovalStatus.PENDING),
            superseded_ids=tuple(conflicts),
            reason="replacement" if conflicts else "new memory",
        )

    def propose_forgetting(
        self,
        feedback: ExplicitFeedback,
        existing: Sequence[MemoryRecord],
        *,
        settings: MemorySettings,
    ) -> tuple[str, ...]:
        """Deletion proposal only. Ambiguous references need an explicit memory_id."""
        if not settings.enabled or not re.match(r"forget\b", feedback.text.strip(), re.I):
            return ()
        if feedback.memory_id:
            return tuple(r.id for r in existing if r.id == feedback.memory_id)
        if _normalize(feedback.text) == "forget everything":
            return tuple(r.id for r in existing)
        target = re.sub(r"^forget\s+(?:that\s+)?", "", feedback.text.strip(), flags=re.I)
        return tuple(r.id for r in existing if _normalize(r.content) == _normalize(target))

    def rank_relevance(
        self, query: str, records: Sequence[MemoryRecord]
    ) -> tuple[MemoryRecord, ...]:
        """Lexical ranking helper; retrieval still owns rendering and token budgets."""
        terms = set(_normalize(query).split())
        scored = []
        for record in records:
            if record.approval_status != ApprovalStatus.APPROVED or not self._active(record):
                continue
            words = set(_normalize(record.content + " " + (record.preference_key or "")).split())
            overlap = len(terms & words)
            if overlap:
                scored.append((overlap, self._priority(record), record.confidence, record))
        scored.sort(key=lambda item: (-item[0], -item[1], -item[2], item[3].id))
        return tuple(item[3] for item in scored)

    def adaptive_values(self, records: Sequence[MemoryRecord]) -> AdaptiveValues:
        """Approved preferences only; explicit settings win even over later feedback."""
        choices = {}
        eligible = [
            r
            for r in records
            if r.approval_status == ApprovalStatus.APPROVED
            and r.type == MemoryType.PREFERENCE
            and self._active(r)
        ]
        eligible.sort(key=lambda r: (self._priority(r), r.updated_at, r.id))
        for record in eligible:
            choices[record.preference_key] = record.content
        choices.update(self._explicit)
        b = self.bounds
        verbosity = {"short": b.verbosity_min, "long": b.verbosity_max}.get(
            choices.get("response.verbosity"), (b.verbosity_min + b.verbosity_max) / 2
        )
        frequency = {"low": b.frequency_min, "high": b.frequency_max}.get(
            choices.get("interaction.frequency"), (b.frequency_min + b.frequency_max) / 2
        )
        return AdaptiveValues(verbosity, frequency)
