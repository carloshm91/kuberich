# Linux runner selection: #168

This checkpoint pins repository, application, release and Pages Linux jobs to
`ubuntu-24.04` before GitHub's announced `ubuntu-latest` OS migration. It keeps
all Python 3.12/3.13/3.14 jobs, native macOS baseline/full release qualification,
independent 90% line/branch/changed-line floors, 100% critical-module gates,
terminal/install/package checks, eleven owned-kind rehearsals and installed
quickstart. No application source or version changes.

## Contracts and negative controls

The planner selects Ubuntu 24.04 for each Linux interpreter. Every Linux setup
and owned-cluster condition uses the same host. Release qualification requires
completed successful native jobs, the planner, aggregate and Repository checks,
with matching requested runner labels. It selects only the retained
`quality-ubuntu-24.04-python-3.12` artifact. Candidate retries also require the
pinned validation host. Names, missing/failed/skipped jobs, duplicate/expired
artifacts, source/run identity and latest-attempt checks remain enforced.

Policy tests reject old/latest/Ubuntu 26/macOS host substitutions in otherwise
complete event matrices, successful jobs with missing/malformed/mismatched labels,
old Linux job/artifact names and unfinished jobs. Owned actual HTTP tests first
accept valid qualification, then reject stale labels or artifacts without writes.
The API shape was checked against actual Application quality run `37935217260`:
each job reports `status: completed` and a singleton requested label such as
`["ubuntu-latest"]` or `["macos-latest"]`. That historical run is preserved as-is;
it is not pinned-host qualification.

## Local verification

The isolated issue worktree starts at `b92dbe4`, including the #166 Pages workflow
and prerequisite macOS corrections. The exact focused command is:

```sh
uv run --locked --python 3.12 pytest tests/quality/test_ci_policy.py tests/quality/test_quality_gate.py tests/quality/test_release_policy.py tests/quality/test_release_transport.py tests/quality/test_site.py tests/quality/test_pages.py -q
```

On 2026-10-09, **290 passed in 57.10 seconds** on local Ubuntu 24.04.3 LTS,
x86_64, kernel 6.8.0-142-generic, CPython 3.12.12. The initial run had a new
test-selector error (it included the mypy step as a cluster rehearsal); selecting
actual `python -m scripts.verify` invocations fixed that assertion, and the complete
focused cohort above then passed. No required check was suppressed or skipped.

These commands also passed:

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict scripts/ci_policy.py scripts/release_policy.py scripts/check_quality_gate.py scripts/release.py scripts/build_site.py scripts/check_site.py scripts/site_reference.py scripts/pages.py
python3 scripts/validate_plan.py
git diff --check
uv build
uv run twine check dist/*
uv run python -m scripts.build_site
uv run python -m scripts.check_site
mkdir -p artifacts/site-qa
cp website/qa/package.json website/qa/package-lock.json artifacts/site-qa/
npm ci --prefix artifacts/site-qa --ignore-scripts
npm audit --prefix artifacts/site-qa --audit-level=low --json
node scripts/verify_site_browser.mjs
```

Strict mypy also passed the complete application-quality workflow file list plus
the four website builder/checker/reference/Pages modules: **128 source files**.
Ruff formatted inventory: **429 files**. Planning validates 12 epics, 79 tasks,
64 capability families and 26 CLI flags. Wheel/sdist metadata passed. Both site
surfaces contain **49 pages, 1,722 checked local links/assets and 64 files**.
Chrome 143.0.7499.169, locked Playwright 1.64.0 and axe 4.14.0 checked all 49 pages
at desktop/mobile sizes with zero violations, no external requests or browser
failures, plus keyboard/menu/copy-denial/no-JavaScript behavior. npm audit found
zero vulnerabilities. Local reports/screenshots remain under `artifacts/site-qa`;
no site publication was performed.

Application source tree remains `d87d8acef7728caffdcfc7c037767b1003427be2` from
base `b92dbe4`. Changed executable application coverage is N/A for this policy-only
diff; application coverage/platform gates still run in every selected hosted
native job. Final commit/hosted evidence will be retained in the issue/PR.

## Hosted qualification and limits

The candidate was rebased onto main `0cfa7153bd8617c3ece3f5641d5b7e539b497ae4`
after #166's source PR #167 merged with all exact-head checks passing. That main
has the same Git tree as the original `b92dbe4` base. Pinned-host PR/native gates
and the migration-warning check remain pending until the new hosted jobs finish.
Local policy checks do not establish hosted native or Ubuntu 26.04 qualification.
The PR/issue must retain final-head required-check results and artifacts before
squash merge. No release, package, tag, DNS, visibility or website publication
is performed by this task.

Selecting Ubuntu 24.04 pins the OS release, not GitHub's hosted image revision,
kernel or apt packages. Retain actual image/tool versions in new qualification
evidence. Original `ubuntu-latest` receipts keep their historical labels/digests;
Ubuntu 26.04 requires separate future evidence before changing the current
contract. This CI choice does not narrow the application's Linux support policy.
