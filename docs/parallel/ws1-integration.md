# WS1: event log and integration

You own the event log and all wiring into the running app. Read
`docs/parallel/README.md` first, then `curio-py/curio/learning_contract.py`,
`companion_manager.py` (especially `_run_turn`, `_update_walkthrough`,
`_on_walkthrough_click`, `_end_walkthrough`), `prompts.py`, `point_parser.py`
and `docs/ARCHITECTURE.md` ("Guided walkthroughs").

The other three packages don't exist on your branch. Build against the
protocols with null implementations, and wire the real ones in the final step.

## 1. Event log: `curio/learning_events/`

- `SqliteEventLog(path: Path)` implementing `EventLog`; default file
  `user_data_path("Curio") / "learning_events.sqlite3"`. I/O via
  `asyncio.to_thread`, like `memory_store.py`.
- `null.py`: `NullTaskMap`, `NullSkillModel`, `NullMapSync` that do nothing
  and return `None`/empty, so the app runs before the other branches merge.

## 2. Concepts tag

- Add a `[CONCEPTS:a, b]` tag to the walkthrough part of the system prompt:
  one to three short, app-independent concept names for the skill the step
  exercises ("pivot tables", "layers", "keyframes"), not UI labels
  ("insert tab"). Only on walkthrough steps.
- Parse and strip it in `point_parser.py` like `[STEP:...]`, including in
  `_ANY_TAG_RE` and the partial-tag regex, so it's never spoken. Normalise with
  `concept_key`. Add tests next to `test_step_tags.py`.

## 3. Recording step events in `CompanionManager`

- At the walkthrough's opening question, store `walkthrough_id`,
  `app_key(get_foreground_window_title())` and `task_key(transcript)`.
- For each step answer, keep a pending step: instruction (spoken text),
  element (from the POINT tag, converted to 0..1 fractions: divide by 1000 for
  `norm1000`, by the screenshot's dimensions for `pixel`; keep the window title
  locally), concepts, assistance (`POINTED` with a POINT tag, otherwise
  `HINTED`; `DID_IT` is reserved for the hands-free mode being built
  separately, so leave a clear hook for it).
- Settle the pending step's outcome when the next thing happens:
  next answer has a higher STEP index → `SUCCEEDED`; same index → `RETRIED`;
  no STEP tag after a click (task finished) → `SUCCEEDED` and the walkthrough
  is `completed`; Esc, new push-to-talk or error → `ABANDONED`; timeout →
  `TIMED_OUT`. Append each settled event to the log.
- When the walkthrough ends, build a `WalkthroughSummary` and fan it out to
  `task_map.record`, `skill_model.observe` and (only if sharing is on)
  `map_sync.push`. Background tasks, exceptions logged, never blocking the turn
  or the UI.

## 4. Using the map and skills in a turn

For how-to questions (`is_howto_question`) and walkthrough continuations:

- `task_map.find(app, task)`: if there's a path, add it to that request as
  untrusted reference data (the same framing `build_system_prompt` uses for
  the knowledge base): "a verified path other users followed", with each
  step's instruction and element position in the active coordinate space.
  Tell the model to follow it but trust the current screen when they differ.
  WS2 will provide a `format_for_prompt(...)` helper; until then write a
  simple local one you can swap out.
- `skill_model.recommend_assistance(app, concepts)` and `prompt_context(...)`,
  with concepts from the path's steps when there is one. Map the advice to
  one prompt line, for example `NONE`/`HINTED` → "the user has done this
  before: give a short spoken hint and point only if they ask".
- Keep everything inside the existing ~10-exchange history rules: these
  additions go into the request only, not stored history, like
  `walkthrough_reminder`.

## 5. Config and tray

- `[learning]` section: `enabled = true`, `share_walkthroughs = false`,
  `sync_url = ""`. Validate in `config.py`, document in
  `config.example.toml`, persist the toggle the way pet selection is persisted.
- Tray: "Skills…" (opens WS4's widget in a small window; placeholder until
  merged) and a checkable "Share walkthroughs anonymously".

## 6. Final step (after WS2–4 merge into your branch)

Read their `docs/parallel/handoff-*.md`, construct the real
implementations in `app.py`, apply any requests (dependencies, PyInstaller
data files for WS3's dashboard, a `pyproject` script entry for the map
server), and run the full suite. Then update `ARCHITECTURE.md`,
`RUNNING.md` and `PROGRESS.md`.

## Done when

- A full walkthrough with fakes produces correct `StepEvent`s and one
  summary (unit tests with fake LLM/TTS like the existing manager tests).
- The concepts tag is parsed, stripped and never spoken.
- Verified-path and skill lines appear in how-to requests only.
- All existing tests still pass.
