# Shared Python memory contract

All four development branches import from `curio.memory_contract` in
`curio-py/curio/memory_contract.py`. This module contains standard-library
dataclasses, literal types, and structural `Protocol` interfaces only. Implementers
need not inherit from protocols. No storage, inference, configuration wiring,
prompt injection, event bus, or UI is implemented here.

## Records and settings

`MemoryRecord` is an immutable snapshot with a UUID string `id`, `type` (`fact`,
`preference`, `project`), plain-text `content`, provenance string `source`,
`confidence` (finite, 0 through 1), UTC-aware `created_at`/`updated_at`, optional
`expires_at`, and `approval_status` (`pending`, `approved`, `rejected`). Defaults
generate the ID and timestamps, use confidence 1, no expiration, and pending
approval. Source identifies origin, such as `user` or a conversation ID; it must
not contain credentials. Confidence never grants approval.

Implementations validate records at write boundaries: nonempty ID, content and
source, supported literals, confidence range, and aware UTC timestamps with
`updated_at >= created_at` and expiration (if any) after creation. Types alone
do not perform runtime validation. Use `dataclasses.replace` for edits; updates
preserve ID/creation time and advance update time. Approval is an explicit update.

`MemorySettings()` defaults to disabled, local storage, default application data
path (`storage_path=None`), proposal-only automatic learning, and no time-based
retention (`retention_days=None`). The storage branch chooses its filename under
the platformdirs Curio user-data directory. Session mode is nonpersistent
and ignores storage_path. A supplied path names the local store file.
Retention days, when supplied, must be a positive integer; writers apply it as
expiration to new records. Existing expiration stays unchanged unless edited.
Policy `off` disables implicit learning, `propose` requires review, and
`auto_approve` permits automatic approval only after explicit user opt-in.
Disabled state overrides every policy. Disabling does not delete records; manual
view/edit/delete/clear remain available.

## Interfaces and ownership

All store, learning, and retrieval methods are async to fit the existing
qasync/asyncio application. Implementations must keep blocking work off the UI
thread and propagate cancellation. Constructors/dependency injection are left to
each branch; the existing app is unchanged.

| Interface | Contract |
| --- | --- |
| `MemoryStore.create(record)` | Return stored snapshot; duplicate ID raises `ValueError`. |
| `retrieve(memory_id)` | Return snapshot or `None`. |
| `update(record)` | Full replacement; missing ID raises `KeyError`. |
| `delete(memory_id)` | Return whether a record existed. |
| `list(...)` | Optional type/status filters, limit 100, offset 0; newest created first, ID ascending for ties. |
| `search(query, ...)` | Text relevance order, optional type/status filters, limit 20; ID ascending for ties. Ranking/search algorithm is backend-owned; blank query returns empty. |
| `clear()` | Delete all records, including pending/rejected/expired; return count deleted. |
| `LearningEngine.process_explicit_feedback(feedback, settings=...)` | Propose records from explicit user corrections; feedback supplies content, source, optional target memory ID and context. |
| `propose_memories(content, source=..., settings=...)` | Propose records from supplied interaction text according to automatic-learning policy. |
| `update_preferences(preferences, source=..., settings=...)` | Propose `preference` records from string key/value pairs; does not alter app configuration. |
| `resolve_contradictions(candidate, existing)` | Return candidate, conflicting IDs, action and reason; default is `needs_review`. No writes. |
| `MemoryRetriever.retrieve(query, token_budget=..., settings=...)` | Return `MemorySelection(records, context, token_count)` in relevance order. |

Store queries expose all statuses and expired records for management unless
filtered. Limits/offsets must be nonnegative (zero limit returns empty). Invalid
input raises `ValueError`; persistence failures use `OSError`. Stores do not
enforce enabled state or approval policy; the coordinating application does.

Learning returns proposals without persistence or side effects. Disabled settings
return no proposals; automatic policy `off` suppresses `propose_memories`, while
explicit feedback/preferences still work when enabled. Proposals remain pending
even under `auto_approve`; the coordinator applies that policy, validates and
persists, then publishes events. Preference keys can be represented in content
as `key: value`; existing-record lookup and matching are implementation-owned.
Explicit feedback does not itself approve a memory.

Contradiction resolution never silently replaces approved facts. The coordinator
asks for review before applying `replace_existing`, then rejects conflicting
records and approves the replacement as one logical operation. `keep_existing`
leaves the store unchanged; `needs_review` keeps the candidate pending.

Retrieval includes only approved, unexpired records (`expires_at > now`, or
no expiration). Disabled memory or a zero budget returns an empty selection;
negative budget raises `ValueError`. `context` is the exact formatted text to
insert into a prompt; `token_count` includes formatting and must not exceed the
budget. The retrieval branch owns a model tokenizer or conservative upper-bound
counter, drops records that cannot fit, and treats memory as untrusted data.
Returned records must correspond to the rendered context; retrieval has no writes.

## Changes and UI notifications

`MemoryEvents` offers synchronous subscriptions returning idempotent unsubscribe
callbacks. The coordinator publishes `MemoryChangeEvent` only after successful
writes (`created`, `updated`, `deleted`, `cleared`) or applied settings changes.
Affected IDs are supplied for record changes; clear/settings events use an empty
tuple to mean full refresh. Approval edits use `updated`. Failed/no-op operations
emit no change event.

`MemoryNotification` carries display text, info/warning/error level, related IDs,
and a review flag. Notifications are separate from persistence events; the UI
can offer review without treating the notification as approval. Subscribers are
called in registration order on the application's event-loop thread; callbacks
must return quickly. Publishers isolate subscriber exceptions so a UI failure
cannot undo a committed write or prevent other subscribers running. Qt adapters
may forward these objects through `Signal(object)`; no Qt import is required by
the shared contract. Publishing and event-bus implementation belong to integration.
