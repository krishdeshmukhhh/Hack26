# Study coach

`curio.study_coach` picks the next tutoring move during a focus session,
writes end-of-session retrieval questions and schedules spaced review. Every
rule comes from section G of [focus-learning-research.md](focus-learning-research.md),
and every `TutorDirective` carries `rationale="G"`. No Qt. The coach needs no
model; quiz generation uses the injected `ModelCall` when given one and falls
back to templates otherwise.

Nothing is wired into the app yet. F4 does that; see
[parallel-focus/handoff-f3.md](parallel-focus/handoff-f3.md).

## Modules

| Module | What's in it |
|---|---|
| `coach.py` | `EvidenceBasedCoach` (implements `focus_contract.StudyCoach`), `teach_back_directive`, `mastery_for`, `mastery_from_skill_model` |
| `quiz.py` | `generate_review_items`, `parse_review_items`, `template_items` |
| `scheduler.py` | `SqliteReviewScheduler`, `ReviewScheduler` protocol, `next_schedule`, `interleave`, `similar` |

## Coaching rules (`EvidenceBasedCoach.next_move`)

State is kept per `LearnerEvent.problem_id`, and all timing comes from
`LearnerEvent.at`, so tests don't need a clock.

| Event | Move | Rule |
|---|---|---|
| `HELP_REQUESTED`, first on a problem | `GUIDING_QUESTION` (default) | Hints first. The start rung fades with mastery: below 0.3 it's `WORKED_EXAMPLE`, from 0.3 up to 0.7 it's `HINT`, and from 0.7 it's `GUIDING_QUESTION` with a cap at `PARTIAL_STEP`. Only a novice ever starts at a worked example. |
| `HELP_REQUESTED`, later | next rung up `HELP_LADDER` | One rung per request, capped as above. |
| 3 `HELP_REQUESTED` within 30 s, no attempt between | `TRY_FIRST` | Hint abuse. The request counter resets after the refusal, and the next request always gets real help: never two refusals in a row. |
| `ATTEMPT_FAILED` | `FEEDBACK` | Says what was right and what went wrong, then gives the next rung's instruction. The ladder climbs one rung (or starts at the start rung). |
| `ATTEMPT_SUCCEEDED` | `SELF_EXPLAIN` or `FEEDBACK` | `SELF_EXPLAIN` only if the problem was solved with at most a hint, no worked example was shown or given for it, and no other self-explanation prompt happened in the last 5 minutes. Otherwise informative `FEEDBACK`. Closes the problem. |
| `STUCK`, not right after a `WAIT` or `TRY_FIRST` | `WAIT` | `wait_seconds` = 45 s, halved after one failure and quartered after two or more (never below 10 s), and ×1.5 at mastery ≥ 0.7. |
| `STUCK` again, after a `WAIT` or `TRY_FIRST` | `GUIDING_QUESTION`, or the current rung | Offered gently. Help nobody asked for never climbs the ladder. |
| `WORKED_EXAMPLE_SHOWN` | `WAIT` | Marks the problem, so the success that follows never gets a self-explanation prompt (Barbieri et al.: negative effect). |
| `EXPLANATION_GIVEN` | `FEEDBACK` | Counts as an attempt, so it resets the hint-abuse counter. |

**Mastery.** Pass `mastery` from the skill model (`mastery_from_skill_model`
uses the lowest mastery among the event's concepts). Without it, the coach
estimates mastery from this session: a Laplace-smoothed success rate for the
event's concepts, used once there are 3 or more outcomes. A success with more
than a hint counts as half a success. With no estimate either, it behaves like
the default row (start at `GUIDING_QUESTION`, no cap).

All thresholds are constructor arguments. `reset(problem_id=None)` forgets one
problem, or the whole session.

## Quizzes (`generate_review_items`)

This asks the model for 2–3 recall questions as a JSON array of
`{concept, question, answer}`. The parser strips code fences, takes the
outermost `[...]`, and drops entries that aren't objects, that have missing or
non-string fields, that repeat a question, or that look like recognition
questions (yes/no openers, "true or false", "which of the following", lettered
options). An unknown concept is guessed from the question text. Model errors,
timeouts (20 s by default), unparsable replies and replies with fewer than two
usable items all fall back to template questions, or get topped up with them:

1. `Where do you find {concept}{ in app}?`
2. `What is {concept} for, and when would you use it?`
3. `What steps did you take to use {concept} today?`

Templates go round-robin over the concepts. The answer is the session notes
that mention the concept (so walkthrough step text gives real answers), or
"Compare with how you did it in today's session." Items are due at `now`, so
the end-of-session quiz can ask them right away. `record_review` then
schedules them.

Privacy: `context` notes are sent to the model, so pass only text the user
allows to leave the device (walkthrough step text, never window titles unless
allowed).

## Spaced review (`SqliteReviewScheduler`)

The schedule is SM-2 style. A correct answer gives 1 day, then 3 days, then
the previous interval × ease, with ease +0.1 up to 3.0. A wrong answer resets
the item to 1 day and 0 repetitions, adds a lapse, and lowers ease by 0.2,
down to 1.3. Ease lives in the database, not in `ReviewItem`. The longest
interval is 365 days.

Items are stored in `user_data_path("Curio")/study_reviews.sqlite3` by
default. `":memory:"` keeps them for the current process only, and
`EvidenceBasedCoach()` uses that when it isn't given a scheduler. All SQLite
work runs on one worker thread. The same question on the same concept (case
and spacing ignored) is stored once. `items()`, `delete(id)` and `clear()` keep
items visible and deletable.

**Interleaving.** `due_reviews(now, limit)` takes up to `4 × limit` due items,
most overdue first, and reorders them so that consecutive items never share a
concept when there's another choice. When there is, it prefers a concept that
is easily confused with the previous one: a bundled pair (vlookup ↔ index
match, absolute ↔ relative reference, layer ↔ mask, …) or a shared content
word.

## Teach-back

`teach_back_directive(concept)` makes Curio play a curious beginner who asks
naive follow-up questions. The evidence is weak to moderate, so it's optional
and we make no claims about it.

## Tests

The tests are `tests/test_study_coach.py` (every coaching rule, including the
negative ones) and `tests/test_study_coach_reviews.py` (interval growth and
lapses, persistence, interleaving order, malformed model output and the
template fallback).
