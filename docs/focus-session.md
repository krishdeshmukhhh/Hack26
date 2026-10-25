# Focus session (F4)

The session experience for focus/learning mode: start with an if-then plan,
run sensing → policy → presenter, show a live timeline, and finish with a
summary, a reflection and a short review quiz. Behaviour and evidence come
from [focus-learning-research.md](focus-learning-research.md). The section
letters below match that doc.

Status: sections 1–4 of [f4-session.md](parallel-focus/f4-session.md) are
built and tested against fakes of the F1–F3 protocols. Final wiring
(section 5: `app.py`, `companion_manager.py`, config, tray) hasn't been done yet.

## Package: `curio/focus_session/`

| Module | What it does | Qt? |
|---|---|---|
| `planning.py` | Parses the spoken start request, suggests if-then plans (model, then templates), parses edited "if …, then …" lines, builds a `FocusPlan` (A) | no |
| `rationale.py` | One-line "why?" text per research section | no |
| `timeline.py` | `SessionTimeline`: on-goal / drifting / break segments (F) | no |
| `store.py` | `SqliteSessionStore`, which implements `SessionStore` | no |
| `runtime.py` | `FocusRuntime` coordinator, `Presenter` protocol, `build_model_call` | QObject |
| `presenter.py` | `FocusPresenter`, `ChoiceBubble`, `PetActions`, `PetWidgetActions` (C, H) | widgets |
| `start_panel.py` | `FocusStartPanel` (A) | widget |
| `session_window.py` | `FocusSessionWindow`, `TimelineBar` (F) | widget |
| `summary_window.py` | `SessionSummaryWindow`: totals, reflection, review quiz, next review day (F, G) | widget |
| `history_window.py` | `FocusHistoryWindow` with delete-all | widget |

`curio.focus_session` itself exports only the non-widget parts. Import the
widgets from their modules.

## Contract change

`SessionSummary` gains `distractions: tuple[str, ...] = ()`. These are the
`app_key()`s of this session's drift episodes. Saved summaries feed the
if-then helper ("if I open youtube, then…"). The field has a default, so F2's
`SessionTally` and any other producer still construct summaries unchanged.

## Session start (A)

- `parse_start_request("Curio, I'm doing my Excel assignment for 25
  minutes")` returns `StartRequest(goal, minutes)`, or `None` for other
  speech. It accepts "an hour", "half an hour", "45 mins" and "2 hours".
  Without a time it uses 25 minutes.
- `FocusStartPanel.prefill(goal, minutes)` resets the form. It sets
  fixed breaks and strict mode off, fills allowed apps from the foreground
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
    policy: FocusPolicy, presenter: Presenter,
    coach: StudyCoach | None = None, store: SessionStore | None = None,
    generate_reviews: Callable[[Sequence[str], str], Awaitable[Sequence[ReviewItem]]] | None = None,
    model_call: ModelCall | None = None,
    resume_context: Callable[[], ResumeNote | None] | None = None,
    clock: Callable[[], datetime] = utc_now, parent=None,
)
```

- `start(plan)` resets the tracker, subscribes to the source and starts it.
  Samples queue onto one asyncio task and are processed in order. A sample
  arriving from another thread is marshalled with `call_soon_threadsafe`.
- Per sample, the runtime calls `classifier.assess`, then `tracker.update`.
  It updates the timeline, then for each signal calls `presenter.signal` and
  `policy.decide`. A returned intervention goes to `presenter.show`.
- **Responses:** the presenter calls `runtime.respond(intervention,
  response)` once per card. Every response goes to `policy.record_response`.
  `FALSE_ALARM` also calls `classifier.correct(sample, ON_GOAL)` with the
  sample that triggered the card, relabels that drift as on-goal time, and
  removes it from the drift count. Duplicate or late answers are ignored.
  `AMBIENT_CUE` expects no answer.
- **Resume context (D):** on `DRIFT_STARTED` the runtime asks
  `resume_context()` for the current walkthrough step, falling back to the
  session plan. It passes a new note to `policy.set_resume_note`. Wiring can
  also push one directly with `set_resume_context(note)`.
- **Breaks:** an accepted `BREAK_START` card, or an `ON_BREAK` judgment,
  counts as break time until `BREAK_OVER` or `BREAK_END`.
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
`intervention_shown(intervention)`, `session_ended(summary)`, `error(str)`.

## Presenter and pet (C, H)

`FocusPresenter(speak=None, pet=None, anchor=None, schedule=qt_schedule)`:

- `AMBIENT_CUE` runs the pet's `look_at_learner()` and nothing else: no sound
  and no card.
- Spoken kinds call `speak(message)` (the existing TTS) and show a
  `ChoiceBubble` near `anchor()` with the card's choices, or "okay" when it
  has none. A "why?" link shows the section's line from `rationale.py`.
- A click, or `handle_spoken(text)` from push-to-talk, maps the choice to a
  response. "not a distraction" maps to `FALSE_ALARM`. "snooze", "later" and
  "not now" map to `SNOOZED`. "keep going" and "no thanks" map to
  `DISMISSED`. Anything else maps to `ACCEPTED`. When the card's
  `expires_after` passes, it records `IGNORED`. A new card replacing an
  unanswered one also records `IGNORED` for the old card.
- Pet reactions: an accepted break starts `nap()`, `BREAK_OVER`/`BREAK_END`
  trigger `stretch()`, and `RETURNED` triggers `happy()`. There are no guilt
  animations and no streaks.
- `PetWidgetActions(pet_widget)` plays existing clips: attentive, settle and
  sleep, wake, and jump. `BehaviorController` has no public "play clip"
  method, so it calls `_start_optional` if it exists. With the triangle
  fallback it does nothing. **Wiring should add a public method** to
  `BehaviorController`. "Walk to the taskbar" isn't implemented, because the
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
  history…" behind a confirmation.

## Storage and privacy

`SqliteSessionStore(path=None)` defaults to
`user_data_path("Curio")/focus_sessions.sqlite3`. It uses one worker
thread with `secure_delete` on and a versioned schema. It refuses to open
unknown databases. It stores summaries only: goal, totals, concepts,
reflection and distraction app keys. **No window titles and no activity
samples** are stored. Delete-all empties the table and runs VACUUM.

## Wiring notes for section 5

- Construct one LLM client for focus (`_configured_llm(config)`) and pass
  `build_model_call(client, config.model)` to F1's classifier, F2's policy,
  the runtime (if-then suggestions) and F3's quiz generator. Pass `None` when
  `[focus] model_judgments = false`.
- `presenter = FocusPresenter(speak=<tts speak>, pet=PetWidgetActions(pet),
  anchor=lambda: pet.geometry().topLeft())`.
- Route push-to-talk through `presenter.handle_spoken(text)` before the
  normal pipeline while a card is open. Route "I'm doing X for N minutes" through
  `parse_start_request`, then `start_panel.prefill(...)`.
- `resume_context`: the current walkthrough step as `ResumeNote(where="step
  N", next_action=<instruction>, source="walkthrough")`.
- Tray: "Start focus session…" opens `start_panel.prefill()`, and
  `plan_ready` connects to `runtime.start`. "Session history" opens
  `FocusHistoryWindow(store)`.
- Shutdown: `await runtime.aclose()`, dispose the windows, then `await
  store.close()`.

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

Run with `uv run pytest tests/test_focus_session*.py`.

Not verified: real TTS, a real pet on a desktop, real F1–F3 implementations
and real model replies. The rendered widgets were inspected offscreen only.
