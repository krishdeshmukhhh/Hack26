# Curio claim audit

Reviewed 24 October 2026 at HEAD `integration snapshot`.
Other workers have uncommitted readiness changes in the shared checkout; these
are distinguished from the committed baseline below.

**Implemented** means source inspected; **test-covered** means assertions
inspected, not executed here; **historical observation** means a commit/doc reports
a prior run; **research** means another system’s study; **hypothesis** means
unmeasured intended benefit. No new live demo, competitor benchmark or human study
was performed by this workstream.

| Proposed claim | Verdict and safe wording | Trace / remaining requirement |
| --- | --- | --- |
| Explains and points at the screen | Implemented/test-covered: ordinary turns capture screens and parse POINT tags into overlays. | [Manager](../../../curio-py/curio/companion_manager.py), [mapper](../../../curio-py/curio/point_mapper.py), [mapper tests](../../../curio-py/tests/test_point_mapper.py). Live accuracy across apps/DPI unmeasured here. |
| No repeated uploads | Qualify: ordinary turns automatically attach fresh screenshots without a file picker each step. Capture still repeats. | Manager `_run_turn`/`_continue_walkthrough`; [walkthrough tests](../../../curio-py/tests/test_walkthrough.py). All monitors can be captured. Not a competitor-wide advantage; [comparison](comparison.md). |
| Recovers from a wrong click | Implemented opportunity, unproven reliability: next screenshot permits reassessment; retries are recorded. | [Recorder](../../../curio-py/curio/learning_events/recorder.py), [integration tests](../../../curio-py/tests/test_learning_integration.py). Need live wrong-panel/misleading-advice trials. |
| Learns successful workflows | Implemented/test-covered: stores paths after model-reported completion and reuses matches as references. | [Task map](../../../curio-py/curio/task_map/store.py), [services](../../../curio-py/curio/learning_events/services.py), [two-instance test](../../../curio-py/tests/test_learning_end_to_end.py), commit `integration snapshot`. Scripted model replies/clicks, real storage/loopback HTTP. |
| Verified paths / knows the task succeeded | Unsupported independent verification: progression/tagless output supplies the ordinary success signal. A click is not proof of correct state. | Manager `_update_walkthrough`; [contract](../../../curio-py/curio/learning_contract.py). Uncommitted integrity prompt says recorded/model-reported completion; baseline terminology overstates certainty. |
| Self-heals after UI updates | Implemented ranking heuristic, unproven recovery: recent paths can outrank stale ones. | [Task-map regression](../../../curio-py/tests/test_task_map.py), `test_self_healing_new_path_overtakes_stale_one`, commit `integration snapshot`. No real app-update experiment found. |
| Adapts assistance to experience | Implemented/test-covered: estimated concept state influences request context; model is asked to fade pointing. | [Skill model](../../../curio-py/curio/skills/model.py), [context](../../../curio-py/curio/learning_events/context.py), `test_repeated_success_lowers_assistance` in two-instance test. Enum-change assertion, not live compliance or learning. |
| Measures mastery / transfers learning across apps | Unsupported outcome claim. Safe: heuristic BKT estimates, concept aliases and parameterized transfer affect recommendations. | [Skill tests](../../../curio-py/tests/test_skills_model.py), commit `integration snapshot`. No calibration, delayed retention or learner-transfer study. Uncommitted integrity changes skip timeouts/label estimates; no historical recalibration. |
| Users control their learning record | Implemented Skills evidence, concept/all reset and JSON export; separate preference-memory approval. | [Skills widget](../../../curio-py/curio/skills/widget.py), [memory review](../../memory-integration.md). Skill updates are automatic when learning is enabled, not per-record approved; do not conflate them with opt-in approved preference memory. |
| Crowd knowledge / where most people get stuck | Sync implemented; crowd-size claim unsupported. Say shared recorded paths and stuck-event rates. | [Server](../../../curio-py/curio/map_sync/server.py), [seeder](../../../curio-py/curio/map_sync/seed.py), commit `integration snapshot`. Retry/timeout events are not unique people; seed data is SIMULATED. Uncommitted prompt removes “most people.” |
| Anonymous / entirely private | Unsupported absolute. Sharing defaults off; schema excludes screenshots/audio/window titles, but free-text tasks/instructions/labels can be sensitive. | [Config](../../../curio-py/curio/config.py), [wire schema](../../../curio-py/curio/learning_contract.py). Images go to the configured inference endpoint; local speech/storage does not imply local inference. |
| Verified AI tutor | Only a bounded slice: exact rational polynomial checks independent of model; recognition needs confirmation. | [Checker](../../../curio-py/curio/live_tutoring/checker.py), [tests](../../../curio-py/tests/test_live_tutoring.py), [coaching tests](../../../curio-py/tests/test_coaching_integration.py), commit `integration snapshot`. Unsupported math returns unsupported; no arbitrary desktop verification. |
| Understands any tutorial/video | Unsupported: public HTML or selected text-bearing TXT/Markdown/HTML/PDF. Video requires supplied transcript; no title-based content inference/scanned-PDF OCR. | [Files](../../../curio-py/curio/tutorial_coach/files.py), [coaching review](../../coaching-integration.md). Stale “not wired” paragraphs conflict with current runtime/tray integration; source/tests take precedence. |
| Hands-free means it does the task | Unsupported. Voice activation/submission exists; users still act. | [Hands-free](../../../curio-py/curio/hands_free.py), commit `integration snapshot`; current manager `_step_assistance` separates input mode from future execution. |
| First, unique, faster, better; improves retention/anxiety; universally accessible | Unsupported. Existing alternatives overlap; no controlled Curio outcome study found. | [Alternatives](comparison.md), [problem audit](problem-and-audience.md). Pet animation is presentation, not educational-effect evidence. |
| Detects scams; fully offline; packaged and ready | Not established as general shipped capabilities. | [Feature scope](../../features.md) includes aspirations; [running guide](../../RUNNING.md) lists manual/configuration gates. A “local” model endpoint may be a remote lab service. Typed exact checking is a limited offline slice. |

## Wording to use now

“The prototype records model-reported walkthrough progress and uses it to suggest
paths and assistance levels on later requests. Users can inspect concept evidence.
We have technical test coverage, but have not demonstrated improved learning,
task success or speed with users.”

Do not recycle historical suite counts as fresh results. This worker did not run
application tests; current results belong to the integrity/coordinator handoff.
Keep source assertions, scripted tests, desktop observations and human outcomes
separate in slides and narration.
