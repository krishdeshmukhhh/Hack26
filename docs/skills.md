# Skill model

What this user knows, per concept, so Curio can decide how much help to give.
Code: `curio-py/curio/skills/`. Contract: `SkillModel` in
`curio/learning_contract.py`.

## Privacy

The skill model updates after every walkthrough with no per-record approval,
unlike the memory store. Transparency takes the place of approval:

- **Local.** One SQLite file, `user_data_path("Curio")/skills.sqlite3`.
  Nothing here goes to map sync or anywhere else.
- **Visible.** The skills window shows every concept, its mastery, attempts,
  last practice, and the step-by-step evidence behind it ("why?").
- **Resettable.** Reset one concept (and its evidence) or everything. Export
  everything as JSON.

Stored per piece of evidence: app, task text, step instruction, outcome,
assistance level, crowd difficulty, the weight it counted for, and mastery
before and after. No window titles, screenshots or audio.

## How mastery is computed

Each concept holds a probability that the user knows it (Bayesian knowledge
tracing). All numbers live in `BktParams`.

| Parameter | Default | Meaning |
|---|---|---|
| `p_init` | 0.2 | prior for a concept never seen |
| `p_learn` | 0.15 | chance of learning from a successful step |
| `p_learn_after_failure` | 0.05 | chance of learning from a failed step |
| `p_slip` | 0.1 | knows it but still fails |
| `p_guess` | 0.2 | doesn't know it but succeeds |
| `half_life_days` | 14 | forgetting half-life |
| `cross_app_transfer` | 0.75 | share of mastery carried to a new app |
| `difficulty_strength` | 0.5 | how much crowd difficulty matters |

**Evidence.** `SUCCEEDED` counts as correct; `RETRIED` and `TIMED_OUT` count
as incorrect; `ABANDONED` is ignored. Steps without concepts are skipped.

**Assistance weighting**, because watching isn't doing: `NONE` 1.0,
`HINTED` 0.7, `POINTED` 0.35, `DID_IT` 0 (ignored). The weight tempers the
observation's likelihoods (a power posterior: weight 0 means no evidence and
above 1 counts extra), and the learning transition is scaled by `min(w, 1)`.

**Difficulty weighting.** When a `DifficultyProvider` returns `d` (share of
users who got stuck), the weight is multiplied by `1 + (d - 0.5)` on success
and `1 - (d - 0.5)` on failure (with strength 0.5). A success on a hard step
counts up to 1.5x; a failure on a hard step costs half as much. Provider errors
are treated as "unknown".

**Why the failure learning rate is lower.** With a single `p_learn` of 0.15,
mastery after any step is at least 0.15, so the `DID_IT` band (< 0.15) could
never be reached. With 0.05 after failures, one unassisted failure from the
prior lands at about 0.08.

**Forgetting.** Mastery decays toward `p_init` with the half-life, applied
when read (`snapshot`, advice, prompt context) and before each new update.

**Idempotence.** Evidence is keyed by step event id and concept, so observing
the same summary twice changes nothing.

## Transfer: `concepts.json`

`ConceptGraph` loads `curio/skills/concepts.json`:

- `apps`: app-name aliases (`"adobe photoshop": "photoshop"`). Trailing years
  and versions are stripped first, so "adobe photoshop 2024" works.
- `concepts`: canonical concepts with per-app names (`layers` is `frames` in
  figma) and global aliases (`pivottable` → `pivot tables`).
- `related`: undirected `[a, b, weight]` edges (vlookup–xlookup 0.8,
  keyframes–timeline 0.6, cell references–formulas 0.6, ...).

Two kinds of transfer:

1. **Same concept, new app.** "frames" in figma is canonical `layers`. If the
   user practiced layers only in photoshop, figma gets
   `p_init + 0.75 * (mastery - p_init)`.
2. **Related concept.** An unseen concept starts at
   `p_init + max(weight * (neighbour - p_init))` over known neighbours. The
   first real evidence starts from that value.

## Advice

`recommend_assistance(app, concepts)` takes the weakest relevant concept (or
the prior if none are given) and maps it to a band:

| Mastery | Advice |
|---|---|
| < 0.15 | `DID_IT` (integration decides whether to honour it) |
| < 0.45 | `POINTED` |
| < 0.8 | `HINTED` |
| otherwise | `NONE` |

`prompt_context(app, concepts)` returns at most two sentences, or `None`:

- "The user knows layers well from photoshop; in figma the same idea is frames."
- "The user knows vlookup well, which is closely related to xlookup."
- "The user is already comfortable with charts in excel; keep it brief."
- "The user is still learning pivot tables in excel; explain each step."

## Skills window

`SkillsWidget(model, parent=None, *, clock=None)` in `curio/skills/widget.py`:
concepts grouped by app with mastery bars coloured by advice band, attempts and
last practiced; a detail card with the band, related concepts and the evidence
list; reset one, reset all, export JSON. It refreshes itself while shown
(through `model.subscribe`), and `refresh()` is a public slot. A model with
only the bare `SkillModel` protocol still works; the evidence, per-concept
reset and full export are hidden or reduced.

## Demo

```powershell
cd curio-py
uv run python -m curio.skills.demo --path demo-skills.sqlite3 --reset --show
```

This fills about six weeks of history: strong photoshop layers, middling masks,
learning excel pivot tables, figma never opened. Asking about figma frames
gives `HINTED` plus the transfer sentence. Leave out `--path` to fill the real
skills file.
