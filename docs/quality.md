# Quality and coverage

Coverage cannot guarantee behavior, cleanup or installation; report measured results and gaps.
The 0.3 gate follows functional readiness; deferred architecture/performance goals
stay visible for stable work. Coverage, security, ownership and cleanup stay mandatory.

## Required gates

| Gate | Requirement |
| --- | --- |
| Production lines | At least 90%, independently measured |
| Production branches | At least 90%, independently measured |
| Changed executable lines | At least 90% against the event merge base |
| Critical deterministic modules | 100% lines and applicable branches per module |
| Static checks | Ruff check, format check and strict mypy |
| Behavior | Applicable unit, contract, UI, terminal, integration and quality tests |
| Artifacts | Build, metadata, payload, rebuild and clean-install checks |
| Dependencies | Audits, SBOMs, licenses and exact artifact/source bindings |

[pyproject.toml](../pyproject.toml) lists `tool.kuberich.coverage.critical_modules`.
Gates cover every `src/kuberich` Python file, including unimported modules; tests
and development scripts are excluded. Missing/extra files, inconsistent totals or
missing branch evidence fail. Counts are integers, not rounded; zero branches mean N/A.

No exclusions are approved: automatic line/partial-branch exclusions, include/omit
filters and excluded lines fail. A narrow exception needs reviewed policy/gate
changes, not a pragma or CLI filter. No changed production executable lines means
N/A, not a new 100% result.

## Running the gates

Use [explicit source-history setup](../CONTRIBUTING.md#toolchain) first.
`uv run python scripts/qualify.py 0.3.0` runs the actual strict target union,
private-access/startup stages, full suite and existing gates; see
[phase verification](releases.md#reproduce-phase-verification). Individual tools:

```sh
uv sync --locked --group dev
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict src/kuberich scripts/check_coverage.py scripts/check_quality_gate.py
uv run pytest --cov=kuberich --cov-branch --cov-report=xml --cov-report=json
uv run python -m scripts.merge_runtime_coverage
uv run python scripts/check_coverage.py coverage.json
uv run diff-cover coverage.xml --compare-branch origin/main --fail-under 90 --total-percent-float
uv build
uv run twine check dist/*
```

Fetch the base first: CI uses the exact event base with diff-cover's merge-base comparison.
Local staged/unstaged executable changes count. The [gate](../scripts/check_coverage.py)
independently verifies the full inventory and line/branch floors; combined percentages are insufficient.

### Test layers and local parallel runs

Directory markers are `unit`, `contract`, `ui`, `terminal`, `packaging` and
`quality`. `fast` selects every unit/contract/UI case, including slow cases.
The registered `kind` marker is not a substitute for real cluster verifiers.

```sh
uv run pytest tests/unit tests/contract tests/ui -m fast -n 12
uv run pytest -m terminal -n 4
uv run pytest -n 6 --cov=kuberich --cov-branch --cov-report=xml --cov-report=json
```

Use fewer workers on smaller hosts or `-n 0` for serial execution. Default
loadgroup scheduling keeps shared evidence fixtures together; worker restarts
are disabled. Crashes and failed tests fail the run. Workers get separate pytest
temporary directories and ephemeral API ports; coordinate separate commands so
one run cannot delete another's retained temporary files or artifacts.

Backend/UI runtime children, including the branch-traced UI replay, take an
exclusive controller lock through setup and cleanup. Other tests drain and
resume afterward. Tracing still does not qualify runtime latency. Separate
pytest commands have separate locks, so coordinate host-wide timing windows.
Every fast run keeps the full positive and deliberate negative runtime controls.
Coverage runs additionally require the instrumented replay; fast-only receipts
cannot satisfy the full coverage gate.

### Parallel test parts

Each source environment has four CI parts, each with two xdist workers. Whole
files and shared-evidence groups remain together. Timing data lives in
[part_timings.json](../tests/support/part_timings.json); unknown files use ten seconds.

```sh
KUBERICH_TEST_PART=2/4 uv run pytest --cov=kuberich --cov-branch --cov-report=
```

The Application job combines all four parts with `scripts/combine_test_parts.py`.
Missing parts/coverage, symbolic links or conflicting evidence bytes fail.
The runtime merge then verifies exact source/nonce receipts, both timing controls,
the successful branch-covered replay and the exact per-file arc union before
regenerating coverage JSON/XML. It preserves the parent reports and merge receipt;
missing, stale or tampered evidence cannot satisfy any floor.
Refresh timing data from a complete JUnit run with `uv run python -m scripts.part_timings junit.xml`.

## GitHub merge checks

Required names are **Quality gate**, **Repository checks** and **DCO**. The
aggregate runs with `always()` and requires the actual event/ref planner, every
part and every selected source/native job. Missing, failed, cancelled, skipped
or malformed dependencies cannot pass. No path filters or allowed failures apply.

| Event | Source environments |
| --- | --- |
| Pull request, including docs | Linux Python 3.12/3.13/3.14; macOS Python 3.12 |
| Main push | Linux Python 3.12/3.13/3.14 |
| Manual Application quality on main | Linux and macOS Python 3.12/3.13/3.14 |

The complete fast selection runs first on Linux 3.12; failure blocks matrices and
fails the aggregate. Success replaces no complete suite, coverage, build or audit.
Linux source jobs use `ubuntu-24.04`; the source macOS matrix uses the explicit
`macos-15` Apple Silicon image. Source Python versions and all four test parts
remain unchanged.
Native Apple Silicon build/install lanes use `macos-15`; Intel uses `macos-15-intel`.
New Apple Silicon bottles use `arm64_sequoia`; published Sonoma metadata stays
readable. Require actual new-image results before claiming native qualification.

Repository checks validate planning, links, generated references, both site surfaces
and digests, strict builder types, browser keyboard/accessibility/copy and no-JavaScript.
Locked Node/browser tools are development-only. Retain coverage, changed-line, UI,
PTY/restoration and package artifacts, including failures, for seven days; they are not releases.

Main requires PRs, resolved conversations, admin enforcement and linear history;
force pushes/deletions stay disabled and checks stay bound to their expected apps.
Solo delivery needs no second reviewer when protection permits. Both release
environments still require owner review, protected branches and no admin bypass.
Revalidate live rules before publication through the [release procedure](releases.md).

### Temporary private-development workflow when Actions is unavailable

Hosted checks remain required; historical quota exceptions grant no current waiver.
An explicit local-only exception records its blocker, source, commands/results and
unavailable platforms, preserving failures; local evidence never becomes hosted,
native, provider or public-release qualification.

## Test layers

Test observable behavior and controlled faults, disclose platform/provider gaps,
and avoid implementation mirrors or empty repetition.

- Unit: pure validation, sorting, redaction, literal arguments and transitions.
- Contract: real local HTTP/WebSocket responses, pagination, 403/410, reconnect,
  malformed frames, credential refresh, cancellation and slow consumers.
- UI: Pilot navigation, focus, scope, stable selection, errors, resize and geometry;
  screenshots never replace behavioral assertions.
- Terminal: source and installed PTYs, Unicode, resize, Ctrl-C, handoff, SSH/tmux,
  connection loss, exact terminal attributes, child reaping and descendant cleanup.
- Packaging: complete wheel/sdist payload, private-file traps, rebuild equivalence,
  isolated uv/pipx installs, installed CLI/UI/shell behavior and real upgrades.
- Integration: owned disposable kind clusters, actual effects, permissions, logs,
  exec, forwarding and custom resources. Preserve and never fall back to an ambient context.

Writes require captured UID/version/scope, read-only checks and confirmation.
Test conflicts, denied access, stale identities, cancellation and ambiguous outcomes
without blind retries. Streams/processes need startup/EOF/error, repeated-stop,
listener/private-file cleanup and actual terminal restoration scenarios.
Keep authentication/helper contracts distinct from opt-in real-cloud trials.
The [integration guide](integration-testing.md) lists pinned prerequisites,
ownership verification, sequential cluster commands and signal-cleanup controls.

Tests use Pilot or public `app.run_command(text)` and frozen `app.state` observations.
Run `uv run python scripts/check_private_access.py`: private access into any KubeRich
namespace from tests or embedded programs fails. Test fakes/framework objects keep
their own boundaries. Numeric diagnostics never replace actual cleanup/UID/scope checks.

## Startup and import boundaries

Run `uv run python -m scripts.check_startup --output NEW_PATH` serially on frozen
source. Keep five fresh samples per offline command, four import profiles and
five actual frames on an owned 120×36 PTY; never omit an advisory miss.

All startup latency is advisory for 0.x: offline wall time 150 ms, aggregate self
and maximum cumulative import time 150,000 µs, and actual UI first paint 600 ms.
Keep actual values, original targets, `budget_met` and `budget_enforced`.
`--strict-startup` enforces every original limit; `--strict-paint` stays UI-only.
Actual source major 1+, including prereleases, always enforces all timing limits;
no version override or higher substitute threshold can downgrade them.

RSS below 40,000,000 bytes, valid observations/output/source identity, complete
profiles and absence of terminal/SDK imports stay hard. Require a real mounted
selected table, columns and geometry inside the original viewport before
SDK/helper/network work. Deadlines, ownership, cleanup and restoration stay hard.
Keep the original strict 700 ms late-frame and forbidden-import negative controls,
plus strict offline/import, stable-prerelease, RSS and functional controls.
Old-policy failures remain failed; supplemental diagnostics do not replace them.

Prepare the SDK only after the public refresh-readiness port; retain eager tables,
pre-readiness quit/cancellation and read-only navigation. Preserve stdout/stderr,
import profiles, ANSI and failures. Source evidence does not qualify another
platform or native artifact. See [startup history](internal/acceptance/startup-budget-0.3.md).

## Property and mutation testing

Run `uv run pytest tests/unit/property`; the weekly/manual mutation campaign targets
85% actual kills. Its initial 84.971693% misses that advisory target; survivors,
incomplete/tool failures and raw counts stay in [the record](internal/acceptance/property-mutation-tests.md).
Coverage gates and failure reporting remain unchanged.

## Performance evidence

Time the original workload without coverage, tracing, profiling, GC tuning or competing
checks. Freeze inputs; retain machine/interpreter/dependency, viewport/dataset/observer
identities and raw samples. Select alternate interpreters explicitly.
For 0.x, runtime/collection heartbeat and input latency is advisory against the
original 150 ms limit. `KUBERICH_STRICT_RUNTIME_BUDGETS=1` enforces it; actual
major 1+, including prereleases, always enforces it and cannot opt out with `0`.
Retain every measured miss; the deliberate 200 ms controls stay strict. Every
functional assertion, memory/retention/source/output bound, deadline, ownership,
cleanup and coverage gate stays hard. Diagnostics never replace original failures.

The real-CLI workload uses 10,000 resource rows, 100 resource events/second and
2,000 log lines/second with 10,000 retained lines. Its reference p95 input target
is below 100 ms; evaluate memory over a 30-minute soak, not a short demonstration.
Use `uv run python -m tests.support.performance_terminal --seconds 1800 --output NEW_PATH`.
After ten warmup minutes, review four five-minute windows with at least 54 samples.
For app/source/observer RSS, ranges of window medians and p95s stay within the
larger of 8 MiB or 5% of the minimum median; descriptor range is at most two and
thread count stays constant. Preserve failures and investigate before changing limits.

The complementary `tests/contract/test_performance_lifecycle.py` keeps three warmup
and 36 measured cycles with constant drained descriptor/thread/task counts.
Held-resource controls must detect added resources. It measures cleanup, not
latency or RSS, and does not replace actual-kind or sustained-CLI observations.

## Artifacts and release qualification

Use fresh outside-checkout environments/tool state, explicit no-cluster configuration
and actual index/dependency prerequisites. Verify complete bundles, ABI/deployment floors,
licenses, certificates, interpreter isolation and source/installed/native terminal behavior.
Audits and strict CycloneDX bind exact artifacts/locks. Scanner errors, missing evidence
or unreviewed/expired exceptions fail. High/critical findings need exact reviewed expiring
mitigations; never omit findings. See [dependency security](dependency-security.md) and [Homebrew](homebrew.md).

A release needs the exact main source's latest successful manual six-environment
Application run, all four native targets and their original retained artifacts.
A later failed attempt blocks an older success. Development PR/main matrices do
not substitute for release qualification. Promised native Homebrew install/upgrade/
removal and bottle lanes require their own real supported-host results.
Repeat release contracts and owned-kind trials three times with separate artifacts;
these do not replace performance, provider or installation qualification.
Follow cumulative phase readiness, exact authored notes, source/artifact digests,
protected owner review and approved channels in [releases.md](releases.md).
Evidence preparation does not publish tags, packages, websites or DNS changes.

## Failure records and historical evidence

Keep original failures, logs, source identity and cleanup outcomes. Never hide cleanup
failure with longer deadlines, skipped assertions or success receipts. Supplemental
controls are not exact qualification; an unchanged retry is not a correction.
Historical reports stay in `docs/internal/`, apart from user guides; local fakes
cannot establish cloud compatibility.
