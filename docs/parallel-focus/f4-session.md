# F4: session experience, runtime and integration

You own `curio/focus_session/`, the focus contract, and the final wiring.
Read `docs/parallel-focus/README.md`, all of
`docs/focus-learning-research.md`, `curio-py/curio/focus_contract.py`,
and for the existing patterns: `coaching_runtime.py`, `ui/coaching_window.py`,
`ui/memory_window.py`, `design_system.py`, `ui/pet_widget.py`, `pets.py` and
`docs/coaching-integration.md`.

Until F1–F3 merge into your branch, build against fakes of their protocols.

## 1. Session start (section A)

- Starting a session by voice ("Curio, I'm doing my Excel assignment for 25
  minutes") or from the tray opens a small panel: goal, duration, break style
  (fixed by default), strict mode (off by default), allowed apps (prefilled
  with the current foreground app).
- **If-then helper:** suggests one or two implementation intentions from the
  goal and the learner's past distractions (from saved summaries), which the
  learner edits or accepts. Each becomes an `IfThenPlan` with `cue_apps`.
- Produces a `FocusPlan`.

## 2. `FocusRuntime`

Coordinator in the style of `coaching_runtime.py`:
- Wires `ActivitySource` → `TrackClassifier` → `DriftTracker` →
  `FocusPolicy`, and delivers each `Intervention` to a presenter.
- Routes responses back: `FALSE_ALARM` → `classifier.correct(...)` and the
  policy; others → `policy.record_response`.
- Passes resume context (current walkthrough step or plan) to the policy.
- Builds the `ModelCall` from the configured backend with a separate client,
  as coaching does, so focus prompts never leak into the voice stream.
- Clean start/stop/cancel and awaitable shutdown, as in coaching integration.

## 3. Presenter and pet behaviour (section H, presentation only)

- `AMBIENT_CUE`: pet animation only (looks at the learner, walks to the
  taskbar). No sound.
- Spoken kinds: the existing TTS plus a small choice bubble near the pet
  with the intervention's `choices`; clicking or saying a choice records the
  response. Expired → `IGNORED`.
- Breaks: the pet naps or stretches; on `RETURNED`, a small happy reaction.
  No guilt animations, no streak losses.
- Every intervention bubble has a "why?" link showing the rationale section's
  one-line summary from the research doc.

## 4. Session timeline and summary (section F)

- A compact live timeline (on goal / drifting / break) in a small window.
- End of session: summary card (time on goal, drifts, false alarms), the
  learner's optional one-line reflection, the review quiz (`REVIEW`
  intervention with F3's items, answers shown after each response) and "next
  review on <day>". Saved via a `SqliteSessionStore` (implements
  `SessionStore`). History view with delete-all.

## 5. Final wiring step (only after `main` contains the learning work)

Merge `main` into your branch first; see the README for why. Then:
- `app.py`: construct F1–F4 from their handoff notes; tray "Start focus
  session…", "Session history".
- `companion_manager.py`: while a study session is active, feed
  `LearnerEvent`s (help requests from how-to and "I'm stuck" questions,
  walkthrough step outcomes from the learning event log) to F3's coach, and
  add its `TutorDirective.instruction` to that request only, like
  `walkthrough_reminder`. Pass the skill model's mastery when available.
  Don't let directives conflict with the existing walkthrough/STEP flow.
- `config.py` / `config.example.toml`: a `[focus]` section (defaults from the
  research doc: 25/5 fixed breaks, 3 check-ins/hour, model judgments on but
  switchable off, strict off).
- Docs: ARCHITECTURE, RUNNING (including a privacy note on what's sampled),
  PROGRESS.

## Done when

Tests: runtime routing with fakes (drift → intervention → response →
classifier correction), presenter expiry → `IGNORED`, session store round
trip, if-then suggestion parsing, offscreen widget smoke tests, and, after
wiring, the full suite passes. Write `docs/focus-session.md` and update the
docs listed above.
