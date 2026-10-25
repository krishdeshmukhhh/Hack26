# Hackathon readiness

Review date: 2026-10-24. Baseline: `integration snapshot`
on `main`. Initial `git status --porcelain=v1` was empty. No existing work was
discarded or included in a new baseline commit. The existing merge commit is
the common reviewed source baseline, not a newly created commit.

Updated four-worker handoffs have now been integrated and reverified; see
[coordinator integration review](readiness/integration-review.md). This follow-up
preserved the existing dirty first-pass work. Latest results below supersede
earlier worker counts; counts from overlapping suites must not be summed.

## Rubric and evidence register

Only category names were supplied; official scoring descriptors/weights remain
a human check. Requirements below are working evidence goals, not official
rubric quotations or predictions of scores.

| Category | Working requirement | Current evidence | Gap / verification | Owner | Status |
| --- | --- | --- | --- | --- | --- |
| Innovation | Explain a distinctive, useful design and acknowledge overlap | Voice/screenshot/POINT loop; task-map and concept guidance; `integration snapshot`, `docs/use-case-evidence.md` | Compare against screen-aware assistants; no first-ever claim | Product | Source-backed; live demo pending |
| Curiosity | Show investigated questions and contrary findings | Research register includes negative/limited effects; exact checker versus model claims | Recheck research sources before citing numerical findings; run learner pilot | Product + Impact | Research exists; product outcomes unmeasured |
| Communication | Explain audience, architecture and evidence clearly | Four updated main docs; combined presentation package and diagrams | Rehearse timed demo, projector readability and Q&A | Coordinator | Package prepared; rehearsal pending |
| Breadth & Complexity | Demonstrate integrated technical depth | Qt/qasync, local/cloud clients, speech, capture, SQLite, map HTTP server, bounded exact algebra | Physical device/network/package tests | Integrity + Demo | Automated checks complete; live checks pending |
| Impact | Describe a specific need and measure real outcomes | Existing external software-learning research; proposed learner audience | Consented counterbalanced pilot; correct completion, timeouts and transfer | Impact | No Curio human outcome results |
| Challenge Navigation | Trace a difficulty, design response and evidence | `docs/coaching-integration.md`, `docs/memory-integration.md`, hands-free history | Fresh cancellation/failure tests plus live device checks | Demo + Coordinator | Source-backed; live checks pending |

## Ownership and handoff gate

Product owns `docs/readiness/product/` only. Integrity owns outcome/evidence/skill
correctness and associated tests, with documentation in `docs/readiness/integrity/`.
Impact owns `docs/readiness/impact/` and `scripts/readiness/impact/`. Demo owns
`tests/readiness/`, `scripts/readiness/demo/`, `docs/readiness/demo/`; it reports
production fixes. Coordinator owns app.py, CompanionManager, shared contracts,
configuration, dependencies, four main docs, this checklist and presentation.
Outside-ownership proposals must be recorded in handoffs. No overlapping edits.

All four handoffs must be reviewed before final integration checks. Git metadata
writes are blocked; integration in this session means sequential diff review in
the current checkout, not Git merges. Workers use disjoint paths here because
host-created worktrees are outside writable roots. Four workers are scheduled
with at most three running alongside the coordinator due to the four-slot limit.

## Setup limitations

Native worktree creation uses the exact baseline, detached. Named branch creation
failed: `cannot lock ref ... unable to create directory .../.git/refs/heads/readiness`.
Do not interpret detached worktrees as the requested named branches. No new
baseline commit, worker branch, merge or integration commit is claimed.

All four native detached worktrees were created and `rev-parse HEAD` confirmed
the exact baseline in each:

| Intended branch (NOT created) | Actual absolute detached worktree path |
| --- | --- |
| readiness/product-evidence | `C:\Users\Veges\.codex\worktrees\0acc\Hack26` |
| readiness/verification-integrity | `C:\Users\Veges\.codex\worktrees\ed88\Hack26` |
| readiness/impact-validation | `C:\Users\Veges\.codex\worktrees\df67\Hack26` |
| readiness/demo-reliability | `C:\Users\Veges\.codex\worktrees\dc6e\Hack26` |

WezTerm was not installed. Windows Terminal launch failed because its app alias
could not be accessed. Direct Windows PowerShell `Start-Process -NoExit` with
each working directory returned PIDs 30172, 22404, 18856, 32524 respectively.
Visible window presence was not independently observed. No worker runs in those
read-only worktrees. Do not ask parallel terminal workers to edit this checkout
without preserving the ownership rules.

Staging the reviewed checklist failed creating `.git/index.lock`: permission
denied. No new commit or merge exists. No push, deployment, publication or
submission occurred.

## Verification rules

Distinguish real component tests, mocked providers, synthetic fixtures, external
research and live human observations. A click/model saying done is not independent
task verification; a skill probability is not measured mastery. Seeder output is
simulated, not users. No productivity, retention, accessibility, adoption, fraud
prevention or uniqueness claims without supporting measurements.

Requested `uv run pytest` and `uv run ruff check .` initially failed because uv
was absent from PATH. Absolute uv executable exists under `.local/bin`; normal
uv runs then failed to fetch hatchling because networking is restricted. Retry
uses installed environment with `UV_NO_SYNC=1`, a workspace UV cache, a unique
temporary base and `-p no:cacheprovider`; no checks/rules are disabled.
Initial and final full lint: 23 findings in unchanged files (exit 1).

## Handoff review and sequential integration

All four handoffs were received before final integration verification:

1. [Product](readiness/product/handoff.md): reviewed all six product documents;
   accepted audience, six-category evidence matrix, traceable stories and claim
   limits into [presentation](presentation/README.md). The worker's primary-source
   review and access limits are documented; no human/competitor experiment occurred.
2. [Integrity](readiness/integrity/handoff.md): reviewed every source/test diff;
   accepted timeout exclusion, estimated-skill labels, qualified recorded-path
   prompt and separate simulated demo DB. Coordinator corrected the shared
   shared contract and manager propagation while preserving enum/wire aliases.
   Event/skill/path provenance now migrates conservatively; stored estimates are
   not recalculated. New synthetic markers persist; old unmarked seeds stay unknown.
3. [Impact](readiness/impact/handoff.md): reviewed Calc study-plan, blank templates,
   analyzer and synthetic fixtures. Accepted failure/missingness-inclusive reporting.
   Three analyzer tests pass; human recruitment/results remain pending.
4. [Demo](readiness/demo/handoff.md): reviewed recovery/cancellation tests,
   preflight, journey/visual exhibits and fallback. Accepted separate root test
   invocation; native SAPI had eight access-denied failures and model probe timed
   out. Corrected obsolete tutoring docs and unreadable font in the seeded exhibit.

There were no Git merges because Git metadata is read-only. This is sequential
review of disjoint working-tree changes. The final presentation, main docs and
shared comments were integrated by the coordinator. Wire field names and config/
dependency manifests are unchanged. Skill-context phrases now explicitly qualify
estimates; no calibrated knowledge or cross-app transfer claim is supported.

Integration checks exposed and corrected a stale `get stuck` assertion in
`test_learning_events.py` after the prompt wording changed. A full run before
that correction had 1 failed, 580 passed, 8 skipped and 9 subtests passed. A root
Ruff run using project rules exposed two demo lint issues missed by default root
rules; both were corrected. App lint must run from `curio-py` because import
classification differs by working directory. Final results are recorded below.

## Final results

Windows / Python 3.12.15 / PySide6 6.11.0; installed-environment commands:

| Check | Actual result | Evidence boundary |
| --- | --- | --- |
| Full app pytest through uv | 592 passed, 8 skipped, 9 subtests passed; 31.60s; exit 0 | Offscreen/component suite; native opt-in tests skipped |
| Separate root readiness suite | 11 passed; 3.32s; exit 0 | Scripted providers/perception, real persistence and loopback transport |
| Full app Ruff through uv | 23 findings; exit 1 | Same unchanged files as initial run; no weakened rules |
| Changed app Python Ruff | Passed from curio-py | Includes coordinator shared comment changes |
| New root scripts/tests Ruff | Passed with project config | Full configured rules |
| Offline preflight | 13 checks passed | Discovery/assets only |
| Current impact analyzer / blank CSV | 3 tests passed / zero participants | Synthetic fixtures / no observations |
| Recorded worker native SAPI / model probes | 8 access-denied failures / ConnectTimeout | Open environment blockers; not live inference success |
| Coordinator Qt exhibit | Regenerated and visually inspected readable with font and evidence label | Seeded typed inputs, real Qt/exact checker; zero TTS voices |
| git diff --check | Passed | Whitespace check |
| Git staging / commit | Blocked by index.lock permission | No new commit |

Latest logs: [pytest](presentation/validation/integrated-pytest.log),
[readiness](presentation/validation/integrated-readiness.log),
[full Ruff](presentation/validation/integrated-ruff.log). Earlier logs retained as
history. Local Markdown link check: 112 links resolved; demo script normalized
from Windows-1252 to UTF-8 without changing text. No human/live outcome experiment
was run. [PROGRESS.md](PROGRESS.md) records environment and earlier failed runs.
All four handoffs are reviewed and presentation artifacts prepared; live gates
remain open. No score or human outcome guarantee is supported.

## Human gate before judging

- Confirm official category descriptors, judging logistics and allowed demo data.
- Run real microphone, speaker, hotkey, wake/pause/question, cancellation and
  POINT checks on the actual laptop/projector and configured model.
- Rehearse network/model failure; obtain a genuine labeled backup recording.
- Test fresh packaged executable, DPI/monitor edges and normal shutdown.
- Run and record a consented pilot before making human benefit claims.

## Reviewable change selection

Include only the reviewed source/test changes, four main project docs, this
register, `docs/readiness/`, `docs/presentation/`, `scripts/readiness/` and
`tests/readiness/` in a future commit. Do not use `git add .`: generated
`curio-py/.readiness-tmp/`, workspace caches and duplicate root readiness logs
are not deliverables. Automatic approval review rejected scratch cleanup as
“blocked by policy”; it supplied no further reason. Files were left intact and
final logs copied non-destructively into `docs/presentation/validation/`.

Suggested integration subject: `Strengthen hackathon evidence and demo readiness`.
No commit with this subject was created. See the [delivery self-review](presentation/review.md).
