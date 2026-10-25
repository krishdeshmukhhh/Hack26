# Handoff: WS1 integration

Branch `feat/learning-integration`. Steps 1–5 of `ws1-integration.md` are
done. Step 6 (the final wiring) is waiting on WS3 and WS4.

## Public API (`from curio.learning_events import ...`)

```python
SqliteEventLog(path: Path | None = None)   # EventLog; default_event_log_path()
NullTaskMap(), NullSkillModel(), NullMapSync()
LearningServices(*, event_log, task_map, skill_model, map_sync, share_walkthroughs=False)
    record_step(event) / finish_walkthrough(summary)   # background, never raise
    refresh_shared(app=None)                           # pull -> task_map.merge
    async prompt_text(*, app, task, concepts, point_coords, image_size) -> str | None
    async drain()
    share_walkthroughs: bool                           # flipped by the tray
WalkthroughRecorder(*, app, task), PendingStep, element_from_point(tag, shots, coords, title)
curio.learning_events.skills_window.SkillsWindow(skill_model)   # placeholder
curio.config.LearningSettings, save_share_walkthroughs(path, enabled)
```

## What's in

- **Event log**: SQLite at `user_data_path("Curio")/learning_events.sqlite3`,
  I/O via `asyncio.to_thread`.
- **`[CONCEPTS:a, b]` tag**: asked for on walkthrough steps in the system prompt
  and the per-request reminder. `parse_concepts_tag` takes it from anywhere in
  the answer (max three, `concept_key`-normalised). It's in `_ANY_TAG_RE` and
  the partial-tag regex (now `[A-Z]{0,8}`), so it's never shown or spoken.
- **Recording** (`CompanionManager`): the first STEP answer starts a
  `WalkthroughRecorder` keyed on `app_key(window title)` and
  `task_key(question)`. Each answer leaves a pending step, which gets settled
  by the next one: a higher index means `SUCCEEDED`, the same or a lower one
  means `RETRIED`. When an answer comes back with no tag it's `SUCCEEDED` and
  `completed`. Esc, a new push-to-talk, cancel and errors give `ABANDONED`;
  timeout gives `TIMED_OUT`. `_end_walkthrough(outcome)` is the one place a
  walkthrough ends. Assistance is `POINTED` or `HINTED`;
  `CompanionManager._step_assistance` is the hook where hands-free mode
  returns `DID_IT`.
- **Bug fix along the way**: before this change, an exception in a
  continuation turn left the walkthrough half-alive with the click watcher
  off. It now ends the walkthrough (`ABANDONED`).
- **Fan-out**: every summary goes to `task_map.record` and
  `skill_model.observe`. It also goes to `map_sync.push` when sharing is on,
  and a successful push is followed by a pull and merge. The app pulls once
  at startup.
- **Turn context**: covers how-to questions and walkthrough continuations
  only. `task_map.find`, then the skill model, using the path's concepts or
  else the pending step's. It goes in as a text block in this request only,
  never in history. Bounded at 1.5 s and fails soft.
- **Config/tray**: `[learning] enabled / share_walkthroughs / sync_url`, with
  validation. The sharing toggle is persisted with a targeted TOML edit, the
  same way pet selection is. The tray has "Skills…" and a checkable "Share
  walkthroughs anonymously".

Tests: 444 pass (37 new across `test_concepts_tag.py`, `test_learning_events.py`,
`test_learning_integration.py`, `test_learning_config.py`, `test_learning_ui.py`).
`ruff check` is clean on every file WS1 owns. Pre-existing lint errors in
`clients/`, `hotkey.py` and others are untouched.

## Not verified

- Not run live. Nothing yet confirms the local Qwen model emits the
  CONCEPTS tag reliably, or that the hint-only line actually makes it drop
  pointing.
- The Skills window and the tray toggle have only been tested offscreen.

## Step 6 checklist (when WS3 and WS4 hand off)

1. Merge `feat/task-map` (done, see `handoff-ws2.md`), `feat/map-sync` and `feat/skill-model`.
2. `app._build_learning`: `SqliteTaskMap()` + `await refresh_difficulty()` at
   startup and `close()` at shutdown. Use the real map sync only when
   `sync_url` is set. Pass the skill model a `DifficultyProvider` that tries
   sync first and falls back to `task_map.local_difficulty`.
3. In `LearningServices._format_path`, replace the local formatter with
   `curio.task_map.format_for_prompt(path, point_coords, image_size)`. Keep
   the crowd-difficulty note if WS2's text doesn't already include it.
4. Swap `SkillsWindow` for WS4's widget. Apply the WS3 requests
   (dependencies, PyInstaller data, `pyproject` script).
5. Full suite. Then `ARCHITECTURE.md`, `RUNNING.md`, `PROGRESS.md`.
