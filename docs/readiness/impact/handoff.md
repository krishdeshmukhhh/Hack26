# Impact workstream handoff

USER VALIDATION PENDING. No participants, testimonials or product findings exist
in this delivery. No recruitment, external transmission, push or publication
was performed. Reviewed checkout baseline: integration snapshot;
other workstreams had uncommitted changes. Prepared 2026-10-24.

## Ready materials

Use study-plan.md as the authoritative protocol, facilitator-checklist.md for
execution, participant-instructions.md as separately revealed goal cards,
interview-and-consent.md for private consent preparation, and blank-results.csv
for a private copy of results. session-template.md remains useful for setup
provenance. protocol.md and observations-template.csv are earlier generic drafts;
do not mix their schema/statuses with this pilot. summarize.py is the legacy
analyzer; use analyze.py for this plan. No actual data was supplied for analysis.

The pilot selects LibreOffice Calc: numeric threshold and text equality
conditional-formatting tasks, four task/condition sequences, independent rule
and saved-file verification, ten-minute limits, mandatory unassisted transfer,
ratings, event counting and neutral interviews. Comparator resources are defined
explicitly. Transfer after both conditions cannot isolate Curio learning.

## Checks performed

From repository root, using the existing interpreter and Ruff installation:

```powershell
.\curio-py\.venv\Scripts\python.exe -B scripts/readiness/impact/check_analysis.py
.\curio-py\.venv\Scripts\python.exe -B scripts/readiness/impact/analyze.py docs/readiness/impact/blank-results.csv
.\curio-py\.venv\Scripts\python.exe -B scripts/readiness/impact/analyze.py scripts/readiness/impact/synthetic-fixtures/SYNTHETIC-mixed.csv --synthetic
.\curio-py\.venv\Scripts\ruff.exe check scripts/readiness/impact/analyze.py scripts/readiness/impact/check_analysis.py --config curio-py/pyproject.toml
```

Three unittest methods cover mixed outcomes, missing durations/counts/ratings,
empty data, tiny/incomplete samples, successful-pair selection, provenance hash,
duplicate rows, invalid ranges/nonfinite values, inconsistent timeouts, bad
headers and rejection of synthetic IDs in ordinary mode. Synthetic CSV fixtures
are stored separately under scripts/readiness/impact/synthetic-fixtures and
explicitly labeled. Temporary malformed cases derive only from those fixtures.
Blank input reports zero observed participants. No dependency installation or
production/test-suite changes are required. This validates the analyzer, not
Curio efficacy. Automated checks cannot validate task comparability or live
Calc/model behavior.

Analyzer reads locally and prints JSON; it never changes input. Reports absolute
input path and byte SHA-256; preserve original raw file, protocol revision,
collection dates, consent status, setup and transformations privately. Notes are
not echoed, but paths and pseudonyms can still be identifying: keep output
private. Missing values stay missing; unsuccessful runs remain in denominators;
completion-only time and pairs are explicitly selected. No significance tests,
productivity percentages, imputation or population extrapolation are generated.
Missing intervention count is visible in metric denominators; do not interpret
intervened_runs alone as evidence of no assistance. Allocation adherence still
requires facilitator review against assigned sequence and private event notes.

## Human work required before and with participants

1. Appoint study owner/data custodian; verify actual Calc version and model
   availability; build clean .ods assets, hash them, rehearse scoring/persistence
   and timing, freeze protocol/config. If unequal difficulty is gross, revise
   before recruitment; no live feasibility has been established by this delivery.
2. Resolve venue review, service processing/retention disclosures, private storage,
   withdrawal contact/deadline and deletion responsibilities before consent.
3. With authorization, recruit 6?10 eligible adult learners, aim for eight for
   balanced blocks; assign in sequence, administer all tasks and transfer, retain
   failures/interventions and optional ratings without coaching.
4. Analyze only consented private data, preserve provenance and dropout reasons,
   audit result correctness and task/order imbalance, report actual denominators
   and limitations. Keep signatures, names, recordings, participant rows and
   linkage out of Git. Honor withdrawal and scheduled deletion.

## Unsupported claims

All Curio improvement claims remain unsupported: faster/more correct work,
fewer errors or switches, lower effort/frustration, greater independence,
learning/mastery/retention, accessibility, adoption, willingness to pay and
market demand. Research on other tools and technical tests are not user outcomes.
A small convenience pilot can describe observed feasibility and failure modes;
it cannot justify generalized efficacy or causal learning claims. Animated-pet
benefit, superiority over other screen-aware assistants, scam prevention and
first-of-kind claims also remain unsupported by this workstream.

## Commit limitation

Attempted to stage only the two owned directories. Git refused to create
.git/index.lock with Permission denied under this session's permissions; no
commit hash exists for this delivery. No push or publication was attempted.
After reviewing the owned files, a teammate with Git write access must run:

```powershell
git add -- docs/readiness/impact scripts/readiness/impact
git commit -m "Prepare executable learner impact pilot"
```

Review the index first if other workstreams have staged changes; commit only
these owned paths. Do not include unrelated work or participant data.
