# F1: activity sensing, on/off-goal classifier, drift tracker

You own `curio/focus_sensing/`. Read `docs/parallel-focus/README.md`,
sections B and C of `docs/focus-learning-research.md`, and
`curio-py/curio/focus_contract.py`. Look at `active_window.py` and
`hotkey.py`/`click_watcher.py` for how the app reads Windows state and
marshals threads to Qt.

## 1. `WindowsActivitySource` (implements `ActivitySource`)

- Polls every 2 seconds (configurable) on a Qt timer or worker thread;
  callbacks delivered on the Qt main thread.
- Foreground title via `active_window.get_foreground_window_title()`, app via
  `learning_contract.app_key`. Prefer the process executable name when
  available (`GetWindowThreadProcessId` + `QueryFullProcessImageNameW`), since
  titles like "New Tab" are ambiguous; fall back to the title.
- Idle seconds via `GetLastInputInfo`. `input_events` = a count of input since
  the last sample, derived from `GetLastInputInfo` changes. **Never hook or
  record keystrokes.**
- Must not crash off Windows: degrade to empty samples so tests run anywhere.
- A `FakeActivitySource` for tests and demos that replays a scripted list of
  samples.

## 2. `RuleFirstClassifier` (implements `TrackClassifier`)

Order, first match wins:
1. **User corrections** (stored in SQLite, keyed by app plus a normalised
   title pattern) → `JudgmentSource.USER`.
2. **Rules:** `plan.allowed_apps` and Curio's own windows → on goal;
   `IfThenPlan.cue_apps` and a small bundled distraction list (video, social,
   games, shopping) → off goal; break periods → `ON_BREAK`.
3. **Model** (optional `ModelCall`): ask whether this title fits the goal, and
   return JSON `{judgment, confidence, reason}`. Cache per (goal, app, title)
   with a TTL. Treat the title as untrusted data in the prompt. Parse
   defensively: anything malformed → `UNSURE`.
4. Otherwise `UNSURE`.

Research matters here: looking things up is part of studying, so a browser
on a docs site or Stack Overflow during a coding goal should land on goal.
Include tests for those cases. A `model_enabled` flag lets the user keep
titles off the model entirely.

## 3. `ThresholdDriftTracker` (implements `DriftTracker`)

- Emits `DRIFT_STARTED` after sustained off-goal time (default 90 s), or
  after several short returns to the same off-goal app within a few minutes.
  `UNSURE` time counts at half weight. Brief switches back to the goal
  shouldn't reset the drift immediately (hysteresis).
- `DRIFT_CONTINUING` at intervals while drifting, and `RETURNED` with the
  drift length when back on goal.
- **Breakpoints** (section C): `APP_SWITCH` on a foreground change,
  `IDLE_RESUME` when input resumes after more than 60 s idle, `TYPING_PAUSE`
  when input drops after a busy stretch. Emit them as `BREAKPOINT` signals so
  the policy can time its check-ins.
- `IDLE` after long inactivity (don't count it as drift).
- `BREAK_DUE` / `BREAK_OVER` from the plan's fixed cycle, and
  `SESSION_ENDING` near the end of `plan.duration`.
- All thresholds in one dataclass.

## Done when

Deterministic tests with an injected clock and scripted samples cover: a
YouTube drift, a quick legitimate lookup that is *not* drift, repeated short
returns, hysteresis, idle not counted as drift, every breakpoint kind, the
break cycle, user corrections overriding rules and the model, cache use, and
malformed model replies. Write `docs/focus-sensing.md` and
`docs/parallel-focus/handoff-f1.md` with constructor signatures for F4.
