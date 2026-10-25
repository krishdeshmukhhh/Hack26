# Focus sensing

`curio.focus_sensing` is the sensing half of focus mode: it watches what is in
the foreground, judges it against the session goal, and turns those judgments
into `FocusSignal`s for the policy. Contracts are in
`curio/focus_contract.py`; the evidence behind each rule is in
[focus-learning-research.md](focus-learning-research.md), sections B, C and E.

```
WindowsActivitySource ─► RuleFirstClassifier.assess ─► ThresholdDriftTracker.update ─► FocusSignals
   (every 2 s)              (corrections, rules, model)     (thresholds, breakpoints)
```

## Activity source

`WindowsActivitySource` polls on two Qt timers, so subscribers are called on
the Qt main thread. Each Win32 call takes microseconds, so it needs no worker
thread.

- **App:** the foreground process's executable (`GetWindowThreadProcessId` +
  `QueryFullProcessImageNameW`), passed through `learning_contract.app_key`.
  A few executables are aliased so the key matches the name their titles end
  with (`chrome.exe` → `google chrome`, `WINWORD.EXE` → `word`), which means
  an `allowed_apps` entry taken from a title still matches. Curio's own
  windows are `curio`. If the process can't be read, it falls back to
  `app_key(title)`.
- **Title:** `active_window.get_foreground_window_title()`. Titles stay on the
  device.
- **Idle:** `GetLastInputInfo`.
- **Input count:** a 250 ms timer checks whether `GetLastInputInfo`'s
  timestamp moved, and `input_events` is the number of ticks that saw input
  since the last sample (0–8 at the defaults). That makes it an activity
  level, not a keystroke count. Nothing hooks the keyboard and no key is ever
  read, and a test checks the module for hook and key-state APIs.
- **Switch:** a different window, a different app, or, in a browser, a
  different title (tab change).
- Off Windows, or if any call fails, the probe returns empty values and
  samples are still produced.

`FakeActivitySource` replays a list of samples: `step()`, `play()`, `push()`,
an optional `loop`, and an optional Qt-timer `interval_seconds` for demos.
`scripted_samples([(app, title, seconds[, idle[, input_events]]), ...],
start=...)` builds such a list.

## Classifier

`RuleFirstClassifier.assess` uses the first source that gives an answer:

1. **User corrections** (`SQLiteCorrectionStore`, keyed by app plus
   `title_pattern(title)`: lowercase, unread counters like `(3)` removed, digit
   runs replaced with `#`) → `JudgmentSource.USER`, confidence 1.
2. **Rules** (`JudgmentSource.RULE`), in this order:
   - the plan's fixed break period → `ON_BREAK`
   - Curio's own windows → `ON_GOAL`
   - `IfThenPlan.cue_apps` (an app key or a title phrase) → `OFF_GOAL`. This
     comes before allowed apps, so a "YouTube" cue still wins when Chrome is
     allowed.
   - `plan.allowed_apps` → `ON_GOAL`
   - the bundled distraction list (video, social, games, shopping) →
     `OFF_GOAL`. If the title also names a reference site or a word from the
     goal ("Python list comprehensions - YouTube" during a Python goal), the
     classifier asks the model instead (`UNSURE` without one).
   - reference and lookup sites (Stack Overflow, docs, MDN, Microsoft Support,
     Wikipedia, …) → `ON_GOAL`, because looking things up is part of studying.
3. **Model** (optional `ModelCall`, only when `model_enabled`). The goal and
   title are sent as a JSON string, and the system prompt tells the model to
   treat the title as untrusted. The reply must be
   `{judgment, confidence, reason}`, where judgment is `on_goal`, `off_goal`
   or `unsure` and confidence is a number. Fenced or surrounding text is fine.
   Confidence is clamped and the reason trimmed. Anything else, a timeout or
   an exception gives `UNSURE` with confidence 0 and is not cached. Good
   answers are cached per (goal, app, title pattern) for 30 minutes, and
   identical questions asked while a call is still running share that call.
4. Otherwise `UNSURE`.

`correct(sample, judgment)` stores the correction and drops any cached model
answer for that title. When F2 receives a `FALSE_ALARM` response, F4 should
call it with `ON_GOAL`.

## Drift tracker

`ThresholdDriftTracker.update(sample, assessment)` uses only `sample.at` as
its clock. The time between two samples counts under the earlier sample's
judgment, capped at 10 s so waking from sleep isn't counted. Samples that
arrive out of order are dropped.

| Signal | When |
|---|---|
| `DRIFT_STARTED` | weighted off-goal time ≥ 90 s (`UNSURE` and `OFF_GOAL` below 0.5 confidence count half), or a third visit to the same off-goal app within 3 min |
| `DRIFT_CONTINUING` | every 120 s while drifting and not on goal |
| `RETURNED` | 15 s of continuous on-goal time after a drift; `drift_seconds` runs from the first off-goal sample to the return. Shorter visits back to the goal don't end the episode (hysteresis), and 15 s on goal also clears a partial score |
| `BREAKPOINT` `APP_SWITCH` | `sample.is_switch` |
| `BREAKPOINT` `IDLE_RESUME` | input comes back after more than 60 s idle |
| `BREAKPOINT` `TYPING_PAUSE` | ≥ 20 s of busy samples (≥ 2 input events) followed by a sample with no input and ≥ 4 s idle |
| `IDLE` | idle ≥ 180 s, once per idle stretch. Off-goal time stops counting from 60 s idle |
| `BREAK_DUE` / `BREAK_OVER` | crossings of the plan's fixed study/break cycle. Starting a break also clears any drift |
| `SESSION_ENDING` | once, 120 s before `started_at + duration` |

Within one update, signals come in this order: break and session signals,
idle, drift, then breakpoints. Every threshold lives in `DriftThresholds`.
`totals` gives on-goal, off-goal, unsure, break and idle seconds, the number
of drifts and their total length, for `SessionSummary` and the timeline.

## Known limits

- Watching a video without touching the mouse or keyboard looks like being
  idle, so it stops counting toward drift after 60 s. This is the price of
  "idle is not drift". The `APP_SWITCH` into YouTube still gets assessed, and
  a few minutes of active scrolling still count.
- Tab changes count as switches only in the browsers we recognise (Chrome,
  Edge, Firefox, Brave, Opera, Vivaldi, Arc).
- The distraction and reference lists are short on purpose. Learner
  corrections are how the classifier adapts, and measuring the false-alarm
  rate is part of the pilot (research doc, "How we check it works").
