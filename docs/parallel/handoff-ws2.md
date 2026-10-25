# Handoff: WS2 task map

Branch `feat/task-map`. Only `curio/task_map/`, `tests/test_task_map.py`,
`docs/task-map.md` and this file were touched. No new dependencies, config
keys or contract changes.

## Public API (`from curio.task_map import ...`)

```python
SqliteTaskMap(path: Path | None = None, *, clock: Callable[[], datetime] = utc_now)
    # path=None -> default_path() = user_data_path("Curio") / "task_map.sqlite3"
    async record(summary: WalkthroughSummary) -> TaskPath | None
    async find(app: str, task: str) -> TaskPath | None
    async paths(app: str | None = None) -> tuple[TaskPath, ...]
    async merge(shared: Sequence[TaskPath]) -> int
    async refresh_difficulty() -> None      # loads history into local_difficulty
    async close() -> None                   # or `async with SqliteTaskMap(...)`
    local_difficulty: LocalDifficulty       # DifficultyProvider, sync + cached

format_for_prompt(path: TaskPath, point_coords: str, image_size: tuple[int, int] | None) -> str
    # point_coords: "norm1000" | "pixel"; anything else raises ValueError

LocalDifficulty(min_attempts: int = 1)
    step_difficulty(app, task, step_index) -> float | None
task_similarity(a, b, app="") -> float;  tasks_match(a, b, app="") -> bool
clean_steps(events) -> tuple[PathStep, ...];  default_path() -> Path
```

## Suggested wiring for WS1

1. Construct one `SqliteTaskMap()` at startup, then `await task_map.refresh_difficulty()`
   (until it's called, `local_difficulty` returns None for everything; any
   other async call also loads it). Close it at shutdown.
2. When a walkthrough ends: `await task_map.record(summary)` for every
   summary, completed or not. Incomplete ones only update difficulty counts.
3. After a map-sync pull: `await task_map.merge(await map_sync.pull(app))`.
4. Before a how-to turn: `path = await task_map.find(app_key(title), task_key(question))`.
   If it's not None, add `format_for_prompt(path, config.point_coords, (w, h))` to the
   request, using the pixel size of the screenshot the model sees.
5. Skill model: pass `task_map.local_difficulty` as the `DifficultyProvider`
   when map sync is off. When it's on, a fallback like
   `sync.step_difficulty(...) ?? local.step_difficulty(...)` makes sense.

## Behaviour notes

- `record` stores `task_key(summary.task)`. `find` and `step_difficulty`
  accept raw or normalised text.
- Steps from local paths have `difficulty=None`, unless a shared path with the
  same label sequence exists. Then `find` copies its difficulty across.
- Local `ElementRef.window_title` is stored on this machine only. `merge`
  clears it on shared rows.
- Tuning constants are module-level: `MATCH_THRESHOLD = 0.7`,
  `RECENT_WINDOW = 30 days`, `RECENT_WEIGHT = 2`, `LOCAL_PREFERENCE = 1.5`,
  `HARD_STEP_DIFFICULTY = 0.4`.

## Verified

`uv run pytest` passes in this worktree (447 tests; 40 new in
`tests/test_task_map.py`) and `ruff check` is clean. The tests cover
recording, retry cleanup, verification counting, self-healing, fuzzy finding
(near-misses that should and shouldn't match), merge idempotence,
local-vs-shared preference, both coordinate formats and local difficulty.

## Not verified

- I haven't run it with real walkthrough summaries from the app. The
  thresholds come from hand-picked examples, not from logged questions.
- Concurrent use from two processes (one SQLite file, 2 s busy timeout) hasn't
  been tested.
- Nothing prunes old paths, verifications or step stats yet. Fine for demo
  scale.
