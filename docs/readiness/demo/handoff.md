# Demo reliability handoff

Workstream date: 2026-10-24. Base HEAD at inspection: integration snapshot. The shared checkout includes pre-existing uncommitted production edits. Only owned readiness paths were edited. Production, contracts, dependencies and existing tests were left unchanged.

## Delivered and verified

The chosen end-to-end technical demonstration uses ordinary Excel pivot-table guidance: unfamiliar request, contextual screenshot request, missed step/retry, model-reported completion, real event/path persistence, same-host HTTP sharing, and later retrieved corrected workflow context. It does not verify Excel state or involve two physical laptops. Existing test helpers provide mocked model, screen, clicks, microphone and TTS; they are imported without modifying them. The project Python 3.12 venv was used directly, avoiding dependency installation and uv cache writes.

Five new checks cover the journey/restart, text versus image construction, fresh versus retrieved context, recommendations by seeded evidence history, disabled learning and exact-math comparison (some share one case). Existing focused checks cover cancellation, stale provider/capture output, coaching mode changes, cleanup, voice boundaries and transport failures.

- `curio-py/.venv/Scripts/python.exe scripts/readiness/demo/run_checks.py`: final **99 passed in 6.01s**, exit 0. Exact expanded pytest command and UUID basetemp are in check-results.txt. Cache and bytecode writing disabled. First development run: 3 passed, 1 failed because text-only content was a string; owned harness corrected, no production change.
- `curio-py/.venv/Scripts/python.exe -m ruff check tests/readiness/test_demo_journey.py scripts/readiness/demo/run_checks.py scripts/readiness/demo/windows_smoke.py --config curio-py/pyproject.toml`: **All checks passed**, exit 0. Earlier Ruff --fix corrected four owned import issues, then format changed the three owned files. Tests rerun afterward.
- `$env:PYTHONPATH="$pwd/curio-py"; $env:PYTHONDONTWRITEBYTECODE='1'; curio-py/.venv/Scripts/python.exe scripts/readiness/demo/windows_smoke.py`: exit 0, real Qt offscreen capture with seeded attempts, 25 enumerated devices, zero TTS voices. See windows-smoke.json and seeded-offscreen-tutor.png. Discovery/rendering is not playback or physical UI verification.
- Native SAPI smoke: exact command in defects.md; **8 failed in 2.75s**, access denied. Shell redirection's final exit code was 0 because it then read the log; pytest itself failed. Full failures retained in native-smoke.txt.
- Unauthenticated read-only `httpx.get('http://127.0.0.1:8000/v1/models', timeout=2)` with project Python: result in provider-smoke.txt. No live inference verified; no configured remote endpoint/credentials were read or sent.

## Technical comparison results

Criteria were written before execution in criteria.md. Text-only versus synthetic screenshot yields 0 versus 1 image blocks. Fresh context lacks the shared path; retrieved context contains the retry's corrected Insert instruction and explicitly says model-reported completion. The mock model's two correctness assertions contrast with exact math rejection/acceptance for the missing/corrected factor 2. Empty versus 12 seeded unassisted success reports changes recommendation from pointed to none. Abandonment does not add skill attempts. These are request/evidence-policy checks, not human usability experiments or proof of improved learning.

## Coordinator actions and remaining manual checks

See defects.md: native SAPI access blocker; obsolete isolated-integration wording in live-tutoring.md. No new algorithmic production defect confirmed. Model completion and transient tutoring limitations must remain explicit. Coordinate any future persistence/independent verification changes outside this scope.

Rehearse actual Excel completion/recovery and later-session behavior, Ctrl+Alt/Escape, acoustic microphone, speaker playback, noisy-room wake, live model latency and grounding, projector/DPI, packaged app shutdown and restart. Physical laptop sharing needs two machines, firewall/connectivity checks and fresh data on B; loopback evidence cannot satisfy it. No live video exists.

The three-minute timeline is demo-script.md; fallback-demo.md uses labeled technical traces and seeded offscreen capture. All four created pytest temp directories were removed after inspection using resolved workspace-contained paths; clients/stores and the loopback server/thread close in tests. Runtime databases and generated audio are not committed. Existing preflight and sync-recovery files from the prior handoff are preserved.

Commit only explicit owned files; do not stage the shared working tree. No push or publication is authorized.

## Commit blocker

Attempted explicit `git add --` of the 13 delivered files and `git commit -m "Add reproducible demo reliability checks and evidence"`. Both failed: `Unable to create .git/index.lock: Permission denied`. No commit hash exists for this delivery. The environment grants read-only access to .git and escalation is unavailable. Run scripts/readiness/demo/commit-owned.ps1 from an authorized repository shell to stage only this delivery and commit it. Nothing was pushed or published.
