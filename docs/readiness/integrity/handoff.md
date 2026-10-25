# Verification integrity handoff

## Exact owned files (declared before edits)
- docs/readiness/integrity/handoff.md
- curio-py/curio/learning_events/evidence.py (new)
- curio-py/curio/learning_events/recorder.py
- curio-py/curio/learning_events/store.py
- curio-py/curio/skills/model.py (preserve pre-existing edits)
- curio-py/curio/map_sync/server.py
- curio-py/curio/map_sync/seed.py
- curio-py/curio/map_sync/assets/dashboard.html
- curio-py/tests/test_verification_integrity.py (new)

No ownership of app.py, CompanionManager, contracts, config, manifests or the four main docs. Existing dirty files will not be staged wholesale.

Additional owned files declared before editing:
- curio-py/curio/task_map/store.py
- curio-py/tests/test_skills_model.py (only prompt expectations; preserve existing edits)

Additional owned file declared before editing:
- curio-py/curio/learning_events/context.py

## Findings and changes

1. Recorder inferred success from a rising model STEP index, and inferred retry from a repeated/lower index. Neither establishes correctness. New EvidenceStepEvent retains the legacy outcome for API compatibility and separately stores model_inferred, user_confirmed, checked_success, checked_failure, or unknown. Checked results require a nonempty opaque result reference and a matching outcome. Only checked_success exposes independently_verified=True. Caller adapters remain responsible for actually checking work; a reference alone cannot establish truth.
2. A later failed attempt could leave an earlier success eligible for a local path. clean_steps now selects final attempts; reinforcement refuses any final non-success despite completed=True. Shared aggregation applies the same rule. This changes behavior, not just vocabulary.
3. Skill prompt context and the assistance wrapper asserted that the user knows concepts or has done a task before. Both now describe unvalidated estimates and hypothetical transfer. The BKT numerical algorithm, prior, stored history and help thresholds remain estimates, not calibrated measurements. No historical mastery values were rewritten.
4. Seed posts lost all synthetic provenance through summary_to_wire. seed.post_all now marks synthetic=True; the server strictly validates and persists that optional marker. Default /v1/paths and /v1/stats exclude marked synthetic records, so demo observations cannot train ordinary sync clients. The dashboard explicitly requests include_synthetic=1, displays synthetic/unknown counts, labels completion model-reported, and explains stuck signals. Shared paths explicitly carry evidence_basis=model_reported. Old unmarked seeds remain unknown; origin cannot be recovered from content.
5. TutorialCoach.confirm already records user_confirmed separately from accept_verified. Model screenshot matches already become MODEL_CLAIM plus unsupported/needs_clarification, not confirmed. The separate verifier route is injected and source-backed; this review cannot prove arbitrary provider implementations truthful. No changes were needed to that boundary.
6. The live tutor's bounded rational-polynomial checker uses exact Fraction algebra, differentiation and composition; its assessment adapter creates VERIFIER_RESULT for deterministic results. Model coaching/recognition stays separate. These implementations were preserved and their tests rerun. General mathematical expressions outside supported syntax remain unsupported, not approximately verified.

## Compatibility and migration

- Event database schema 1 -> 2 adds evidence_basis='unknown' and evidence_ref='' in a transaction; old rows, IDs, instructions, outcomes and timestamps are retained. New databases use the same migration. Unsupported newer schema versions still fail safely. Legacy StepEvent rows deserialize as StepEvent for existing equality/API compatibility; consumers must default missing provenance to unknown, never checked success.
- EvidenceStepEvent is a frozen StepEvent subclass, preserving protocol consumers. Recorder defaults to model_inferred, including model completion. Explicit user confirmation can call finish(..., evidence_basis='user_confirmed'). Existing callers require no argument changes.
- TaskPath.verified_count and existing SQL verification table names remain legacy report counters. Existing stored paths are retained. New contradictory summaries cannot reinforce them. Old paths cannot be retrospectively certified or disproved.
- Shared contract/wire serialization currently omits local per-step provenance; remote paths are deliberately downgraded to model_reported, never upgraded to independent verification. Skill evidence likewise retains legacy outcomes and must be understood as estimates; typed provenance across all consumers requires the contract change below.
- New seed posts require the updated server (older strict servers reject the optional field). Missing synthetic markers mean unknown, including ordinary clients; false is also treated as unknown, not proof of genuine human use.

## Before / after examples

- STEP 1 -> STEP 2: bare succeeded -> legacy succeeded plus durable model_inferred; independently_verified is false.
- User says completed: no explicit learning evidence category -> optional user_confirmed category, still not independently verified.
- STEP 1 positive, then STEP 1 fails, completed=True: old positive path could be reinforced -> final contradiction prevents local/shared path creation.
- Five apparent successes: 'The user knows layers well' -> 'Unvalidated skill estimate ... not measured mastery'; transfer is expressly hypothetical.
- Run map seeder: fake activity mixed into real sync paths/stats -> visible synthetic dashboard counts; default sync excludes those records.
- Exact supported derivative equality: deterministic checked result before and after; no model verdict substituted.

## Coordinator actions (required)

1. Shared learning_contract.py: add explicit evidence basis and result reference to StepEvent; make inferred progress/repetition distinct from independently checked success/failure. Move/replace the temporary local subclass with that shared representation. Add completed_basis to WalkthroughSummary and explicit report_count/provenance to TaskPath. Migrate/parse old absent fields as unknown. Keep old enum/wire aliases readable; do not reinterpret existing succeeded/verified_count as proof. Extend summary/path serializers only after coordinated client/server version handling. Never export local evidence references containing private artifact details.
2. CompanionManager: at _finish_recording (currently recording.finish(outcome, completed=completed)), propagate the actual evidence origin once available. Its _finish_walkthrough currently uses SUCCEEDED for a model DONE response: keep this inferred, not checked. A genuine user confirmation must use user_confirmed; clicks alone remain navigation. Only a verifier that checks relevant current work may issue checked_success/checked_failure with a result reference. Keep completion and verified success separate in signals/logs/UI.
3. app.py/coaching wiring: preserve tutorial confirmation vs injected verification and exact math vs model coaching. Do not turn a model 'verified' string, a user confirmation, a click, or a completed lifecycle into source-backed verifier evidence. Label model answers as suggestions and reserve exact-check claims for supported checker results. No app.py change was made here.
4. Retain/review the pre-existing uncommitted changes in task_map/prompt.py, skills/widget.py, skills/demo.py and associated tests: they already qualify model reports and estimates and isolate Skills demo storage. Those changes are NOT included in this workstream commit. Remaining Skills demo provenance is not durable (isolated database/default path helps but mixing can still occur); add an explicit synthetic-origin field to skill evidence and a visible banner before claiming full provenance support. My prompt fixes do not depend on calling those estimates measured mastery.
5. Four main docs (ARCHITECTURE.md, RUNNING.md, features.md, PROGRESS.md): replace any 'verified path'/'verification count' claims with model-reported path/completion count; distinguish user confirmation from checks, estimates from measurement, and supported exact checks from model judgments. Update current notes saying map sync has no synthetic provenance: new marked seed records are now isolated from normal sync, while legacy origin remains unknown. Keep manual/live-provider/package validation claims scoped to actual evidence. Also align docs/task-map.md, docs/map-sync.md and docs/skills.md with these semantics and synthetic dashboard behavior; they remain untouched here.
6. On deployment, update the map server before running the new seeder. Isolate/archive old demo data; do not automatically mark historical unlabelled data genuine. No deployment/push was performed.

## Checks actually run

uv was not on PATH. Used curio-py/.venv/Scripts/python.exe (Python 3.12) directly from curio-py.

- Red tests reproduced missing recorder provenance, missing explicit confirmation support, rejected synthetic marker, and later failure incorrectly reinforcing a path.
- Scoped Ruff: curio/learning_events/{evidence,recorder,store,context}.py, curio/map_sync/{server,seed}.py, curio/skills/model.py, curio/task_map/store.py, tests/test_verification_integrity.py, tests/test_skills_model.py. Final result recorded below.
- Affected pytest: tests/test_verification_integrity.py tests/test_learning_events.py tests/test_map_sync.py tests/test_skills_model.py tests/test_task_map.py tests/test_live_tutoring.py tests/test_coaching_contract.py tests/test_tutorial_coach_contract.py tests/test_learning_integration.py tests/test_learning_end_to_end.py tests/test_skills_widget.py tests/test_skills_demo.py. Final result recorded below.
- New tests exercise v1 SQLite migration, event round trip, inferred/user/checked distinctions, invalid checked-result references/outcomes, contradictory completion, synthetic persistence, and real HTTP seed -> server -> default sync/demo dashboard separation.
- No physical desktop interaction, live model, rendered browser dashboard, packaging, deployment or general-math validation claimed. No full-repository lint/test claim. Tests run against the shared working tree, including pre-existing edits; only this workstream's changes are staged.

Final validation: affected pytest passed (174 tests, 9 subtests; 20.56 seconds). Scoped Ruff passed. The earlier failing prompt expectations were updated to assert estimates; the earlier path regression now passes.

## Commit limitation and exact staging action

Git staging was attempted, but the environment rejected creation of .git/index.lock with Permission denied. This session only has read access to .git and cannot request elevated permissions. No commit/hash was created; no push occurred.

Additional owned artifact declared before creation: docs/readiness/integrity/changes.patch. It contains only this workstream's patch against HEAD, excluding pre-existing edits (including the existing timeout change in skills/model.py and its existing tests). It does not include itself.

Coordinator, in this same working tree with Git write access, run:

```powershell
git apply --cached docs/readiness/integrity/changes.patch
git diff --cached --check
git diff --cached --stat
git commit -m "Preserve learning evidence provenance and isolate synthetic map data"
git rev-parse HEAD
```

The cached patch deliberately stages this workstream's versions only. Preserve other working-tree changes and do not use git add . . On a clean checkout use git apply --index instead. Review and separately integrate the pre-existing label/demo/timeout fixes listed above. The generated patch is a handoff artifact, not a replacement for the required coordinator integration actions.
