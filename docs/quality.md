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

The initial launch site in #150 also runs build/link/digest checks, strict builder
types and real Chrome keyboard/accessibility/copy/no-JavaScript checks under
Repository checks. Its Node 20+/Chrome and locked Playwright/axe tools are developer
verification prerequisites, outside the application/runtime dependency contract.
Generated local evidence and node_modules are not repository planning sources.
Site-only delivery reports changed executable application coverage as N/A;
it preserves every application coverage gate and the latest qualified source tree.

The current critical modules are the CLI/module entry points, preference schema
validation/precedence, diagnostic redaction, control escaping, literal text
presentation, argument validation/capture, client/UID target identity checks,
launch availability/exclusivity, shared access/command decisions, context catalogue
and session identity, resource endpoint/scope/alias/manifest normalization, and
watch events, UID state/replays and recovery decisions, plus active-view identity,
snapshot invalidation and freshness decisions, plus pod health, typed ordering,
inspection redaction/search, log query/framing/retention, and retained log identities,
window selection, start-time validation and clipboard bounds, plus immutable
process/environment capture, scoped kubectl/editor builders and exit decisions,
plus shell target validation and sanitized return decisions, plus bounded terminal
geometry and keyboard/paste encoding. Namespace UID/lifecycle values in
`domain/namespaces.py` join the critical inventory in #125; shared workspace
layout receives Pilot and real-terminal checks.
Captured container specification/status decisions in `domain/containers.py`
join the critical 100% line/branch inventory in #129.
Standard resource summary, quantity and ordering decisions in
`domain/registry.py` join that inventory in B05 #41. Every advertised family
receives parameterized column contracts, actual HTTP/Pilot LIST/WATCH/GET tests
and owned-kind watch updates/individual reads through `scripts.standard_kind`.
S05 #42 adds bounded numeric TCP intent, bind validation, scoped argv, target
UID/phase and observed readiness decisions in `domain/port_forwards.py` to the
critical inventory. Real child/socket, Pilot, source/fresh-install PTYs and
`scripts.verify_port_forwards_kind` qualify forwarding, cancellation and cleanup.
The Linux/Python 3.12 job requires real owned Pod/Service HTTP transport; pinned
images/binaries and the shared kind owner protect caller configuration.
M01 #43 adds immutable mutation intent, patch/precondition, annotation and outcome
decisions in `domain/mutations.py` to the 100% critical inventory. Actual HTTP/TLS
faults, repeated cancellation, Pilot and source/fresh-install PTYs qualify guards
and confirmation; `scripts.verify_mutations_kind` is required on Linux/Python 3.12
for actual writes, stale UID/version refusal and server RBAC on an owned cluster.
M02 #44 adds editor argv, bounded JSON-compatible YAML, immutable identity and
structural diff decisions in `domain/editing.py` to the critical 100% inventory.
Actual private files, held workers/reads, loopback HTTP/TLS, Pilot and source/fresh
wheel PTYs qualify editor failure/cancellation, default Cancel and distinct
dry-run/Apply. `scripts.verify_editing_kind` is required on Linux/Python 3.12 for
actual strict dry-run, guarded edits, conflict/replacement refusal and patch RBAC.
M03 #45 adds workload applicability, counts, restart/history and observed rollout
decisions in `domain/workloads.py` to the critical 100% inventory. HTTP/TLS,
Pilot and source/fresh-wheel terminal contracts complement required Linux/Python
3.12 `scripts.verify_workloads_kind` Deployment and ControllerRevision operations,
HPA, scale-only RBAC, failed progress and monitoring cancellation.
M04 #46 adds deletion options, immutable create/delete requests and Job suspension
decisions in `domain/operations.py` to the critical 100% inventory. Required
Linux/Python 3.12 `scripts.verify_operations_kind` checks real deletion policies,
finalizers, mixed RBAC batches, replacement/version refusal, Job/CronJob
suspension, manual execution and duplicate prevention. HTTP/TLS disconnects
must prove a single DELETE attempt; Pilot/source/fresh-wheel PTYs cover exact
selection/count, default Cancel, partial results and lifecycle ownership.
S07 #48 adds running-process attach and literal transfer/path/probe decisions in
`domain/attach.py` and `domain/transfers.py` to the critical 100% inventory.
Actual files, controlled HTTP/executables, held-worker and repeated-cancellation
contracts, Pilot and source/fresh-wheel PTYs qualify private staging, default
Cancel, overwrite, tar/archive limits and cancellation-before/after-publication.
Required Linux/Python 3.12 `scripts.verify_transfers_kind` checks actual regular,
init and ephemeral round trips, 8 MiB streams, directories, missing tar,
interrupted uploads/downloads and native attach/restore on an owned cluster.
The source kubeconfig and caller context remain unchanged.

F05 invocation overrides and bounded impersonation decisions in
`domain/connection_overrides.py` join the critical inventory in #19.
Fixed provider diagnostic decisions in `domain/credential_helpers.py` join the
critical 100% line/branch inventory in C06 #21. Synthetic provider contracts,
responsive Pilot navigation and the owned-kind AWS-shaped helper qualify local
behavior; real EKS evidence remains a separate explicit test-context requirement.
C07 extends that same critical module with Azure mode/prompt/error and bounded
bearer decisions. Native provider handoff also receives actual PTY and fresh-wheel
checks for private stdout, declared stdin, Ctrl+C/cancel/SIGTERM and restoration.
C05 #52 adds immutable bounded Table decoding in `domain/tables.py` to the
critical 100% line/branch inventory. Real HTTP contracts cover generic GET,
paged Table/JSON fallback, per-GVR negotiation, permission/error identity,
renewed watches and repeatedly cancelled parser workers. The required Linux
3.12 `scripts.verify_custom_resources_kind` checks real CRDs of both scopes,
server columns/full objects, versions, alias collisions, install/remove refresh
and actual restricted RBAC. Its receipt labels forced legacy/plain-JSON
representations supplied by an owned loopback gateway; status denials are actual
cluster responses. Visible generic custom-resource UI remains B06 #53.
C08 adds bounded credential-response validation and captured proxy/TLS decisions
in `domain/exec_credentials.py` and `domain/proxies.py` to the 100% critical
inventory. Real token-file/certificate renewal, HTTP CONNECT and SOCKS5 contracts
complement generic source/fresh-wheel native login. The required Linux/Python
3.12 `scripts.verify_credential_interop_kind` checks merged configs, relative TLS,
exec certificate/token helpers, logs, real kubectl exec/forwards and private-file
cleanup through an owned HTTP proxy. Real GKE/OIDC/provider certification remains
opt-in Q05 #87; future Helm operations remain #66.
Q02 adds mandatory owned loopback SSH, isolated tmux and SSH-to-tmux trials for
workspace/log navigation, native handoff and embedded shells. The suite requires
OpenSSH client/keygen/server and tmux; missing prerequisites fail explicitly.
Linux runners install openssh-server/tmux and prepare `/run/sshd`; macOS runners
install tmux and require their existing `/usr/sbin/sshd`. No developer system
daemon or user configuration is changed. See
[terminal compatibility](terminal-compatibility.md) for commands, ownership,
lost-connection evidence and outstanding macOS/manual qualification.

D01 requires complete wheel/sdist payload and metadata checks, private-file traps,
sdist-to-wheel equivalence and actual isolated uv tool/pip-backed pipx installs.
Each interpreter runs installed CLI/navigation/shell trials outside the checkout.
Installer evidence is retained under `artifacts/packaging`; installed dependencies
are measured independently of the development lock. Tool subprocesses own their
process group and reap children on timeout. Application jobs allow 45 minutes
for the measured full suite, cold pip-backed installs and owned cluster checks,
including the setup/body cancellation qualification added in Q01 #38.

Future critical modules include mutation guards, tool-specific command builders,
and resource-state transition/reconnect decisions. Keep those decisions separate
from transport and widget glue so exhaustive tests are practical. The critical
module list is maintained in `tool.kuberich.coverage.critical_modules` in
pyproject.toml and changes with code review. Each listed file must exist, contain
executable code, and independently meet 100% lines and applicable branches.

Q04 #35 audits isolated locked/fresh installed runtimes, validates CycloneDX 1.6
SBOMs, retains original license notices and verifies artifact/lock/policy digests.
The packaging suite retains actual reports under `artifacts/security`; after the
final build, CI runs `python -m scripts.check_supply_chain --verify` against those
exact distribution bytes. Every finding requires a reviewed, exact, expiring
exception; missing/skipped evidence and scanner errors fail. See
[dependency security](dependency-security.md) for commands, scope and limits.

D02 retains local candidate identity under `artifacts/releases`. Release decision
and owned HTTP/Git transport tests run in every application job; actual canonical
RC builds/audits/installations exercise preparation without publication. The
dispatch pipeline still requires real green hosted Linux/macOS qualification,
protected main and approved environments; private local checks never bypass it.
See [release pipeline](release-pipeline.md) for the owner setup and retry contract.

D03 adds strict types for `scripts/homebrew.py`, owned HTTP/Git update transactions
and canonical-RC formula tests sharing the actual audited RC build. Its local tap
qualification uses real brew style/audit/install/test/upgrade/uninstall; the prepared
tap CI requires Linux/macOS online checks. See [Homebrew delivery](homebrew.md).

Configure coverage over the entire src/kuberich package, including modules not
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
uv run pytest --cov=kuberich --cov-branch --cov-report=xml --cov-report=json
uv run python scripts/check_coverage.py coverage.json
uv run diff-cover coverage.xml --compare-branch origin/main --fail-under 90 --total-percent-float
```

`scripts/check_coverage.py` compares coverage.json's file inventory to every
Python file under src/kuberich, including unimported namespace-package modules.
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
**DCO**. Quality gate uses `always()` and requires both the verification planner
and the complete event-specific application matrix to succeed. It independently
validates the planner's output for the actual event/ref; failure, cancellation,
skip, missing dependencies, invalid results and incomplete plans cannot pass.
There are no path filters or allowed matrix failures.

### Private development matrix: #109

| Event | Required application jobs |
| --- | --- |
| Every pull request, including documentation | Linux: Python 3.12/3.13/3.14; macOS baseline: Python 3.12 |
| Every main push | Linux: Python 3.12/3.13/3.14 |
| Manual Application quality dispatch on main | Linux and macOS: Python 3.12/3.13/3.14 |

Each selected job still runs the complete behavioral/terminal/packaging suite,
independent coverage gates, build and supply-chain verification. Linux 3.12 keeps
all eleven actual disposable-cluster rehearsals. The macOS baseline is a development
check, not qualification of macOS 3.13/3.14. The planner refuses unknown events
and non-main push/dispatch refs. PR checks stay on `pull_request`; a manual
dispatch never substitutes for the required PR checks. Concurrency groups include
the event so a main push cannot cancel a manual release qualification.

Before a release, dispatch Application quality on the intended main commit and
require all six successful jobs and its retained artifacts. Publication preflight
requires the latest completed successful **manual** quality run for the exact
commit and its main-push Repository checks; a routine three/four-job run cannot
qualify publication. A later failed qualification attempt blocks an older success.
No automatic schedule, extra paid runner, billing change or publication is added.

The [CI usage audit](acceptance/private-ci.md) distinguishes measured historical
job time from projected work reductions, inaccessible account billing and the
unavailable after-change hosted measurement. Resume the configured development
checks when Actions can start, then record an actual before/after comparison in
#109. Full supported-platform qualification remains mandatory in #40.

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
[D10 #89](https://github.com/carloshm91/kuberich/issues/89). Repository visibility
changes still require the maintainer's explicit approval.
See [GitHub's protected-branch availability](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).

## Temporary private-development workflow when Actions is unavailable

Historical condition: the source repository opened under #155 on 2026-10-08.
Hosted development checks resumed, including native macOS qualification in #157
and the #46 candidate. Use actual required hosted results for current merges;
the temporary exception below applies only while its stated blocker exists.
Full release/protection qualification remains #89.


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
passing check or report blocked jobs as passed. Resume the configured event-specific
CI when the restriction is resolved, and qualify the full supported matrix before the
first public release. [Follow-up #109](https://github.com/carloshm91/kuberich/issues/109)
tracks a less costly development matrix and trigger policy. Account budgets,
paid/persistent runners, repository visibility and publication remain separate
maintainer decisions.

## Test layers

The maintainer approved opening the source repository in #155 on 2026-10-08.
Its measured licensing/package checks do not qualify a public product release.
Actual standard-runner development workflows resumed after source opening.
Require their configured matrix for current PRs; preserve honest platform counts. Keep the real
hosted status and the full platform/public-release requirements above.

Q01 #38 consolidates the [owned Kubernetes/fault suite](integration-testing.md).
Required Linux/Python 3.12 CI verifies disposable endpoint/node identity before
writes and real SIGTERM cleanup during setup and after readiness. Release-time
qualification repeats contracts and actual-kind trials three times with separate
artifacts. These repetitions do not replace Q03 performance benchmarks.

### Behavior coverage for every feature

The maintainer requested deeper scenario coverage while continuing incremental
delivery. Each feature PR must map its acceptance criteria to applicable tests
and identify any remaining manual/platform/provider qualification. Test quantity
and code coverage alone do not establish completeness. Use the following scenario
families where they apply, and link unresolved gaps to the implementing issue:

- Resource views: discovered/supported endpoints, typed columns, empty collections,
  denied/absent APIs, pagination, watch renewal/410/reconnect, context generations,
  UID replacement, retained selection/filter/scroll, untrusted text and navigation.
- Mutations including scale: read-only guards, exact captured target and confirmation,
  input/limits, denied access, conflicts and validation failures, cancellation,
  ambiguous transport outcomes and no blind retries. Exercise actual effects only
  on owned disposable fixtures, then verify resulting API state.
- Logs/processes/port-forward: bounded streams, startup/EOF/failure, concurrent
  ownership, repeated start/stop, interruption, resize, exit and process/listener
  cleanup. Demonstrate terminal restoration and real forwarding where applicable.
- Credentials: declared args/env/profiles/roles, expiration and concurrent refresh,
  malformed/private output, authorization versus login failure, context replacement
  and cancellation. Keep local contracts distinct from opt-in real-cloud trials.
- Installation/release: clean built artifacts, supported Python/OS combinations,
  installed CLI behavior, upgrade/rollback and the actual promised install channels.

Use controlled failure injection and negative controls for important regressions
so a test demonstrates the incorrect behavior would fail. Add release-time soak
scenarios under Q01 #38; do not replace behavioral assertions with implementation
mirrors or arbitrary repetitions. The existing independent 90% floors and 100%
critical-module gates remain mandatory, and maximum practical coverage is the target.

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
Provider qualification and later effectful integrations remain pending; a parsed flag is not
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


S04 adds selected-container shell identity/return decisions to the critical
inventory. API/Pilot/native-PTY/fresh-install cases cover configured/default
shells, read-only policy, scoped arguments, private connection preparation, stale
UIDs, failures and cleanup. The Linux/Python 3.12 job additionally requires
`scripts.verify_shell_kind`: actual kubectl exec, two containers, fullscreen vi,
resize, interruption, repeated return, source-kubeconfig pinning and RBAC denial.
Its matching kubectl 1.36.4 is downloaded into the runner's temporary directory
and verified against a pinned SHA-256; no global kubectl is replaced. The owned
cluster is deleted on success/failure and sanitized terminal/cluster evidence is
retained. Hosted/macOS results remain unavailable under the billing restriction.

F05 #19 adds actual HTTP/TLS tests for alias selection, credential replacement,
repeated impersonation headers, loaded UID/extras, stream consistency, server
denial and private shell snapshots. Pilot checks effective identity and timed age
updates while filtering, with unchanged request count/session generation. Source
and freshly installed CLI PTYs exercise overrides across context/namespace
navigation and terminal restoration. The owned kind shell check also requires
explicit CA/client certificate files, forced TLS verification, alternate aliases,
successful impersonated exec, impersonated exec denial, and token replacement of
the original client certificate identity. These checks establish the initial
launch contract, not cloud provider or later mutation/plugin qualification.
