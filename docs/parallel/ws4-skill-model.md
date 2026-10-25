# WS4: skill model (what this user knows)

You own `curio/skills/`. Read `docs/parallel/README.md` and
`curio-py/curio/learning_contract.py` first. Look at `ui/memory_window.py`
for the existing window style, and `docs/memory-contract.md` for the privacy
expectations (local, visible, resettable).

The skill model is separate from the memory store on purpose: it updates
after every walkthrough with numbers, with no per-record approval. Replace
approval with transparency: every skill and the evidence behind it is visible
and resettable.

## 1. Model: `curio/skills/model.py`

`SqliteSkillModel(path: Path, *, graph: ConceptGraph, difficulty: DifficultyProvider | None = None, clock=...)`
implementing `SkillModel`; default file
`user_data_path("Curio") / "skills.sqlite3"`. Store per-concept state and
the evidence events behind it.

**Bayesian knowledge tracing** per concept, for each step's concepts:
- Correct = `SUCCEEDED`, incorrect = `RETRIED` or `TIMED_OUT`; `ABANDONED`
  is ignored.
- Weight evidence by assistance, because watching isn't doing: `NONE` 1.0,
  `HINTED` 0.7, `POINTED` 0.35, `DID_IT` 0.
- **Difficulty weighting (item response theory, lightly):** when a
  `DifficultyProvider` gives a step difficulty `d`, succeeding on a hard step
  counts more and failing on it counts less.
- **Forgetting:** mastery decays toward the prior with a half-life of about
  14 days since last practice, applied when read.
- Starting parameters around p_init 0.2, p_learn 0.15, p_slip 0.1,
  p_guess 0.2. Keep them in one dataclass so they're easy to tune.

## 2. Transfer between apps: `curio/skills/concepts.py`

`ConceptGraph` loaded from a small bundled JSON file: related concepts with
weights and per-app names (layers ↔ frames for photoshop/figma, vlookup →
xlookup, keyframes → timeline, cell references → formulas, …). An unseen
concept's starting mastery borrows from related known ones at partial
strength. `prompt_context` uses this for lines like "the user knows layers
well from photoshop; in figma the same idea is frames". At most two sentences.

## 3. Advice

`recommend_assistance(app, concepts)`: the weakest relevant concept decides.
Starting bands: < 0.15 → `DID_IT`, < 0.45 → `POINTED`, < 0.8 → `HINTED`,
otherwise `NONE`. Integration decides whether `DID_IT` is honoured.

## 4. Skills window: `curio/skills/widget.py`

`SkillsWidget(model: SkillModel, parent: QWidget | None = None)`: the "skill
map". Concepts grouped by app with mastery bars, attempts and last practiced,
a "why?" view of the evidence, reset per concept and reset all, export JSON.
Refreshes when a walkthrough is observed (expose a Qt signal or a `refresh()`
slot). It's a headline demo visual, so it should look polished and match
`design_system.py`. Don't register it in the tray; WS1 does that.

## 5. Demo helper: `python -m curio.skills.demo --path ...`

Fills a model with a believable history (strong in photoshop layers, new to
figma) so transfer shows up in the demo.

## Done when

Deterministic tests (injected clock) cover BKT updates, assistance and
difficulty weighting, decay, transfer, advice bands, reset, and an offscreen
widget smoke test like `test_memory_window.py`. Write `docs/skills.md` and
`docs/parallel/handoff-ws4.md` with constructor signatures for WS1.
