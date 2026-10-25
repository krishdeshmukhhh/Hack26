# WS2: task map (verified paths on this machine)

You own `curio/task_map/`. Read `docs/parallel/README.md` and
`curio-py/curio/learning_contract.py` first. Glance at
`docs/ARCHITECTURE.md` ("Guided walkthroughs") to see where summaries come
from, but don't edit any integration files.

## What to build

`SqliteTaskMap(path: Path, *, clock=...)` implementing `TaskMap`; default
file `user_data_path("Curio") / "task_map.sqlite3"`, I/O off the UI
thread.

### `record(summary)`
- Ignore summaries that aren't `completed`.
- Turn the steps into a clean path: for each step index keep the last
  `SUCCEEDED` attempt, drop retries, renumber from 1.
- If a path for the same app and a matching task has the same sequence of
  element labels, increase its `verified_count`. If the sequence differs,
  store it as an alternative.
- **Self-healing:** if an app update moves a button, new successful paths
  stop matching old ones. Prefer the alternative with the most *recent*
  verifications (for example, count the last 30 days double), so a fixed path
  overtakes a stale one after a few users. Test this explicitly.

### `find(app, task)`
- Loose matching on `task_key` text with the standard library: token
  overlap plus `difflib.SequenceMatcher`, a threshold, and a small synonym
  table ("make" ≈ "create", "turn on" ≈ "enable"). Return the best path, or
  `None` below the threshold. Test near-misses that should and shouldn't match.

### `merge(shared)`
- Store `PathSource.SHARED` paths from map sync alongside local ones. Prefer a
  local path when its verifications are comparable; otherwise the stronger
  shared one. Keep each step's `difficulty`. Idempotent: merging the same
  pull twice changes nothing.

### `format_for_prompt(path, point_coords: str, image_size: tuple[int, int] | None) -> str`
- A module-level helper integration will put in the request: numbered
  steps, each with the instruction, element label and position converted
  from 0..1 into the active coordinate space (`norm1000` → 0–1000;
  `pixel` → the screenshot's pixels). Plain lowercase text suited to the
  existing prompt style. Mark hard steps ("most people get stuck here")
  when `difficulty` is high.

### `LocalDifficulty`
- Implements `DifficultyProvider` from this machine's own history (share of
  retried/timed-out attempts per step), so the skill model gets a difficulty
  signal even without the shared server. Synchronous and cached.

## Done when

Unit tests cover recording, retry clean-up, verification counting,
self-healing, fuzzy finding, merge idempotence and both coordinate formats.
Write `docs/task-map.md` (short) and `docs/parallel/handoff-ws2.md` with
the constructor signatures for WS1.
