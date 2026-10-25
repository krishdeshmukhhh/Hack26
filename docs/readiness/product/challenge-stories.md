# Traceable engineering challenge stories

Reviewed 24 October 2026. Commit messages are historical developer reports, not
new experiments by this worker. Named tests were inspected, not run here. File
links point to the current checkout; use `git show <hash> -- <path>` for historical
versions. All named commits exist in the reviewed history.

## 1. A model’s step count ended the walkthrough too early

**Problem/evidence:** commit
`integration snapshot`, “Keep walkthroughs going until the
model says the task is done,” reports the 30B model emitted `[STEP:1/1]` in three
of three wallpaper-task runs. It also records Whisper dropping “how,” preventing
walkthrough detection. This is a developer’s small live check, not a
representative reliability or speech-recognition study.

**Change:** step totals became display-only; any STEP tag waits for a click and
another observation. Tagless output ends the loop. Request detection accepts
other task phrasings. [Manager](../../../curio-py/curio/companion_manager.py),
[prompts](../../../curio-py/curio/prompts.py).

**Regression:** `test_underestimated_step_total_still_continues` in
[test_walkthrough.py](../../../curio-py/tests/test_walkthrough.py) scripts 1/1
followed by further steps, asserting three requests before idle.
[Step-tag tests](../../../curio-py/tests/test_step_tags.py) cover parsing.

**Presentation:** “We stopped treating a model’s estimated step total as control
flow.” Tagless output can still prematurely declare success. This supports
continued observation, not independently verified completion.

## 2. Typing could permanently disable the activation hotkey

**Problem/cause:** commit
`integration snapshot`, “Fix Ctrl+Alt hotkey getting
permanently stuck after typing,” describes a key pressed as uppercase `I` and
released as lowercase `i` after Shift release. A character-key held set retained
a phantom key, blocking strict Ctrl+Alt activation.

**Change:** [hotkey.py](../../../curio-py/curio/hotkey.py) normalizes character
keys by virtual-key code and prunes stale keys using Windows key state.

**Regressions:** `test_shift_released_before_letter_does_not_block_hotkey` and
`test_stale_key_is_pruned_using_os_key_state` in
[test_hotkey_stuck_keys.py](../../../curio-py/tests/test_hotkey_stuck_keys.py)
exercise the sequence and mocked OS-state recovery.

**Presentation:** “We traced an activation failure to physical-key identity and
added regressions.” Not evidence for every keyboard layout, elevated application
or packaged build.

## 3. Learning components needed a real integration path

**Trace:** `integration snapshot` added recording/fan-out; `integration snapshot` the SQLite task map;
`integration snapshot` BKT/concept graph; `integration snapshot` sync/server/dashboard;
`integration snapshot` wired real implementations.
[WS1 handoff](../../parallel/handoff-ws1.md) records ranking handling and known
retry-path wording/target loss.

**Problem:** isolated components do not establish that records reach another
instance’s request context, or that storage/network failures leave turns usable.

**Change/evidence:** [LearningServices](../../../curio-py/curio/learning_events/services.py)
fans writes out in background tasks and bounds context reads at 1.5 s.
`test_walkthrough_on_one_laptop_guides_the_next` in
[test_learning_end_to_end.py](../../../curio-py/tests/test_learning_end_to_end.py)
uses real SQLite stores, loopback HTTP and two service instances. It asserts shared
path text reaches the second request and a window title stays out of the server
file. Replies/clicks are scripted; no two physical laptops or human learners.
`test_failing_learning_never_breaks_the_turn` in
[integration tests](../../../curio-py/tests/test_learning_integration.py) covers
failure isolation.

**Presentation:** “We checked the path from recording through storage/sharing to
later request context with real components and scripted turns.” No learning
experiment follows. Stored completion can be wrong; the test retains apology
wording and can lose the target after a hint-only retry.

## 4. Explanations and correctness needed separate authority

**Trace:** commit `integration snapshot`, “feat: integrate tutorial coaching, live tutoring,
and file uploads.” [Integration review](../../coaching-integration.md) reports an
initial native Qt access violation and cleanup changes; this is documentation
evidence, not a reconstructed commit-by-commit crash experiment.

**Design/evidence:** [exact checker](../../../curio-py/curio/live_tutoring/checker.py)
uses allowlisted parsing and rational polynomial algebra. Recognition is editable
and confirmed before assessment. In
[test_live_tutoring.py](../../../curio-py/tests/test_live_tutoring.py),
`test_first_error_and_recovery` and
`test_guided_completion_does_not_establish_independent_understanding` distinguish
correction from guided completion. In
[test_coaching_integration.py](../../../curio-py/tests/test_coaching_integration.py),
`test_screen_checks_are_suggestions_and_equation_recognition_requires_confirmation`
keeps suggestions separate from correctness.

**Presentation:** “For a narrow math slice we check the answer independently of
the explanation model.” No arbitrary calculus, general GUI verification or proven
student learning follows.

## Current readiness review is separate

The [integrity handoff](../integrity/handoff.md) describes uncommitted timeout
weighting, estimated-mastery wording and simulation-label changes. They are not
historical work attributable to the commits above. Product research did not
implement them. Their lesson: event counts, model progress and seeded records
need accurate presentation labels.
