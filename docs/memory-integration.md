# Continuous learning integration review

Reviewed on `main` at base `integration snapshot`. Implementations were supplied as modified
or untracked files. `git branch -avv` has no four memory workstream refs, so this
review covers available diffs/source additions, not four Git commit ranges. Git
metadata is read-only here; no staging, merges or integration commit are claimed.

| Reviewed workstream | Source / summary | Findings resolved |
| --- | --- | --- |
| Shared contract | `memory_contract.py`, `memory-contract.md` | Retained async protocols, pending approval, disabled defaults and event payloads. |
| Storage | `memory_store.py`, tests | Worker-based SQLite, local/session modes reviewed. Added policy reconfiguration retaining session data and management updates while disabled. Fixed invalid timestamp fixture. |
| Learning | `learning.py`, tests, `learning-engine.md` | Proposal-only engine was unwired. Connected snapshots, explicit feedback and opt-in successful-turn signals; approval owns contradiction retirement. |
| UI | `memory_window.py`, `tray_icon.py`, tests | Window/tray signal were unwired and approval was missing. Added approve/reject controls, shared runtime and settings callbacks. |
| Conversation | `memory_conversation.py`, manager, prompts, tests and summary | Real services were missing; lexical matching missed global preferences. Injected runtime, included preference keys/style preferences, and connected bounded learning. |

`memory_settings.py` parses/persists `[memory]`; `memory_runtime.py` serializes
store access and publishes safe callbacks on qasync. `app.py` shares one runtime
between UI and conversations and closes resources after the loop stops. Existing
config files default to memory disabled. The real initialization/shutdown path
is tested with mocked audio/hotkey/provider objects.

Approval persists a replacement before retiring contradictions. There is no
crash-atomic multi-record transaction: interrupted retirement can leave two
approved values. Retrieval keeps the newest eligible value per preference key.
Re-proposing a rejected/expired equivalent restores it to pending through update;
`MemoryStore.create` retains its insert/duplicate-ID semantics. General fact
contradictions remain limited to obvious negation detected by the rule engine.

Commands come only from user transcripts; model output cannot authorize deletion.
Recalled POINT/STEP text cannot trigger actions. Context is untrusted user-message
data. Automatic policy defaults off and only proposes pending preferences from
repeated user signals; ordinary conversations are not archived.

Verification: `uv run pytest` passes **295 tests** on Windows/Python 3.12.15.
Six real-component integration tests cover separate-process persistence,
approval/correction/reversal, disabled learning, session retention, actual Qt
controls/event refresh on qasync, preference-bearing mocked requests with TTS and
POINT, and app initialization/shutdown. Original pipeline suites also pass.
These prove request integration, not preference compliance by a live model.

`uv run ruff check .` reports **23 pre-existing violations in unchanged files**;
scoped integration lint passes. Restricted network access blocked uv's hatchling
sync, so checks used the installed environment with `UV_NO_SYNC=true` and a
workspace UV cache. No rules were disabled or unrelated lint cleanup performed.

Interactive Windows smoke was blocked by the Computer Use native pipe being
unavailable after retries/reset. Physical audio/desktop behavior, live Groq/local
responses, packaging and exact provider token accounting remain unverified.
The runtime defaults to a conservative 512 UTF-8-byte context allowance and accepts
an exact provider counter. See RUNNING.md for the remaining manual checklist.
