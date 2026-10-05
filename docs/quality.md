# Quality and coverage

Coverage is a release requirement and one part of correctness. A high percentage
does not establish correct Kubernetes semantics, responsive terminal behavior,
or reliable installation.

## Required gates

| Gate | Requirement |
| --- | --- |
| Production line coverage | At least 90%, measured independently |
| Production branch coverage | At least 90%, measured independently |
| Changed-line coverage | At least 90% against the PR merge base |
| Critical deterministic modules | 100% line and branch coverage |
| Lint and formatting | Ruff check and format check pass |
| Types | Strict mypy over application source passes |
| Behavioral tests | Applicable unit, UI, contract, and integration tests pass |
| Artifacts | Build, metadata validation, and clean-environment installation pass |
| Dependencies | No unresolved actionable high/critical vulnerability without a documented, time-bounded mitigation reviewed in the PR |

The current critical modules are the CLI/module entry points, preference schema
validation/precedence, diagnostic redaction, control escaping, literal text
presentation, argument validation/capture, client/UID target identity checks,
launch availability/exclusivity, shared access/command decisions, context catalogue
and session identity, resource endpoint/scope/alias/manifest normalization, and
watch events, UID state/replays and recovery decisions, plus active-view identity,
snapshot invalidation and freshness decisions.
Future critical modules include mutation guards, tool-specific command builders,
and resource-state transition/reconnect decisions. Keep those decisions separate
from transport and widget glue so exhaustive tests are practical. The critical
module list is maintained in `tool.kubetrol.coverage.critical_modules` in
pyproject.toml and changes with code review. Each listed file must exist, contain
executable code, and independently meet 100% lines and applicable branches.

Configure coverage over the entire src/kubetrol package, including modules not
imported by tests. Do not include tests in the denominator. Do not omit entire
UI, client, or subprocess modules. A combined coverage.py percentage is not the
independent line/branch gate: parse coverage JSON totals for each metric. Zero
branches are not a fabricated 100%; report them as not applicable. Empty
production source does not establish product coverage.

Use a 90% minimum changed-line gate with diff-cover. Exceptions for
unreachable or platform-specific lines require an explicit narrow justification;
the global line and branch floors remain unchanged. Do not add assertions that
merely mirror implementation details or blanket no-cover directives. No coverage
exclusions are currently approved: automatic line/partial-branch exclusions are
disabled, include/omit filters are rejected, and excluded lines fail the gate.
Introducing a narrowly justified exception requires a reviewed policy and gate
change; do not bypass the current checks with a pragma or command-line filter.

## Running the gates

```sh
uv run pytest --cov=kubetrol --cov-branch --cov-report=xml --cov-report=json
uv run python scripts/check_coverage.py coverage.json
uv run diff-cover coverage.xml --compare-branch origin/main --fail-under 90 --total-percent-float
```

`scripts/check_coverage.py` compares coverage.json's file inventory to every
Python file under src/kubetrol, including unimported namespace-package modules.
It rejects missing/extra files, inconsistent totals, missing branch evidence,
empty production source, and configuration that hides code. Floors use integer
counts rather than rounded display percentages. Tests and development scripts
are outside the application denominator; their regression tests still run in CI.

The application matrix runs Ruff, formatting, strict mypy for the application
and gate scripts, all behavioral/gate/artifact tests, coverage gates, builds, and
metadata validation on Linux/macOS and Python 3.12-3.14. Each matrix job applies
the same coverage requirements. CI fetches full Git history and uses the PR's
base commit, or the push event's previous commit, with diff-cover's merge-base
comparison. Only executable lines represented by coverage are counted; comments,
assets, and edits to non-executable continuations do not establish new coverage.
No changed executable lines means N/A. The negative-control tests verify 0%,
80%, the exact 90% boundary, a docs-only diff, and an unavailable base.

Coverage JSON/XML, changed-line JSON, actual UI SVGs, PTY transcripts/restoration
summaries and candidate distributions are retained
for seven days, including available evidence after failures. They are test
artifacts, not published release packages.

## GitHub merge checks

The stable required check names are **Quality gate**, **Repository checks**, and
**DCO**. Quality gate uses `always()` and requires the complete application matrix
to succeed; failure, cancellation, skip, missing dependencies, and invalid
results cannot pass. There are no path filters or allowed matrix failures.

While this repository is private on its current GitHub plan, GitHub rejects
branch-protection access with HTTP 403 and requires GitHub Pro. CI still executes
these checks, but it cannot technically block a maintainer from merging. The
temporary maintainer workflow is to inspect all three checks and every matrix
job on the current PR commit before a squash merge. This is manual verification,
not protected-branch enforcement; keep the repository private.

Once protection is available, configure those three checks as required with
strict/up-to-date status, enforce them for admins, require PRs and resolved
conversations, retain linear history, and prohibit force pushes/deletions.
Replace the old Bootstrap checks requirement with Quality gate and verify the
actual returned configuration. The maintainer accepted this temporary manual
workflow by merging PR #96 and authorizing continued private development on
2026-10-04. F02 is complete under that documented scope adjustment; automatic
enforcement must be enabled and verified before the first public release in
[D04 #40](https://github.com/carloshm91/kubetrol/issues/40). Repository visibility
changes still require the maintainer's explicit approval.
See [GitHub's protected-branch availability](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).

## Temporary private-development workflow when Actions is unavailable

On 2026-10-04, during PR #108, GitHub refused to start hosted jobs after the
maintainer exhausted the account's 2,000 included Actions minutes. The maintainer
explicitly authorized continuing private development and merging with measured
local checks while this quota/billing restriction remains. This authorization
takes precedence over the usual requirement for green hosted checks during this
temporary condition.

Before a merge, run the applicable full suite, independent line/branch/changed-line
and critical-module gates, lint/formatting, strict typing, build/metadata checks,
and relevant owned-cluster/PTY/install verification locally. Record the tested
commit/application tree, interpreter/platform, commands, counts and results in
the PR/issue. Record which hosted jobs did not run; Linux evidence does not
establish a new macOS result. Failed local checks still block delivery.

Keep the hosted workflows and their true failure status; never manufacture a
passing check or report blocked jobs as passed. Restore full platform CI when
the restriction is resolved, and qualify the full supported matrix before the
first public release. [Follow-up #109](https://github.com/carloshm91/kubetrol/issues/109)
tracks a less costly development matrix and trigger policy. Account budgets,
paid/persistent runners, repository visibility and publication remain separate
maintainer decisions.

## Test layers

- Unit: domain rules, typed sorting, quantities, validation, redaction, command
  arguments, transition logic, and retries with a controllable clock.
- Contract: a local fake Kubernetes HTTP/WebSocket server for pagination,
  list/watch continuity, 410, 403, disconnects, malformed payloads, and cancellation.
- UI: Textual Pilot tests for navigation, focus, keybindings, selection stability,
  details, modal dismissal, resizing, and error states. Add selected snapshots
  for meaningful layouts; do not replace behavior assertions with screenshots.
- Integration: isolated kind fixtures for real API behavior, container logs,
  exec, RBAC denial, and subsequently mutations/port-forward/CRDs. Every test
  owns its context and cleanup; never fall back to the user's active context.
- Terminal: real PTY/subprocess tests for handoff, Ctrl-C, window resizing,
  terminal restoration, process exit, SSH, and tmux. Headless tests cannot prove
  terminal restoration.
- Packaging: test the built wheel, source distribution, Homebrew formula, and
  later standalone artifacts in clean environments. Check help, version, missing
  kubeconfig, bundled assets, and a disposable-cluster smoke workflow.

The fast required PR suite covers every supported Python minor on Linux and
the declared macOS baseline. Cluster, PTY, and install checks are required for
changes affecting those paths; the release gate runs the complete matrix.
Use stable check names and a required aggregate quality-gate job that cannot
pass when a required dependency fails, is cancelled, or is incorrectly skipped.

## Performance evidence

Record the runner, terminal size, Python/dependency versions, dataset, and
measurement method. The initial qualification workload is 10,000 synthetic
resource rows, 100 resource events/second, and 2,000 log lines/second with a
10,000-line retained buffer. Target p95 input response below 100 ms on the
documented reference machine and a memory plateau during a 30-minute soak.
These are acceptance targets, not claims about current performance. Investigate
failures before changing the budget; preserve comparable benchmark results.

## Current repository stage

F01 provides the installable development CLI and behavioral/artifact tests.
F02 implements independent coverage, changed-line and critical-module gates,
negative controls, and the aggregate application matrix. Automatic protected-
branch enforcement remains unavailable under the current private-repository
plan, as recorded above. F03 adds local configuration, sanitized diagnostics and
temporary-file/process/artifact checks. B01 adds the real disconnected terminal
workspace, Pilot behavior tests, normal/compact geometry snapshots and real PTY
checks for resize, rapid command input, Unicode paste, quit and failure. Installed
wheel console/module launches also run in PTYs outside the checkout. Each matrix
job retains actual SVGs and terminal restoration evidence; SSH/tmux and cluster
qualification remain future work. F04 adds hostile text/argument and immutable
target tests, ambient credential traps for all test families, unsafe fixture
negative controls and a real isolated SDK configuration load without an API
connection. F05 stage 1 adds audited option/alias tests, a reviewed help snapshot,
service-level policy negative controls, visibility/initial-command Pilot evidence,
real PTY restoration and clean-installed launch contract checks. Reviewed help
snapshots preserve argparse's native alias formatting on Python 3.12 and 3.13/3.14.
C01 adds real loopback HTTP/TLS and synthetic exec-helper contract tests,
responsive context/namespace Pilot selectors and owned client/process cleanup.
Linux/Python 3.12 additionally requires disposable-kind namespace/TLS/client-auth
verification and retains sanitized cluster evidence. The deterministic catalogue,
connection-request and session-state modules join the critical 100% inventory.
C02 adds real HTTP discovery negotiation, consistent/expired pagination,
partial/forbidden groups, bounded snapshots and cancellation tests. The resource
domain joins the critical inventory. Disposable-kind verification additionally
requires core/named-group discovery and real paginated namespace/pod/deployment
snapshots with collection versions and item UIDs. The UI still has no resource
rows; live updates remain C03/C04/B02.
C03 adds pure critical watch-state/retry decisions and actual HTTP framing,
list/watch continuity, replay/recreation, retry/backoff, permission, token refresh,
bounded slow-consumer and cancellation tests. The required kind check exercises
a real write between LIST and WATCH plus create/update/delete/recreation and owned
watch/fixture cleanup. UI resource subscriptions remain C04/B02; C03 does not
establish a visible live pod table or maximum-workload performance.
Provider qualification, refresh and effectful integrations remain pending; a parsed flag is not
compatibility evidence. [Test isolation](security-primitives.md) describes the qualified
fixture path and limitations. The README must
never show an unmeasured coverage badge or imply that planned checks already run.

C04 adds bounded latest-state subscriptions, generation/client/scope rejection,
rapid switches, cancelled preparation/reconnect, late pages/callbacks and leak tests.
Its view domain joins the critical inventory. Pilot and PTYs verify stale/live/error
status and terminal restoration. The kind check adds actual namespace/resource
switches, client reopening and workspace exit cleanup. UI counts are available;
B02 still owns table rows and Q01 owns performance qualification.

Preview correction #107 adds no-bookmark idle streams, normal renewal/checkpoint
continuity and failed-establishment/timeout backoff regression tests. Pilot and
source/installed CLI PTYs verify the clearer live/count state and terminal cleanup;
the kind check requires two real quiet-watch renewals without stale status or relisting.

The PTY harness retains a shell-like session owner while the actual CLI process
runs. It records all terminal attributes immediately before/after that process,
using a separate completion pipe, before the session owner exits and macOS
[revokes access to the terminal](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/kern_exit.c#L2093).
The parent verifies both against the original PTY
mode and checks terminal control restoration in the actual output. Timeouts
terminate/kill the owned process group and close every descriptor.

## Sources

- [Coverage configuration](https://coverage.readthedocs.io/en/latest/config.html)
- [Textual testing](https://textual.textualize.io/guide/testing/)
