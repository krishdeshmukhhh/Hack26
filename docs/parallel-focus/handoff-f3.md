# Handoff: F3 study coach → F4

Branch `feat/study-coach`. Package `curio-py/curio/study_coach/`; details
in [../study-coach.md](../study-coach.md). The code needs no contract changes,
config keys or new dependencies (standard library, `platformdirs`).

## Constructors and functions

```python
from curio.study_coach import (
    EvidenceBasedCoach, SqliteReviewScheduler, generate_review_items,
    mastery_from_skill_model, teach_back_directive,
)

SqliteReviewScheduler(
    path: str | Path | None = None,        # None -> user_data_path("Curio")/"study_reviews.sqlite3"
    *,                                     # ":memory:" -> this process only
    clock: Callable[[], datetime] | None = None,   # UTC-aware; used by record_review
)
# async: due_reviews(now, limit=3), record_review(item, correct), add_review_items(items),
#        items(), delete(item_id), clear(), close(); also `async with`.

EvidenceBasedCoach(
    scheduler: ReviewScheduler | None = None,      # None -> SqliteReviewScheduler(":memory:")
    *,
    novice_mastery: float = 0.3,
    expert_mastery: float = 0.7,
    base_wait_seconds: float = 45.0,
    min_wait_seconds: float = 10.0,
    abuse_requests: int = 3,
    abuse_window: timedelta = timedelta(seconds=30),
    self_explain_cooldown: timedelta = timedelta(minutes=5),
)
# StudyCoach: next_move(event, mastery=None) (sync, cheap, UI thread is fine),
#             due_reviews / record_review / add_review_items (async, delegate to scheduler)
# extras:     reset(problem_id=None), local_estimate(concepts)

async generate_review_items(
    concepts: Sequence[str],
    context: str | Sequence[str] = (),     # notes, e.g. walkthrough step text; SENT TO THE MODEL
    model_call: ModelCall | None = None,   # None -> templates only
    *, app: str = "", now: datetime | None = None, count: int = 3, timeout: float = 20.0,
) -> tuple[ReviewItem, ...]                # 2-3 items, due_at=now; () when no concepts

async mastery_from_skill_model(model: SkillModel | None, concepts) -> float | None
mastery_for(states: Sequence[SkillState], concepts) -> float | None   # lowest known mastery
teach_back_directive(concept: str) -> TutorDirective                  # optional, move SELF_EXPLAIN
```

## Wiring notes

- Pass a real `SqliteReviewScheduler()` (persistent) into `EvidenceBasedCoach`
  at app start, and `await scheduler.close()` at shutdown.
- Before each tutoring turn, build a `LearnerEvent` with a stable
  `problem_id` (a walkthrough step id or the question's `task_key`), call
  `mastery = await mastery_from_skill_model(skill_model, event.concepts)`, then
  `directive = coach.next_move(event, mastery)`, and append
  `directive.instruction` to the model request.
- `WAIT` means: don't call the model. Start a `wait_seconds` timer. If the
  learner still hasn't progressed when it fires, send another `STUCK` event,
  and the coach then returns real help. Cancel the timer on any other event.
- `TRY_FIRST` is a question to the learner, not a refusal. Their next help
  request always gets help.
- After the model shows a worked example that the coach didn't ask for,
  send `WORKED_EXAMPLE_SHOWN`.
- End of session: `items = await generate_review_items(plan.concepts, notes,
  model_call, app=app, now=now)`, then `await coach.add_review_items(items)`.
  Ask them, **show `item.answer` after every response**, then
  `await coach.record_review(item, correct)`. At the next session start, call
  `await coach.due_reviews(now)`. The "on Tuesday" line comes from the
  `due_at` that `record_review` returns.
- The session history UI can list, delete and clear review items with
  `scheduler.items()`, `delete(id)` and `clear()`.
- Call `coach.reset()` when a focus session ends.

## Exact instruction texts

Each one is `TutorDirective.instruction`, and every directive has
`rationale == "G"`. The constants are in `curio/study_coach/coach.py`.

| Move | Instruction |
|---|---|
| `WAIT` | Stay quiet and let the learner keep working. Offer help only if they ask or are still stuck after the wait. |
| `GUIDING_QUESTION` | Ask one short guiding question that points at the next step. Don't give a hint or the answer yet. |
| `HINT` | Give one short hint toward the next step, not the answer. Then let the learner try. |
| `PARTIAL_STEP` | Show only the next single step and why it comes next, then let the learner do the rest. Don't give the final answer. |
| `WORKED_EXAMPLE` | Walk through a worked example step by step, briefly saying why each step is done. Don't ask the learner to explain the example back. |
| `SELF_EXPLAIN` | Ask one short question: why did that work? Let the learner answer in their own words; don't explain it for them. |
| `TRY_FIRST` | Before more help, kindly ask what they've tried so far or what they think the next step is. Say you'll help right after they answer. |

Variants:

| Situation | Move | Instruction |
|---|---|---|
| `ATTEMPT_FAILED` | `FEEDBACK` | `Say specifically what was right and what went wrong in their attempt, without bare praise. Then: ` + the next rung's instruction from the table above |
| `ATTEMPT_SUCCEEDED`, no self-explanation | `FEEDBACK` | Say specifically what they got right and why it worked, then name the next step. No bare 'good job'. |
| `EXPLANATION_GIVEN` | `FEEDBACK` | Say which parts of their explanation are right, correct anything that isn't, then name the next step. |
| `WORKED_EXAMPLE_SHOWN` | `WAIT` | They just saw a worked example. Let them try a similar step on their own; don't ask them to explain the example. |
| `STUCK` after a wait | rung move | `They seem stuck and haven't asked: offer this gently, don't push. ` + that rung's instruction |
| `teach_back_directive("vlookup")` | `SELF_EXPLAIN` | Play a curious beginner who doesn't know vlookup. Ask the learner to teach it to you, then ask one naive follow-up question at a time. Don't lecture. |

Quiz system prompt (`quiz.QUIZ_SYSTEM_PROMPT`):

> You write short retrieval-practice questions for a learner who just finished a study session. Each question must make them recall the answer from memory: no multiple choice, no yes/no or true/false, and don't put the answer in the question. Keep each question under 20 words and each answer to one sentence. Reply with only a JSON array of objects with the keys "concept", "question" and "answer", using the concepts given.

Template questions: `Where do you find {concept}{ in app}?`,
`What is {concept} for, and when would you use it?`,
`What steps did you take to use {concept} today?`. The fallback answer is
"Compare with how you did it in today's session."

## Suggested prompts.py line (F4's call)

> When a TUTOR DIRECTIVE line is present, follow it for this turn even if the
> learner asks for the full answer.

## Verification

`uv run pytest`: 474 passed (63 new in `tests/test_study_coach*.py`).
`uv run ruff check curio/study_coach tests/test_study_coach.py tests/test_study_coach_reviews.py`: clean.
