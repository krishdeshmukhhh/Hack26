# F2: check-in policy, resume notes, breaks

You own `curio/focus_policy/`. Read `docs/parallel-focus/README.md`,
sections A, C, D, E and F of `docs/focus-learning-research.md`, and
`curio-py/curio/focus_contract.py`. You consume `FocusSignal`s (F1 produces
them; build against scripted signals) and produce `Intervention`s (F4 shows
them).

## 1. `AdaptiveFocusPolicy` (implements `FocusPolicy`)

**Deciding whether to step in** (section C):
- **Vulnerable and receptive:** after `DRIFT_STARTED`, wait for the next
  `BREAKPOINT` signal before any spoken check-in. If no breakpoint arrives
  within a cap (for example 2 minutes), allow one anyway.
- **Escalation ladder** per drift episode: `AMBIENT_CUE` →
  `CHECK_IN` → `PLAN_REMINDER` (only if the plan has an if-then plan for
  this app). One rung at a time, with spacing between rungs. `strict` mode
  shortens the spacing; it never blocks anything.
- **Limits:** a maximum number of spoken interventions per hour (default 3),
  snooze (`SNOOZED` silences for N minutes), and quiet hours. Frequency
  scales with an injected 0..1 `interaction_frequency` (from the memory
  system's adaptive values).
- **Learning from responses:** `FALSE_ALARM` responses should be passed to
  the classifier by F4. Here they also lower how quickly you escalate for
  that app. Repeated `IGNORED` check-ins back off.
- On `RETURNED` after a drift: a `RESUME` intervention if there's a resume
  note, otherwise nothing (no lecture, no guilt).

**Message wording** (section C): offer choices, never orders. Use templates
with several variants per kind, rotated, with a one-time "new style of
check-in" note when a variant first appears (HabitLab finding). Include the
learner's own goal and if-then words. Optional `ModelCall` to rephrase, with
the templates as fallback; validate that model output is short and contains
no commands ("stop", "you must"). Every intervention's `choices` includes a
"not a distraction" option and its `rationale` letter.

Add tests that scan every template for banned controlling phrases.

## 2. Resume notes (section D)

- `set_resume_note` / `resume_note`. Generate a note automatically on
  `DRIFT_STARTED` from the latest context F4 passes in (the current
  walkthrough step or the session plan). Keep only the newest.
- `RESUME` message: "you were on <where>, about to <next>."

## 3. Breaks (section E)

- `BREAK_DUE` → `BREAK_START` ("time for a five-minute break, want to
  stretch?"), with "keep going" and "start break" choices. `BREAK_OVER` →
  `BREAK_END`, plus a resume note. Self-paced style: suggest a break only
  after a long stretch with no break. Frame breaks as energy, never as
  productivity.

## 4. Metacognitive prompts and reflection (sections F and G)

- `METACOGNITIVE` at session start ("what's the first thing you'll do?"),
  roughly halfway ("how's it going against the plan?") and at
  `SESSION_ENDING`, then `REFLECTION` ("what got in the way today?"). Never
  during a drift or a break.

## 5. `SessionTally`

A small helper that accumulates on-goal, off-goal and break seconds, drift
count, interventions and false alarms from signals and responses, and
produces a `SessionSummary` at the end (F4 stores and shows it).

## Done when

Deterministic tests (injected clock, scripted signals) cover: no check-in
mid-thought, check-in at the breakpoint after a drift, the escalation order,
hourly limits, snooze, quiet hours, strict mode spacing, false-alarm and
ignored backoff, resume notes, both break styles, metacognitive timing,
rotation and the one-time notice, banned phrases in every template, model
output validation, and tally accuracy. Write `docs/focus-policy.md` and
`docs/parallel-focus/handoff-f2.md`.
