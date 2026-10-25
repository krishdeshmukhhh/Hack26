# Coordinator review of the four updated handoffs

2026-10-24. Common baseline remains integration snapshot.
Existing dirty work from the first readiness pass was preserved. This review
supersedes first-pass counts and limitations where explicitly stated below.
No cached patch was applied: integrity changes already existed in the working
tree. Applying changes.patch again would duplicate changes or stage stale versions.

## Sequential review

1. Product: reviewed six documents, proposition/next-encounter angle, comparisons,
   research limits and historical stories. Retained unsupported-claim boundaries.
   Documentation comparison is not competitor use or product efficacy evidence.
2. Integrity: reviewed event/skill/task-map/sync/dashboard diffs and regression
   tests. Accepted conservative provenance migration, final-attempt contradiction
   guard, estimate wording and seed isolation. Replaced temporary EvidenceStepEvent
   subclass with shared StepEvent fields plus a compatibility alias.
3. Impact: reviewed Calc protocol, goal cards, consent/scoring templates, blank
   CSV, analyzer, synthetic fixtures and checks. study-plan.md / blank-results.csv /
   analyze.py are authoritative; earlier generic templates are separate drafts.
4. Demo: reviewed journey/recovery tests, runners, smoke scripts, reports and
   capture. Real components use scripted perception/audio/model events. Native
   SAPI recorded 8 access-denied failures; localhost provider discovery timed out.
   Device enumeration found 25 devices but Qt exposed 0 voices. These are open
   environment blockers, not proven algorithmic defects or successful live checks.

## Coordinator integration

- Shared StepEvent: explicit evidence basis, local opaque result reference and
  synthetic flag. Matching checked outcome/reference required. Validation checks
  record consistency, not whether an arbitrary adapter actually checked work.
- WalkthroughSummary: completed_basis/synthetic; CompanionManager explicitly
  propagates model-inferred completion. Clicks are navigation only. No generic
  desktop verifier or user-confirmation UI was invented. Tutorial user confirmation
  and bounded exact math retain separate existing authority.
- Event schema 3, skill schema 2, path schema 2: migrate missing fields to
  unknown/unmarked and retain records/counts/estimates. TaskPath.report_count is
  a compatibility alias, never a new verified-success metric. Path basis persists.
- Local result references and checked bases never cross sync. Optional v1
  synthetic marking requires updated server before seeding; default sync filters
  marked demo data. Historical unmarked seed data cannot be recovered as genuine.
- Skills demo evidence has durable synthetic markers, including in export and
  after restart; mixed histories show a visible warning. Existing estimates are
  not recalculated and old unmarked demo history cannot be reliably identified.
- New marked synthetic summaries cannot reinforce ordinary local task paths.
  Unknown historical counters are never upgraded to independent verification.
- Dashboard synthetic inclusion uses exact query parsing, not substring matching.
- Removed outdated isolated-startup claim from live-tutoring.md and aligned the
  four main docs plus task-map/map-sync/skills docs.
- Original seeded Qt image contained unreadable missing-font glyphs. Coordinator
  loaded an explicit Segoe UI font, inserted an on-image seeded-exhibit label,
  regenerated and visually inspected the readable capture. It is not live footage.

## Verification

New coordinator regression tests first failed for missing shared provenance,
report_count and durable skill markers, then passed after integration. They cover
event store round-trip, model-completion origin, no exported local references,
untrusted remote verification claims, synthetic/legacy migration, persisted
path basis, synthetic path exclusion and the reopened Skills warning.
Fresh full app/root checks and analyzer results are recorded in the readiness
register and PROGRESS.md after the final run; worker counts are not summed.

Git refs/index remain permission-blocked; no worker or integration commit exists.
The initial four detached worktree paths remain in hackathon-readiness.md. No
merge, deployment, push, publication or submission occurred. Commit helpers and
changes.patch are historical handoff aids, not proof that anything was committed.

## Open live checks

Run in the actual interactive Windows session: speech/microphone access, installed
recognizer/voices, audible playback, hotkey/Escape/recovery, configured model/tunnel,
model grounding and adherence, projector/DPI, packaged startup/shutdown, physical
two-laptop sharing and genuine backup recording. Do not change machine permission
policy automatically. Human learner/competitor trials remain unperformed.
