# Focus session (F4)

The session experience for focus/learning mode: start with an if-then plan,
run sensing → policy → presenter, show a live timeline, and finish with a
summary, a reflection and a short review quiz. Behaviour and evidence come
from [focus-learning-research.md](focus-learning-research.md). The section
letters below match that doc.

Status: implemented and wired into `app.py`, `companion_manager.py`, config
and the tray. `wiring.py` builds the real sensing, policy, study coach and UI;
`integration.py` connects voice requests and walkthrough progress. The original
[F4 handoff](parallel-focus/f4-session.md) describes the development split.

## Package: `curio/focus_session/`

| Module | What it does | Qt? |
|---|---|---|
| `planning.py` | Parses the spoken start request, suggests if-then plans (model, then templates), parses edited "if …, then …" lines, builds a `FocusPlan` (A) | no |
| `rationale.py` | One-line "why?" text per research section | no |
| `timeline.py` | `SessionTimeline`: on-goal / drifting / break segments (F) | no |
| `store.py` | `SqliteSessionStore`, which implements `SessionStore` | no |
| `runtime.py` | `FocusRuntime` coordinator, `Presenter` protocol, `build_model_call` | QObject |
| `wiring.py` | `build_focus_mode`, `FocusMode`: constructs services/windows, applies config and closes stores | widgets |
| `integration.py` | `FocusIntegration`: transcript routing, per-turn tutor directives, walkthrough context and concepts | no |
| `presenter.py` | `FocusPresenter`, `ChoiceBubble`, `PetActions`, `PetWidgetActions` (C, H) | widgets |
| `start_panel.py` | `FocusStartPanel` (A) | widget |
| `session_window.py` | `FocusSessionWindow`, `TimelineBar` (F) | widget |
| `summary_window.py` | `SessionSummaryWindow`: totals, reflection, review quiz, next review day (F, G) | widget |
| `history_window.py` | `FocusHistoryWindow` with delete-all | widget |

`curio.focus_session` itself exports only the non-widget parts. Import the
widgets from their modules.

## Summary contract

`SessionSummary` includes `distractions: tuple[str, ...] = ()`. These are the
`app_key()`s of this session's drift episodes. Saved summaries feed the
if-then helper ("if I open youtube, then…"). The field has a default, so F2's
`SessionTally` and any other producer still construct summaries unchanged.

## Session start (A)

- `parse_start_request("Curio, I'm doing my Excel assignment for 25
  minutes")` returns `StartRequest(goal, minutes)`, or `None` for other
  speech. It accepts "an hour", "half an hour", "45 mins" and "2 hours".
  Without a time it uses 25 minutes.
- `FocusStartPanel.prefill(goal, minutes)` resets the form. It sets
  break style and strict mode from `[focus]`, fills allowed apps from the foreground
  app, and asks for suggestions.
- `FocusRuntime.suggest_if_then(goal)` loads saved summaries and calls
  `planning.suggest_if_then(goal, past_distractions(...), model_call)`. The
  model gets the goal and past distractions as untrusted JSON and must reply
  with a JSON list. Replies are parsed defensively: at most two plans, fields
  capped at 120 characters, controlling phrases rejected. On any failure the
  panel falls back to templates: one plan per past distraction, or a generic
  "if I feel the urge to check something else, then say 'back to it'…".
- The learner can edit each line and its watched apps, or untick it. Each
  ticked line becomes an `IfThenPlan`. Cue apps are guessed from "open X" or
  "check X" when left blank.

## `FocusRuntime` (section 2)

```python
FocusRuntime(
    *, source: ActivitySource, classifier: TrackClassifier, tracker: DriftTracker,
    policy: SessionPolicy, presenter: Presenter,
    coach: StudyCoach | None = None, store: SessionStore | None = None,
    generate_reviews: Callable[[Sequence[str], str], Awaitable[Sequence[ReviewItem]]] | None = None,
    model_call: ModelCall | None = None,
    clock: Callable[[], datetime] = utc_now, parent=None,
)
```

- `start(plan)` resets the tracker, subscribes to the source and starts it.
  It also calls `policy.start_session(plan)` and presents the opening
  metacognitive question. Due reviews are offered once pending cards are answered.
  Samples queue onto one asyncio task and are processed in order. A sample
  arriving from another thread is marshalled with `call_soon_threadsafe`.
- Per sample, the runtime calls `classifier.assess`, then `tracker.update`.
  It updates the timeline, then for each signal calls `presenter.signal` and
  `policy.decide`. A returned intervention goes to `presenter.show`.
- **Responses:** the presenter calls `runtime.respond(intervention,
  response, reply="")` once per card. Policy-card responses go to
  `policy.record_response`; runtime-owned review offers are handled separately.
  `FALSE_ALARM` also calls `classifier.correct(sample, ON_GOAL)` with the
  sample that triggered the card, relabels that drift as on-goal time, and
  removes it from the drift count. Duplicate or late answers are ignored.
  `AMBIENT_CUE` expects no answer.
- **Resume context (D):** `FocusIntegration.walkthrough_step` pushes the latest
  step through `runtime.set_context(where=..., next_action=..., source=...)`
  to the policy. The policy snapshots it when drift starts, falling back to
  the session goal. A spoken answer to the opening question also supplies a
  resume note through `policy.set_resume_note`.
- **Breaks:** an accepted `BREAK_START` card, or an `ON_BREAK` judgment,
  counts as break time until `BREAK_OVER` or `BREAK_END`.
  `take_break()` supports a learner-requested break, ending after the plan's
  break length. Check-in choices can also start a break.
- `note_concepts(concepts, context)` records what was practised. This feeds
  `concepts_practised` and quiz generation.
- `end()` stops sensing and drains queued samples. Open cards are recorded as
  `IGNORED`. It saves the summary and emits `session_ended`. A session also
  ends by itself once a sample arrives past `started_at + duration`.
  `cancel()` discards a session without saving it. `finish()` releases the
  ended session once the summary window closes. `aclose()` awaits every task
  the runtime started.
- `build_model_call(provider, model)` wraps a **dedicated** LLM client, as
  coaching does, so focus prompts never reach the voice stream.
- Errors in the classifier, store or coach are logged and never stop the
  pipeline. The UI gets a generic message through `error`.

Signals: `session_started(plan)`, `timeline_changed()`,
`intervention_shown(intervention)`, `session_ended(summary)`,
`review_requested(items)`, `error(str)`.

## Presenter and pet (C, H)

`FocusPresenter(speak=None, pet=None, anchor=None, schedule=qt_schedule)`:

- `AMBIENT_CUE` runs the pet's `look_at_learner()` and nothing else: no sound
  and no card.
- Spoken kinds call `speak(message)` (the existing TTS) and show a
  `ChoiceBubble` near `anchor()` with the card's choices, or "okay" when it
  has none. A "why?" link shows the section's line from `rationale.py`.
- A click, or `handle_spoken(text)` from the voice pipeline, maps the choice to a
  response. "not a distraction" maps to `FALSE_ALARM`. "snooze", "later" and
  "not now" map to `SNOOZED`. "keep going" and "no thanks" map to
  `DISMISSED`. Other matched choices map to `ACCEPTED`; unmatched speech
  remains available to the assistant. Free-text prompt answers are passed
  through as `reply`. When the card's
  `expires_after` passes, it records `IGNORED`. A new card replacing an
  unanswered one also records `IGNORED` for the old card.
- Pet reactions: an accepted break starts `nap()`, `BREAK_OVER`/`BREAK_END`
  trigger `stretch()`, and `RETURNED` triggers `happy()`. There are no guilt
  animations and no streaks.
- `PetWidgetActions(pet_widget)` uses the public `play_clip` method for attentive,
  settle, sleep, wake and jump. A timer repeats sleep during a nap and stops
  on wake. Triangle fallback and reduced motion play nothing.
  "Walk to the taskbar" isn't implemented, because the
  only way to move the pet today is `fly_to`, which also shows the pointer pill.

## Timeline, summary, history (F, G)

- Drift time is only what the tracker called sustained drift. When
  `DRIFT_STARTED` arrives with `drift_seconds`, that much time is relabelled
  as drifting, so a quick lookup stays on goal.
- `FocusSessionWindow` shows the goal, the time left, a coloured bar across
  the planned duration and per-state minutes, plus an End button.
- `SessionSummaryWindow` opens on `session_ended`. It shows time on goal,
  time drifting and the number of drifts, break time, and false alarms. It
  has a one-line reflection field ("What got in the way today?", at most 280
  characters).

  The review quiz loads new items for today's concepts through
  `generate_reviews` (F3's `generate_review_items`, bound to the model call)
  and adds them to the coach. Due items fill up to three questions. For each
  question the learner attempts an answer, then sees the correct one, then
  marks "I got it" or "Not quite", which calls `coach.record_review`. The
  answer is always shown after the attempt.

  The window ends with "I'll ask you about <concept> again tomorrow / on
  Tuesday", taken from the soonest updated `due_at`. "Done" saves the
  summary again with the reflection; saving the same `plan_id` replaces it.
- `FocusHistoryWindow` lists saved summaries newest first, with "Delete all
  history…" behind a confirmation. The wired window also clears classifier
  corrections and scheduled review questions.

## Storage and privacy

`SqliteSessionStore(path=None)` defaults to
`user_data_path("Curio")/focus_sessions.sqlite3`. It uses one worker
thread with `secure_delete` on and a versioned schema. It refuses to open
unknown databases. It stores summaries only: goal, totals, concepts,
reflection and distraction app keys. **The summary database stores no window
titles or activity samples.** Delete-all empties the table and runs VACUUM.

During an active session, `WindowsActivitySource` samples the foreground app,
window title, idle seconds, input-activity count, switch flag and timestamp
(every two seconds by default). App identity comes from the process executable;
browser title changes count as switches. Input activity counts polling ticks
with new input, not keystrokes or their contents. Focus sensing captures no
screenshots, page bodies or microphone audio.

For unresolved classifications, `model_judgments = true` permits sending the
goal, app and up to 300 title characters to the configured model backend.
Turning it off disables that classifier request; it does not disable model calls
for if-then suggestions, card wording or quiz generation. Ordinary voice help
still follows the existing screenshot pipeline.

The separate local `focus_corrections.sqlite3` stores app keys, normalized title
patterns and judgments for false-alarm corrections; these patterns can retain
sensitive title words. `study_reviews.sqlite3` stores review items and scheduling
state. All three databases use the Curio user-data directory. Delete-all in
Focus history clears all three stores, but does not reset ordinary memory or
the policy wording variants saved in QSettings.

## Application wiring

- When `[focus] enabled = true` (the default), `app._build_focus` creates a
  dedicated `_configured_llm(config)` client using `config.default_model`.
  `build_focus_mode` shares its text-only adapter across the classifier, policy,
  if-then helper and quiz generator. `model_judgments` gates only the classifier.
- `manager.attach_focus(mode.integration)` routes ordinary-mode transcripts
  through `handle_transcript` before an assistant turn. It handles start/end,
  breaks and matching card replies; help requests remain assistant turns.
  Explicit tutorial/integral coaching modes keep their own transcript routing.
- While studying, learner-initiated help gets a request-only tutor directive
  using available task-map concepts and estimated mastery. Hints/questions omit
  STEP/POINT actions; partial steps/worked examples can use walkthrough tags.
  Automatic walkthrough continuations receive no tutor directive. Step progress
  feeds resume context, concepts and coach events; GUI progress is not independent
  proof of correctness or mastery.
- The presenter speaks through `manager.say` when the voice pipeline is idle,
  and anchors cards near the visible pet. The tray swaps **Start focus session…**
  for **End focus session**, and exposes **Focus history…**. The start panel's
  `plan_ready` signal calls `runtime.start`.
- At session start, an enabled memory runtime can supply the adaptive
  interaction-frequency preference. Seen policy wording variants are restored
  from QSettings and saved at shutdown.
- Shutdown detaches the manager hook and awaits `FocusMode.aclose()`, which
  stops the runtime, disposes windows/presenter and closes all three stores.

## Tests

`tests/test_focus_session_*.py` (fakes live in
`test_focus_session_fakes.py`):

- runtime routing: drift → check-in → false alarm → classifier correction
  and policy, resume notes, breaks, end/cancel/auto-end, failures, reviews
  and the model call
- presenter: expiry → `IGNORED`, replacement, ambient-only animation, spoken
  choices, pet reactions
- store round trip, upsert and clear
- if-then parsing, including malformed model output
- offscreen smoke tests for every window
- integration: transcript routing, tutor directives, walkthrough context/events
- wiring: config validation, tray actions, real service construction, preferences,
  start/end and shutdown with temporary databases and no model

Run with `uv run pytest tests -k focus_session`.

Automated wiring tests construct the real F1–F3 services; deterministic runtime
tests also use fakes. Real model replies, audible TTS, physical desktop sensing,
pet behavior and packaged startup still need manual verification.
