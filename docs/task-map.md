# Task map

`curio/task_map/` remembers the click paths that finished a task on this
machine, plus the paths pulled from the shared map, so the next walkthrough
for the same task can follow a known-good path.

## Recording

`SqliteTaskMap.record(summary)` runs after every walkthrough.

- Every step event updates per-step attempt counts, including events from
  walkthroughs that never finished, because those are where people get stuck.
  `LocalDifficulty` reads these counts.
- Only `completed` summaries become paths. For each step index the last
  `SUCCEEDED` attempt is kept, retries and abandoned attempts are dropped, and
  the steps are renumbered from 1.
- A path is identified by its sequence of element labels (case and spacing
  ignored). If a local path for the same app and a matching task has the same
  sequence, it gets another verification and its steps are replaced with the
  newest positions. If the sequence differs, the path is stored as an alternative.

## Choosing a path (self-healing)

Each local verification is timestamped. A path's strength is the number of
verifications, with those from the last 30 days counted twice. When an app
update moves a button, old paths stop being reinforced and the new one
overtakes them: five verifications from two months ago (strength 5) lose to
three from this week (strength 6).

Shared paths use their `verified_count` as their strength. Local strength is
multiplied by 1.5 and a local path wins ties, so a local path wins unless the
shared one is clearly stronger. If the chosen local path has the same label
sequence as a shared one, it takes the shared path's step difficulty.

## Matching tasks

`task_similarity` puts both texts through `task_key`, then a synonym table
("make" → "create", "turn on" → "enable", "add" → "insert", …), drops
stopwords, the app's own name and trailing plural "s". The score is
0.6 × token Jaccard + 0.4 × `difflib.SequenceMatcher` ratio, and the threshold
is 0.7. A pair with opposite verbs (enable/disable, show/hide, insert/delete, …)
scores 0. `find` keeps the candidates within 0.15 of the best match and picks
the strongest of them.

## Merging shared paths

`merge(paths)` stores pulled paths as `shared` rows. A shared path is
identified by app, task and label sequence, not by its id, because
`path_from_wire` makes a new id on every pull. Merging the same pull twice
returns 0. Step difficulty is kept and window titles are cleared.

## Prompt text

`format_for_prompt(path, point_coords, image_size)` renders numbered
lowercase steps with the target label and its position: on the 0–1000 grid
for `norm1000`, or in screenshot pixels for `pixel`. In pixel mode with no
`image_size`, positions are left out. Steps with `difficulty >= 0.4` get
"most people get stuck here".

## Storage

The default location is `user_data_path("Curio") / "task_map.sqlite3"`.
It has three tables: `paths`, `verifications` and `step_stats`. Schema
version 1 is stored in `PRAGMA user_version`. All I/O runs on a single
worker thread.
