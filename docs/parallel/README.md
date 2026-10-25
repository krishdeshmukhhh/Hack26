# Parallel build: task map + skill model

Four workstreams build "every person Curio helps makes it better for the next
person" in parallel git worktrees. All four branch from the foundation commit
that adds `curio-py/curio/learning_contract.py`, and code against it.

```
walkthrough step ──► StepEvent ──► EventLog (local SQLite)          [WS1]
                                     │ walkthrough ends
                                     ▼
                              WalkthroughSummary
                 ┌───────────────────┼────────────────────┐
                 ▼                   ▼                    ▼
           TaskMap.record      SkillModel.observe    MapSync.push
           verified paths      per-concept mastery   anonymous, opt-in
              [WS2]                [WS4]                [WS3]
                 ▲                   ▲                    │
                 │ merge(pull())     │ step_difficulty()  │
                 └───────────────────┴────────────────────┘
```

Before a how-to turn, integration asks the task map for a verified path and
the skill model for how much help to give, and puts both in the prompt.

## Workstreams

| WS | Branch | Worktree | Prompt |
|---|---|---|---|
| 1 | `feat/learning-integration` | `.worktrees/integration` | [ws1-integration.md](ws1-integration.md) |
| 2 | `feat/task-map` | `.worktrees/task-map` | [ws2-task-map.md](ws2-task-map.md) |
| 3 | `feat/map-sync` | `.worktrees/map-sync` | [ws3-map-sync.md](ws3-map-sync.md) |
| 4 | `feat/skill-model` | `.worktrees/skill-model` | [ws4-skill-model.md](ws4-skill-model.md) |

## File ownership (the rule that keeps merges clean)

| Owner | Exclusive files |
|---|---|
| WS1 integration | `curio/learning_events/`, `companion_manager.py`, `app.py`, `config.py`, `config.example.toml`, `prompts.py`, `point_parser.py`, `ui/tray_icon.py`, `curio.spec`, `pyproject.toml`, `uv.lock`, `learning_contract.py` and its test, `docs/ARCHITECTURE.md`, `docs/PROGRESS.md`, `docs/RUNNING.md`, `docs/features.md` |
| WS2 task map | `curio/task_map/`, `tests/test_task_map*.py`, `docs/task-map.md` |
| WS3 map sync | `curio/map_sync/`, `tests/test_map_sync*.py`, `docs/map-sync.md` |
| WS4 skill model | `curio/skills/`, `tests/test_skills*.py`, `docs/skills.md` |

Never edit another workstream's files. If you need a contract change, a new
dependency, a config key or a tray entry, write it in your
`docs/parallel/handoff-<ws>.md` and WS1 applies it.

## Rules for every workstream

- Code against `curio.learning_contract`. Match the repo's style: frozen
  dataclasses, `from __future__ import annotations`, constructor-injected
  dependencies, no work at import time, SQLite I/O off the UI thread with
  `asyncio.to_thread` (see `memory_store.py`).
- Standard library plus existing dependencies only (`httpx`, `PySide6`,
  `platformdirs` are available).
- Local files go under `platformdirs.user_data_path("Curio")`, and every
  store takes an explicit path so tests use `tmp_path`.
- Tests: `cd curio-py && uv sync --extra local && uv run pytest`. Each
  worktree has its own `.venv`. If `uv` is missing, install it first:
  `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`.
  `uv run ruff check <your files>` must pass.
- Commit to your own branch as you reach milestones. Don't push or merge.
- Finish by writing `docs/parallel/handoff-<ws>.md`: public constructors and
  their signatures, what's done, what isn't verified, requests for WS1.

## Setup (run once from the repo root)

```powershell
git worktree add -b feat/learning-integration .worktrees/integration feat/learning-foundation
git worktree add -b feat/task-map .worktrees/task-map feat/learning-foundation
git worktree add -b feat/map-sync .worktrees/map-sync feat/learning-foundation
git worktree add -b feat/skill-model .worktrees/skill-model feat/learning-foundation
```

Then in each terminal, `cd` into its worktree, start `claude`, and paste:

> Read docs/parallel/README.md and docs/parallel/wsN-....md, then do the work described there.

## Merge order

1. WS2, WS3 and WS4 merge into `feat/learning-integration`. They touch
   disjoint files, so they shouldn't conflict.
2. WS1 does its final wiring step: replaces the null implementations with the
   real ones and runs the whole suite.
3. `feat/learning-integration` merges into `main`.

## Demo script (what this is all for)

1. Laptop A: "how do I insert a pivot table?" Curio walks through it, the user
   finishes, and the path is pushed to the map server.
2. Laptop B, same question: the guide follows the verified path on the first try.
3. The map server's dashboard shows a heatmap of where users got stuck.
4. The skills window on laptop A shows "pivot tables" mastery rising. Asked
   again, Curio only gives a hint instead of pointing at every step.
