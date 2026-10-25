# Shared coaching contract

Application integration now exists in the working tree; see coaching-integration.md
and RUNNING.md. The isolation notes below describe the earlier foundation handoff,
not a claim that missing feature branches or commits were subsequently created.

Import from `curio.coaching_contract` (source:
`curio-py/curio/coaching_contract.py`). Standard library only; no Qt, network,
persistence, model client, or desktop side effects at import. Neither feature is
implemented or wired into the application by this foundation.

## Baseline and isolation status

Inspected branch: `main`. Existing memory baseline:
`integration snapshot` (`Continuous memory implemented.`).
Memory runtime, conversation, store, settings, learning and UI are already tracked
in that commit. Reviewed memory injection in app/manager and the untrusted-data
prompt boundary. Preserve these interfaces and existing tests. The initial only
untracked file, `docs/use-case-evidence.md`, is unrelated research and must remain
outside this commit.

Git staging failed creating `.git/index.lock` with permission denied in this
session. **No foundation commit, feature branches, or worktrees were created.**
The paths below are reserved targets, not existing worktrees. Do not launch a
worker against them until the foundation has been committed and checked out.

| Branch | Absolute target path |
| --- | --- |
| `feature/url-tutorial-coach` | `C:\Users\Veges\OneDrive\Documents\GitHub\Hack26\Hack26\.worktrees\url-tutorial-coach` |
| `feature/live-tutoring` | `C:\Users\Veges\OneDrive\Documents\GitHub\Hack26\Hack26\.worktrees\live-tutoring` |

These are sibling worktrees within the writable workspace. `.worktrees/` is
ignored. In a checkout permitting Git writes, stage only `.gitignore`, this doc,
`curio-py/curio/coaching_contract.py` and
`curio-py/tests/test_coaching_contract.py`; review the staged diff and commit.
Capture that exact commit, then create both branches from it:

```powershell
git commit -m "feat: define shared coaching contracts and worker boundaries"
$foundationCommit = git rev-parse HEAD
git worktree add -b feature/url-tutorial-coach .worktrees/url-tutorial-coach $foundationCommit
git worktree add -b feature/live-tutoring .worktrees/live-tutoring $foundationCommit
git worktree list --porcelain
```

Verify both worktree HEADs equal `$foundationCommit` before starting workers.
No need to recommit or copy existing memory files.

## Ownership and integration handoff

| Owner | Exclusive files and imports |
| --- | --- |
| URL worker | `curio-py/curio/tutorial_coach/`, `curio-py/tests/tutorial_coach/`, `docs/tutorial-coach/`; import `curio.tutorial_coach` |
| Tutoring worker | `curio-py/curio/live_tutoring/`, `curio-py/tests/live_tutoring/`, `docs/live-tutoring/`; import `curio.live_tutoring` |
| Integration | `app.py`, `companion_manager.py` (CompanionManager), config modules/files, `prompts.py`, tray wiring, shared UI shell, all dependency manifests/locks, `docs/ARCHITECTURE.md`, `docs/features.md`, `docs/PROGRESS.md`, `docs/RUNNING.md`, shared contract and its tests/docs |

Worker import locations above are reserved; feature packages do not yet exist.
Workers expose constructor-injected services and optional widget factories under
their own packages. Accept provider protocols, an event source and explicit
parent/dependencies; no global QApplication, tray registration, config mutation,
automatic capture or application startup on import. A widget factory should take
an injected feature service and optional Qt parent and return a QWidget. Document
its precise signature in the worker's docs. Integration performs application
wiring later. Workers must not modify integration-owned files or each other's
files. Propose shared contract/dependency changes in handoff notes instead.

## Data and correctness boundaries

All records except CancellationToken are frozen dataclasses using tuples for
collections. IDs are opaque nonempty strings assigned by the caller. Services
validate unique goal/step IDs and session/goal/work references at their ingress;
the records are an in-process boundary, not a deserializer for untrusted input.

- CoachingSession contains goals, optional tutorial steps and lifecycle status.
  Goal carries explicit success criteria. TutorialStep is an instruction with
  source attribution, never an assessment. There is no automatic progress counter.
- UserQuestion and SubmittedWork carry session and optional step IDs. Work is
  text and/or references to explicitly submitted artifacts, including intermediate
  work. New work gets a new ID; old evidence must not silently apply to revisions.
- CoachingReply carries the requested AssistanceLevel: hint, explanation or
  worked_example. Default feature behavior should request hint first; escalation
  is an explicit user choice. A worked example is teaching material, never proof
  that the student solved the problem. CoachingProvider does not return verdicts.
- VerificationProvider returns a separate StepAssessment for a particular work
  revision, optionally a step. Status is confirmed, incorrect,
  needs_clarification or unsupported. Ambiguity requires clarification; missing
  verification capability returns unsupported rather than a guessed verdict.
- Confirmed and incorrect require at least one source-backed observation or
  verifier result. Clicks, user claims and model claims alone are rejected by
  StepAssessment. Evidence provenance describes how something was observed;
  an LLM saying "verified" is still MODEL_CLAIM. Constructors cannot establish
  truth: the verifier must check actual work against criteria, relevance and
  freshness. Do not relabel model assertions as verifier results.
- SourceReference identifies a URL or opaque artifact plus a locator (page,
  timestamp, region, section or lines). Extraction and answers retain attribution.
  References confer no permission to fetch. Evidence stores a summary and source
  references, avoiding mandatory screenshot retention.

The existing click-to-advance walkthrough in CompanionManager stays unchanged.
A click can request a new capture or navigate; neither a click, a proposed step,
a STEP tag nor a model assertion establishes correctness. Explicit lifecycle
completion is not a claim of student mastery. Integration must only present a
verified-success message when relevant assessments support it.

## Providers and lifecycle

ContentExtractor.extract takes an authorized SourceReference and RequestContext
and returns attributed ExtractedContent. CoachingProvider.coach takes the session,
question, explicit assistance level, optional work/content and context.
VerificationProvider.assess takes session, submitted work and context. All are
async Protocols for fake/local/remote implementations. No provider is selected
or instantiated here. External content is untrusted data and cannot grant tool,
network, desktop-action or capture authority. URL policy, content limits, consent,
timeouts and credentials belong in injected adapters/integration.

Session transitions are created -> active/cancelled; active -> paused/completed/
cancelled/failed; paused -> active/cancelled/failed. Terminal states cannot resume;
restart creates a new session ID. Transition returns a new immutable snapshot.
Pausing stops ongoing work before another request; it is not proof of completion.

RequestContext carries session_id, unique request_id and a cooperative
CancellationToken. Adapters validate context IDs against inputs. Providers check
the token before and after awaited work and propagate OperationCancelled or
asyncio.CancelledError; genuine failures propagate exceptions for the service to
translate into UI-safe notifications. No automatic retry contract is imposed.
Session cancellation invalidates all pending requests, cancels their tokens and
asyncio tasks, releases owned resources and emits the terminal lifecycle event.
Closing widgets unsubscribes listeners; application shutdown awaits service
cleanup. These are service obligations, not background tasks created here.

## Events and Qt adapter obligations

CoachingEvents exposes subscribe_events and subscribe_notifications, returning
idempotent unsubscribe callbacks. Services emit CoachingEvent for session changes,
proposed steps, replies and assessments; notifications have stable codes, UI-safe
messages and severity info/warning/error. Pair SESSION_CHANGED with a session,
STEPS_PROPOSED or REPLY_READY with a reply, and ASSESSMENT_READY with an assessment.
Consumers must never treat STEPS_PROPOSED as ASSESSMENT_READY.

Every event/notification carries RequestContext. Services serialize delivery in
request order and isolate listener exceptions. Before applying results, consumers
check session ID, current request ID and cancellation state. A matching terminal
SESSION_CHANGED event must still be deliverable after token cancellation; drop
late provider replies/assessments. A new request cancels the old token and uses a
new request ID. This prevents old model results from replacing current work.

A Qt adapter marshals callbacks to the Qt event loop (queued signals when crossing
threads); providers cannot mutate widgets. Callbacks are synchronous, brief and
nonblocking. No Qt implementation or event bus is supplied in this contract.

## Meaningful checks

`tests/test_coaching_contract.py` checks that claims/clicks cannot establish
correctness even with references; verdicts need traceable observations; uncertain
assessments remain possible without proof; steps do not complete sessions;
terminal states cannot resume; snapshots remain unchanged; cancellation is
idempotent and raises at the provider boundary. Run from `curio-py`:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_coaching_contract -v
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check curio/coaching_contract.py tests/test_coaching_contract.py
```

The unittest command avoids requiring Qt for the shared contract checks. The
existing pytest suite uses the repository's offscreen QApplication fixture.

Verification in this session: four standalone contract checks passed; changed-file
Ruff passed; `git diff --check` passed. Existing suite plus contract checks passed
with `299 passed, 9 subtests passed` using
`--ignore=tests/test_tutorial_coach.py --ignore=tests/test_live_tutoring.py`.
Those two untracked tests and `curio/live_tutoring/` / `docs/live-tutoring.md`
appeared concurrently after initial inspection and were left untouched. The full
unfiltered suite failed collection because the concurrent tutorial test imports
`curio.tutorial_coach`, which does not exist. This is not a passing full-suite
claim. No feature files were included in the foundation. No terminals were opened
because the requested worktrees could not be created without the foundation
commit. `git worktree list --porcelain` still lists only the original main
checkout; neither requested branch exists.
