# Memory in AI conversations

`ConversationMemory` in `curio.memory_conversation` uses only `MemoryStore`.
Pass it as the optional keyword `memory=` to `CompanionManager`. No database or
memory UI implementation is coupled to the conversation pipeline.

The application constructs it through `MemoryRuntime` with the configured store,
`MemorySettings`, the current model's `count_tokens(text)` function, and an
explicit `token_budget` (default 512). Without an adapter, existing behavior is
preserved. Replace `adapter.settings` when settings change, and update the token
counter when switching models. The budget covers the entire rendered memory
block, including labels and JSON escaping; it is separate from response tokens,
conversation history, screenshots, and curated knowledge. No tokenizer or provider
is guessed. A counter appropriate for the configured model is required.

Before an ordinary model request, `select` searches approved, nonexpired memories
and rereads each result through the store to reject stale snapshots. Search
provides relevance order. Whole records are added only if the complete context
fits the budget. Blank queries, zero budget, or disabled memory skip retrieval.
Reads time out after one second by default; failures omit memory and let the AI
turn proceed. Cancellation propagates. Selection is a snapshot, with the same
concurrency limits as the shared contract.

Memory is added as a text block in the current **user** message, separate from
the actual question and screenshots. It never enters the system prompt or stored
conversation history. Static system rules mark memory and external reference
content as untrusted. JSON encoding makes boundaries explicit; this is not a
claim that prompt injection can be completely prevented. Neither provider output
nor retrieved content is passed to command handling.

Explicit commands are recognized only at the beginning of a full user turn:

- `remember that <text>` creates a pending fact or supported preference through
  the connected engine with source `explicit_feedback`, applying the configured
  expiration. Without an engine, the adapter proposes a `user` fact instead.
- `forget memory <UUID>` validates the exact UUID, checks existence and calls
  `delete`. Ambiguous `forget` requests explain the syntax and perform no deletion.
  Bulk deletion is deliberately left to memory management.
- `recall <query>` returns approved relevant memories with IDs under the same
  budget. The application answers directly and never interprets recalled POINT
  or STEP tags as actions.

Commands are handled locally before screenshot capture and model dispatch, then
use the existing completion/history/TTS path. Disabled memory refuses commands
without accessing storage. Command failures produce a generic local response;
they never claim success or fall through to a model that might invent success.
Mutations that finish before cancellation remain committed, as specified by the
store contract. Ordinary conversation is never archived. With the connected rule engine and
explicit `automatic_learning = "propose"`, successful user turns may contribute
bounded preference signals and create pending suggestions after repetition.

The existing Anthropic request format and OpenAI-compatible conversion carry the
same user-context block. Groq and local endpoints using that OpenAI-compatible
client require no special memory API. This change does not add provider selection
or add new providers; `app.py` supplies the real runtime adapter.

Tests use mock stores and fake streaming/TTS providers. Existing walkthrough and
conversation tests cover the preserved voice, cancellation, history and pointing
paths; no network, live model, SQLite, or memory UI is required.

The integrated runtime uses a conservative UTF-8-byte counter with a 512-unit
allowance by default; inject an exact model tokenizer when available. Global
approved response preferences are relevant across ordinary questions and carry
their preference key in JSON. Connected explicit feedback uses the rule engine
to produce pending preferences/facts; approval occurs in the memory window.
