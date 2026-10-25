# Parallel build: focus and learning mode

Four workstreams build the mode specified in
[focus-learning-research.md](../focus-learning-research.md). Read that first:
every behaviour there has an evidence section (A–H), and code should carry
that letter in `rationale` fields so "why did Curio do that?" can be
answered.

All four branch from `feat/focus-foundation`, which adds
`curio-py/curio/focus_contract.py`. It builds on `feat/learning-foundation`,
so `learning_contract.py` (app_key, concept_key, SkillModel) is available too.

```
ActivitySource ─► TrackClassifier ─► DriftTracker ─► FocusSignal ─► FocusPolicy ─► Intervention ─► pet / voice
   [F1]              [F1]               [F1]                          [F2]                         [F4]

LearnerEvent ─► StudyCoach.next_move ─► TutorDirective ─► prompt          ReviewItems ─► spaced review
                    [F3]                                    [F4]               [F3]           [F4]

FocusPlan (session start)  ·  SessionSummary (timeline, reflection)  ·  wiring          [F4]
```

## Workstreams

| WS | Branch | Worktree | Prompt |
|---|---|---|---|
| F1 | `feat/focus-sensing` | `.worktrees/focus-sensing` | [f1-sensing.md](f1-sensing.md) |
| F2 | `feat/focus-policy` | `.worktrees/focus-policy` | [f2-policy.md](f2-policy.md) |
| F3 | `feat/study-coach` | `.worktrees/study-coach` | [f3-study-coach.md](f3-study-coach.md) |
| F4 | `feat/focus-session` | `.worktrees/focus-session` | [f4-session.md](f4-session.md) |

## File ownership

| Owner | Exclusive files |
|---|---|
| F1 sensing | `curio/focus_sensing/`, `tests/test_focus_sensing*.py`, `docs/focus-sensing.md` |
| F2 policy | `curio/focus_policy/`, `tests/test_focus_policy*.py`, `docs/focus-policy.md` |
| F3 study coach | `curio/study_coach/`, `tests/test_study_coach*.py`, `docs/study-coach.md` |
| F4 session | `curio/focus_session/`, `tests/test_focus_session*.py`, `focus_contract.py` and its test, `docs/focus-session.md`, and, in its final step only, `app.py`, `companion_manager.py`, `config.py`, `config.example.toml`, `prompts.py`, `ui/tray_icon.py`, `docs/ARCHITECTURE.md`, `docs/RUNNING.md`, `docs/PROGRESS.md` |

Never edit another workstream's files. Contract changes, config keys and
dependencies go in `docs/parallel-focus/handoff-<ws>.md` for F4.

## Rules for every workstream

- Same rules as [docs/parallel/README.md](../parallel/README.md): match the
  repo's style, constructor injection, no work at import, SQLite off the UI
  thread, explicit file paths for tests, standard library plus existing
  dependencies, `uv run pytest` and `uv run ruff check <your files>`.
- Model access is the injected `ModelCall` from the contract. Everything must
  still work (rules only, templates only) when it's `None`.
- Privacy rules from the research doc are requirements, not suggestions: no
  keystroke content, no continuous screenshots, window titles leave the
  machine only through `ModelCall` and only when the user allows it.
- Use an injected clock everywhere, so tests are deterministic.
- Commit to your own branch. Don't push or merge. Finish with
  `docs/parallel-focus/handoff-<ws>.md`.

## Setup (run once from the repo root)

```powershell
git worktree add -b feat/focus-sensing .worktrees/focus-sensing feat/focus-foundation
git worktree add -b feat/focus-policy .worktrees/focus-policy feat/focus-foundation
git worktree add -b feat/study-coach .worktrees/study-coach feat/focus-foundation
git worktree add -b feat/focus-session .worktrees/focus-session feat/focus-foundation
```

In each terminal: `cd` into the worktree, start `claude`, paste:

> Read docs/parallel-focus/README.md, docs/focus-learning-research.md and docs/parallel-focus/fN-....md, then do the work described there.

## Relationship to the learning workstreams

The learning build (`docs/parallel/`) changes `companion_manager.py`,
`app.py` and `prompts.py` in its WS1. F4's final wiring step must happen
**after** `feat/learning-integration` is merged into `main`: F4 merges
`main` into its branch first, then wires. F1–F3 never touch those files, so
they can run at any time.

F3 uses `learning_contract.SkillModel` mastery when it's available (from the
learning WS4) and its own simple estimate otherwise.

## Merge order

1. F1, F2, F3 merge into `feat/focus-session`.
2. `main` (with the learning work) merges into `feat/focus-session`.
3. F4 wires everything, runs the full suite, and `feat/focus-session` merges
   into `main`.

## Demo script

1. "Curio, I'm doing my Excel assignment for 25 minutes." Curio helps
   phrase an if-then plan: "if I open YouTube, I'll say 'back to it'".
2. Open YouTube. After a short while, at the next app switch, the pet looks
   over, then asks: "still on the assignment? we can get back to it or take a
   real break."
3. Go back: "you were about to add the row fields."
4. Ask for the answer to a formula question: Curio gives a guiding question,
   then a hint, not the answer.
5. End the session: the timeline shows on-goal vs drift time, a two-question
   review, and "I'll ask you about VLOOKUP again on Tuesday."
