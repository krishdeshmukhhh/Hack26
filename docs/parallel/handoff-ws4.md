# Handoff: WS4 skill model

Branch `feat/skill-model`. Owned files: `curio-py/curio/skills/`,
`curio-py/tests/test_skills*.py`, `docs/skills.md`. Design notes are in
[../skills.md](../skills.md).

## Public API

```python
from curio.skills import ConceptGraph, SqliteSkillModel, BktParams, default_path
from curio.skills.widget import SkillsWidget   # Qt; package root stays Qt-free

graph = ConceptGraph.load()                     # bundled curio/skills/concepts.json
model = SqliteSkillModel(
    path: Path | None = None,                   # None -> user_data_path("Curio")/"skills.sqlite3"
    *,
    graph: ConceptGraph,
    difficulty: DifficultyProvider | None = None,   # pass the MapSync instance
    clock: Callable[[], datetime] = now_utc,
    params: BktParams = BktParams(),
)
```

`SqliteSkillModel` implements `SkillModel` (`observe`, `snapshot`,
`recommend_assistance`, `prompt_context`, `reset`). Extras:

| Member | Use |
|---|---|
| `subscribe(callback) -> unsubscribe` | called after each change, on the awaiting (Qt/qasync) thread |
| `mastery(app, concepts) -> dict[str, float]` | effective mastery per canonical concept |
| `evidence(concept, limit=200)` | `SkillEvidence` rows, newest first |
| `reset_concept(concept) -> bool` | forget one concept |
| `export_data() -> dict` | JSON-ready dump |
| `graph`, `params`, `path` | read-only |

`SkillsWidget(model, parent=None, *, clock=None)`: signals `refreshed()`
and `operation_finished(str, bool)`, slot `refresh()`. It subscribes to the
model on show and unsubscribes on close.

## Notes for wiring

- Construct and call everything on the qasync loop. SQLite runs in
  `asyncio.to_thread` with a connection per call, and writes are serialised
  with an `asyncio.Lock`. `DifficultyProvider.step_difficulty` is called on the
  loop thread, as the contract says.
- `observe` canonicalises the app (`"Adobe Photoshop 2024"` → `photoshop`) and
  the concepts (`frames` in figma → `layers`). Pass the same raw app and
  concepts to `recommend_assistance` and `prompt_context`; they canonicalise
  too.
- `recommend_assistance(app, [])` returns `POINTED` (the prior). A single
  unassisted failure on a new concept can return `DID_IT`; you decide whether
  hands-free mode honours it.
- `observe` is idempotent per `StepEvent.id`, so it's safe to retry.
- A provider that raises is treated as "no difficulty data".
- Demo: `uv run python -m curio.skills.demo --path <file> --reset --show`.

## Requests for WS1

1. **PyInstaller data file.** Add this to `datas` in `curio.spec`:
   `("curio/skills/concepts.json", "curio/skills")`. Without it,
   `ConceptGraph.load()` fails in the frozen build. Hatch wheels already
   include it.
2. **Tray entry.** Add a "Skills" entry that shows, raises and refreshes one
   `SkillsWidget(model)`, like Memories.
3. **Fan-out.** After each walkthrough: `await model.observe(summary)`. The
   open window refreshes itself.
4. **Prompt.** Before a how-to turn, add
   `await model.prompt_context(app, concepts)` and the
   `recommend_assistance` level to the prompt.
5. No new dependencies, config keys or contract changes are needed.
   Optionally, a `skills.enabled` config key could skip `observe` and
   prompt_context; that's your call.

## Done and verified

- 26 skill tests (`tests/test_skills_*.py`): BKT maths, assistance and
  difficulty weighting, decay with an injected clock, cross-app and
  related-concept transfer, advice bands, prompt sentences, idempotence,
  reset (one and all), listeners, export, persistence, demo data, and
  offscreen widget tests (grouping, bars, evidence, live refresh, reset,
  export, plain-protocol model, failure path, no event loop).
- Whole suite: 433 passed. `ruff check` is clean on the owned files.
- Checked the window visually with an offscreen render of the demo data.

## Not verified

- The window inside the running app with the tray and qasync. The tests use
  `asyncio.run`, and the demo `--show` path uses qasync but wasn't run
  interactively here.
- The frozen PyInstaller build (needs request 1).
- Real `[CONCEPTS:...]` tags from the model. The graph covers common
  photoshop, figma, excel, sheets and video-editing concepts. Unknown concepts
  still work, just without transfer.
- Tuning against real usage. All parameters are the spec's starting values,
  apart from `p_learn_after_failure` explained in `docs/skills.md`.
