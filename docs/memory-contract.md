# Shared memory contract

All four development branches import `curio.memory_contract` from
`curio-py/curio/memory_contract.py`. This module defines dataclasses, string enums,
and structural `Protocol` interfaces only. No database, inference, event bus,
configuration wiring, or prompt injection is implemented here. Python 3.12 and
the standard library are sufficient; existing Qt voice states remain unchanged.

## Records and storage

`MemoryRecord` is an immutable, keyword-only snapshot: UUID string `id`, `type`
(fact/preference/project), plain-text `content`, `source`, optional `source_id`,
confidence, creation/update/expiration times, and approval status. Preferences
use a stable `preference_key` such as `response.verbosity`; other records leave
it unset. New records default to pending approval and confidence 1.0 (a score,
never permission to approve). `updated_at` initially equals `created_at`.

Implementations validate nonempty ID/content, enum values, finite confidence in
[0, 1], timezone-aware UTC timestamps, updated_at >= created_at, expiration
strictly after creation, and a nonempty preference key for preference records.
Invalid input raises `ValueError`. Dataclasses are transport containers; apart
from filling initial timestamps they do not enforce these rules themselves.
Serialize enums by value, timestamps as ISO 8601 UTC, and paths as strings.

`MemoryStore` provides async create/retrieve/update/delete/list/search/clear.
Update is a full snapshot replacement (use `dataclasses.replace`); preserve
identity and creation time and set a new update time. Editing content/source/
preference key returns approval to pending. Approval changes use update too.
Create duplicates raise `ValueError`; missing updates raise `KeyError`;
retrieve returns None and delete returns False for missing IDs. Storage failures
raise `OSError`; cancellation propagates. Writes are atomic per method.

List/search apply `MemoryFilter`, exclude expired records by default, and include
all approval states unless filtered. Expired means expires_at <= current UTC
time. List sorts by updated_at descending then ID ascending; search ranks by
relevance with that same tie break. Empty/whitespace search returns (). Limits
and offsets must be nonnegative (zero limit returns ()); invalid values raise
`ValueError`. Retrieve and clear deliberately include all states for management.
Clear returns a deleted count and removes all memories, without deleting chat
history or curated knowledge files. Concurrent writers must be serialized by
the integration layer; no cross-method transaction or conflict detection is promised.

## Learning and retrieval

`LearningEngine` accepts `ExplicitFeedback`, proposes memories from text,
proposes preference replacements, and resolves contradictions. All four methods
are side-effect free with respect to storage: new proposals are pending and
superseded IDs are advisory. They must not silently delete or rewrite an approved
fact. A caller approves and persists the proposed replacement before retiring
the superseded records. Uncertain contradictions may retain both candidates for
review. None means no resolution; empty tuples mean no candidates. Explicit
feedback uses source explicit_feedback and its feedback ID as source_id;
automatic proposals use source automatic and the optional turn reference.

`MemorySettings` defaults: disabled, local storage, automatic learning off,
no default expiration. A None path resolves to
`platformdirs.user_data_path("Curio") / "memory.sqlite3"` in the storage
implementation. Session mode never writes memories to disk and ignores the path.
Expiration days, when set, must be a positive integer. Settings persistence and
TOML parsing belong to the configuration branch, not this module.

Disabled learning returns ()/None, performs no inference, and retrieval returns
an empty `MemorySelection`. Management operations remain available while disabled.
Automatic `off` blocks `propose_memories`; `propose` allows pending candidates
only. Explicit feedback and preference changes are allowed when enabled under
either automatic policy. No policy automatically approves or uploads memories.

`MemoryRetriever.select` owns access to a store supplied by its implementation's
constructor. It selects only approved, unexpired records relevant to the query.
It returns ordered snapshots and the exact `prompt_text` block to inject, plus
`token_count == count_tokens(prompt_text) <= token_budget`. The caller supplies
the target model's token counter; count labels and separators too. Budget zero,
blank query, disabled settings, or no fitting records returns the default empty
selection; negative budgets raise `ValueError`. Empty text counts as zero. Do
not truncate records to fit or approve candidates during retrieval. Prompt
integration treats memory text as untrusted contextual data, never instructions.
Recheck eligibility when selecting; cached deleted/rejected/expired entries must
not leak into later turns. Selection is a snapshot, not a lock across a model call.

## Events and UI

`MemoryEvents` exposes change and notification subscriptions, each returning an
idempotent unsubscribe callback. Store/settings adapters publish changes only
after successful mutation, in commit order, once per operation. Created/updated/
deleted events contain affected IDs; cleared/settings_changed events use ().
No-op deletes/empty clears emit nothing. Changes contain no raw content; listeners
reload snapshots. `MemoryNotification` carries a stable code, safe message,
severity and optional IDs (for example `memory.approval_required` or
`memory.storage_error`). Notification delivery does not imply persistence.

Callbacks are synchronous, brief, and delivered on the owning qasync loop;
worker adapters marshal onto that loop. Isolate listener exceptions so a failed
UI callback cannot fail a committed write or prevent other listeners running.
The UI may forward payloads through `Signal(object)` without adding a Qt
dependency here. Event publishing, threading, and subscription lifecycle are
implementation responsibilities; the protocol only standardizes consumption.

Storage, learning, retrieval/prompt integration, and settings/UI branches can
implement these interfaces independently. Keep this module the shared import
location; coordinate signature changes across all four branches.

Integration points in the current app: `config.py` can hold `MemorySettings`;
`app.py` constructs implementations and wires callbacks; `CompanionManager`
can await retrieval before building a request and propose learning only after
a successfully completed turn. Keep `ConversationHistory`'s ten-turn buffer and
the curated `knowledge_base.py` independent of this store. These are extension
points, not changes made by this contract.

For contradiction handling, `None` means no replacement proposal was produced;
the caller must not interpret it as approval or permission to persist the input.
A resolution with empty `superseded_ids` proposes an addition without retiring
existing records. The integration layer owns review and serialized application
of replacements; the protocols do not promise an atomic multi-record operation.
