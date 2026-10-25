$ErrorActionPreference = 'Stop'
$files = @(
  'tests/readiness/test_demo_journey.py',
  'scripts/readiness/demo/run_checks.py',
  'scripts/readiness/demo/windows_smoke.py',
  'scripts/readiness/demo/commit-owned.ps1',
  'docs/readiness/demo/criteria.md',
  'docs/readiness/demo/demo-script.md',
  'docs/readiness/demo/fallback-demo.md',
  'docs/readiness/demo/defects.md',
  'docs/readiness/demo/handoff.md',
  'docs/readiness/demo/check-results.txt',
  'docs/readiness/demo/native-smoke.txt',
  'docs/readiness/demo/windows-smoke.json',
  'docs/readiness/demo/provider-smoke.txt',
  'docs/readiness/demo/seeded-offscreen-tutor.png'
)
# Invoke from the repository root after reviewing these files.
# Refuse to include another workstream's already staged changes.
$staged = @(git diff --cached --name-only)
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect Git index' }
if ($staged.Count -gt 0) { throw 'Index already contains staged changes; review separately' }
git add -- @files
if ($LASTEXITCODE -ne 0) { throw 'Staging failed' }
git diff --cached --stat
git commit -m 'Add reproducible demo reliability checks and evidence'
if ($LASTEXITCODE -ne 0) { throw 'Commit failed' }
git rev-parse HEAD
