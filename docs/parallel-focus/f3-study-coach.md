# F3: study coach (tutoring moves, quizzes, spaced review)

You own `curio/study_coach/`. Read `docs/parallel-focus/README.md`,
section G of `docs/focus-learning-research.md` (every row is a requirement),
`curio-py/curio/focus_contract.py`, and skim `coaching_contract.py` (the
existing hint/explanation/worked_example levels, which `COACHING_LEVEL` maps
to) and `learning_contract.py` (`SkillModel`, `concept_key`).

## 1. `EvidenceBasedCoach` (implements `StudyCoach`)

`next_move(event, mastery)` returns a `TutorDirective` whose `instruction` is
one or two plain lines that integration adds to the model request. Keep
per-problem state keyed by `LearnerEvent.problem_id`.

- **Hints first:** the first `HELP_REQUESTED` on a problem gets
  `GUIDING_QUESTION`; each further request or `ATTEMPT_FAILED` moves one rung
  up `HELP_LADDER`. Never start at a worked example, except below.
- **Fading by skill:** with `mastery` (from the skill model) below a novice
  threshold, start at `WORKED_EXAMPLE`; at middling mastery start at `HINT`;
  at high mastery start at `GUIDING_QUESTION` and cap at `PARTIAL_STEP`.
  Without mastery, use a simple local estimate from this session's events.
- **Hint abuse:** several `HELP_REQUESTED` within a short window with no
  attempt in between → `TRY_FIRST` ("what have you tried so far?"). Never
  refuse help twice in a row: not asking for help hurts too.
- **Wait before stepping in:** a `STUCK` event with no help request →
  `WAIT` with `wait_seconds` (default about 45 s, shorter after repeated
  failures, longer at high mastery), then `GUIDING_QUESTION` if still stuck.
- **Self-explanation:** after `ATTEMPT_SUCCEEDED` on a problem the learner
  solved with at most a hint → `SELF_EXPLAIN` ("why did that work?"). **Never
  directly after `WORKED_EXAMPLE_SHOWN`** (Barbieri: negative effect). Not on
  every success; rate-limit it.
- **Feedback:** after an attempt, `FEEDBACK` instructions ask for what was
  right or wrong and the next step, not bare praise.
- Every directive gets its `rationale` letter ("G").

Test each rule, especially the negative ones (no self-explanation after a
worked example, no worked example first for a non-novice, no double refusal).

## 2. Quizzes and spaced review

- `generate_review_items(concepts, context, model_call)`: from the session's
  concepts (and optional notes such as walkthrough step text), produce two or
  three short retrieval questions with answers via `ModelCall`, as JSON,
  parsed defensively. Template questions are the fallback ("where do you find
  X in Y?"). Questions should require recall, not recognition.
- `SqliteReviewScheduler` (used by `due_reviews`, `record_review`,
  `add_review_items`): spaced repetition with growing intervals, for
  example an SM-2-style schedule: correct → interval × ease, wrong → back to
  short intervals and lower ease. Store items locally.
- **Interleaving:** `due_reviews` mixes similar concepts instead of grouping
  them. Similarity from a small bundled list of easily confused pairs
  (vlookup ↔ index match, absolute ↔ relative references, layers ↔ masks)
  plus shared words; avoid two consecutive items on the same concept.
- Answers are always shown after the learner responds (feedback strengthens
  the testing effect).

## 3. Teach-back (optional, lowest priority)

`teach_back_directive(concept)`: Curio plays a curious beginner and asks
naive follow-up questions. The research rates this weak-to-moderate, so ship
only if everything else is done, and make no claims about it.

## Done when

Deterministic tests cover every coaching rule, the scheduler's interval
growth and lapses, interleaving order, malformed model output for quizzes,
and the template fallback. Write `docs/study-coach.md` and
`docs/parallel-focus/handoff-f3.md` with constructor signatures and the
exact directive texts for F4.
