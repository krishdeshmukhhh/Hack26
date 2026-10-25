# Focus policy: check-ins, resume notes, breaks, reflection

`curio/focus_policy/` decides **whether and how** Curio steps in during a
focus session. It consumes `FocusSignal`s (from F1's `DriftTracker`) and
returns `Intervention`s (F4 presents them). The evidence for each rule is in
[focus-learning-research.md](focus-learning-research.md); every intervention
carries that section letter in `rationale`.

Standard library only. No Qt, no I/O, no work at import. All timing uses an
injected clock, so tests are deterministic. **Nothing here blocks an app or
site, in strict mode or otherwise.**

| Module | Contents |
|---|---|
| `policy.py` | `AdaptiveFocusPolicy` (implements `FocusPolicy`), `PolicySettings`, `QuietHours` |
| `wording.py` | Templates, banned phrases, `MessageBook` (rotation), model rephrasing and validation |
| `tally.py` | `SessionTally` → `SessionSummary` |

## Deciding whether to step in (section C)

Act when the learner is **vulnerable** (drifting) **and receptive** (at a
breakpoint).

Each drift episode runs from `DRIFT_STARTED` until `RETURNED` (or a break)
and climbs a ladder one rung at a time:

1. `AMBIENT_CUE`: silent pet animation, `message == ""`. It fires on
   `DRIFT_STARTED` and needs no breakpoint.
2. `CHECK_IN`: a spoken question with choices.
3. `PLAN_REMINDER`: repeats the learner's own if-then plan. Offered only if an
   `IfThenPlan.cue_apps` entry matches the current app (exact `app_key`) or
   appears in the window title (case-insensitive).

After a rung, the next one becomes eligible after the **spacing**, which
defaults to 60 s. A spoken rung then waits for a `BREAKPOINT` signal. If no
breakpoint arrives within `breakpoint_cap` (2 min) of becoming eligible, the
next `DRIFT_CONTINUING` triggers it anyway. Once the ladder is used up, the
episode stays quiet.

Spacing = `rung_spacing / (0.5 + interaction_frequency)`
× false-alarm backoff for this app × ignored backoff × 0.5 in strict mode.

| Limit | Rule |
|---|---|
| Hourly limit | At most `round(3 × (0.5 + frequency))` spoken nudges (`CHECK_IN`, `PLAN_REMINDER`) per sliding hour, and never fewer than 1. At the default frequency of 0.5 that's 3. A rung blocked by the limit waits; it isn't skipped. |
| Snooze | `SNOOZED` silences drift cues, the halfway prompt and break suggestions for `snooze` (10 min). Resume, break-end and session start/end prompts still come through, since they answer something the learner did. |
| Quiet hours | Inside any `QuietHours` window (which may wrap past midnight), `decide` returns only silent `AMBIENT_CUE`s. Explicit calls (`start_session`, `reflection_prompt`) aren't affected. |
| Strict mode | Halves the spacing. That's all it does. |
| `interaction_frequency` | A 0..1 float or a callable, read on every decision, so the memory system's adaptive value can change mid-session. |

## Learning from responses

- `FALSE_ALARM` stops the current episode (no further rungs, no resume
  read-back) and doubles that app's backoff, up to ×8. The backoff applies to
  later rungs and also delays the first ambient cue for that app. Other apps
  aren't affected. F4 also passes the correction to the classifier.
- `IGNORED` on a spoken nudge doubles the spacing for each consecutive ignore
  (×2, ×4, up to ×8). Any other response resets it.
- `DISMISSED` on a spoken nudge stops escalation for this episode.
- On `RETURNED`, the learner gets a `RESUME` if there's a resume note, and
  nothing otherwise: no lecture, no guilt.

False-alarm counts, the ignored streak, the hourly window, snooze and seen
variants belong to the learner and persist across sessions in one policy
instance. Everything else resets for each plan.

## Wording

- Templates offer choices: "want to…?", "we can…". `BANNED_PHRASES` covers
  orders ("stop", "you must", "you should", "don't"…), guilt ("wasting",
  "distracted again?") and productivity claims. Matching is case-insensitive
  and word-bounded, and handles curly apostrophes. Tests scan every template,
  choice and notice.
- Each kind has at least two variants, rotated in order. The first time a new
  `CHECK_IN` or `PLAN_REMINDER` variant appears, it's prefixed with "trying a
  new style of check-in." (HabitLab). The first variant shown is never
  announced. `seen_variants` can be persisted so this stays one-time across
  restarts.
- Messages use the learner's own goal and if-then words. **Window titles
  never appear in a message**, so rephrasing never sends a title to the model.
- `await policy.rephrase(intervention)` asks the injected `ModelCall` for a
  fresh wording. The output is accepted only if it's at most 180 characters
  and 30 words, has no markup or URLs, contains no banned phrase, and is
  still a question when the template was one. Any failure, timeout (4 s) or
  missing model returns the original intervention unchanged. The id, choices
  and rationale are always kept.

Drift-related interventions (`AMBIENT_CUE`, `CHECK_IN`, `PLAN_REMINDER`,
`RESUME`) always include the "not a distraction" choice. Break, metacognitive
and reflection prompts don't, because they aren't about a detected
distraction. All interventions carry a rationale letter.

## Resume notes (section D)

- `set_context(where=..., next_action=..., source=...)`: F4 passes the latest
  walkthrough step or plan position.
- On `DRIFT_STARTED`, and when a break starts, a note is captured: the latest
  context if it's newer than the current note, otherwise the current note is
  kept. If there's neither, the plan goal is used (`source="plan"`). A note
  the learner spoke (`set_resume_note`) that's newer than the context wins.
  Only one note is kept.
- `RESUME` reads: "you were on {where}, about to {next}." With only the plan:
  "you were working on {goal}."

## Breaks (section E)

- **Fixed** (default): `BREAK_DUE` → `BREAK_START` ("time for a five-minute
  break, want to stretch?") with choices "start break" / "keep going".
- **Self-paced**: suggested on `BREAK_DUE` or at a `BREAKPOINT`, only after
  `self_paced_stretch` (50 min) without a break.
- **None**: no break prompts.
- `ACCEPTED` → `begin_break()`. `DISMISSED` ("keep going") → no new
  suggestion for 15 min. During a break, drift signals are ignored.
- `BREAK_OVER` → `BREAK_END` with the resume note, but only if a break is
  actually in progress.
- The wording talks about energy and stretching, never productivity.

## Metacognitive prompts and reflection (sections F, G)

- `start_session(plan)` → planning prompt ("what's the first thing you'll
  do?").
- At the first `BREAKPOINT` after half the duration → monitoring prompt
  ("how's it going against the plan?"). Fires once.
- `SESSION_ENDING` → evaluation prompt. Fires once.
- `reflection_prompt(plan)` → `REFLECTION` ("what got in the way today, if
  anything?").
- None of these fire during a drift or a break.

## SessionTally (section F)

Feed it every signal (`observe`), every shown intervention
(`record_intervention`), every response (`record_response`), and
`start_break()` when a break starts some other way. `summary(reflection=...)`
returns a `SessionSummary`.

- Off-goal time starts when the drift began (`signal.at - drift_seconds`),
  clamped so it never reaches back before the last state change.
- A `FALSE_ALARM`, during or right after a drift, moves that drift's time
  back to on-goal and removes it from `drift_count`. The timeline matches
  what the learner says, and `false_alarms` still counts the correction.
- On-goal + off-goal + break always adds up to the session length.
