# Development checkpoint

## Unreleased 0.4.0 relationship source

Development work for #70 adds native `:xray` and `:usedby` with separate owner,
selector, endpoint, placement and declaration evidence. Graph opening retains
expected UID checks, path-local cycles, explicit source completeness and minimal
navigation history. Pod and seven workload templates, including zero replicas,
plus ServiceAccounts and PV/PVC declarations are supported. Arbitrary CR reference
search and proof of process consumption remain unsupported. See the
[relationship acceptance record](acceptance/resource-relationships.md).

The source starts from #69's protected squash
`55e5937d955b91a283924650432b54ff2a0a5fc1` after PR #311 passed all 27 selected
jobs, Repository checks and DCO. Its independent 98.7960% line, 95.9154% branch,
99.57% changed-line and 86-critical-module results qualify that baseline only.
Retry 2 recovered GitHub artifact DNS `ENOTFOUND` after a separate supported
test-timeout correction. The automatic-main application run 41973484821 passed
all 22 jobs, and Repository run 41973485184 passed. These baseline results do
not qualify the later #70 source.

The pure focused command passed 133 cases with both modules at 100% lines and
branches. The corrected UI cohort passed 11 cases; collector cohorts and their
independent coverage limits are recorded separately. These overlapping results
are not one combined suite. Actual App/owned-HTTP integration now passes 17
cases, including delayed/filter-render readiness and cross-context Back. The
first disposable-kind trial passed in 38.026 seconds with all 217 source inputs
unchanged and complete owned cleanup. The initial whole local campaign retained
four failures; exact guide census and asynchronous test-readiness corrections
passed their focused cohorts without production changes. Complete current-head
hosted/platform/package evidence remains pending. See the acceptance record for
the original failure lineage, measured coverage and scoped corrections.

```sh
COVERAGE_FILE=artifacts/issue70/domain/.coverage uv run pytest tests/unit/test_relationships.py tests/unit/test_reference_fields.py -n 0 --cov=kuberich --cov-branch --cov-report=json:artifacts/issue70/domain/coverage-final-qualified.json --cov-report= -q
```

This tested command uses synthetic fixtures, not an ambient cluster. Source
metadata remains 0.3.0; this work is unreleased for 0.4.0 and does not publish
artifacts or update the installed release. Earlier sections below keep their
recorded source boundaries and historical qualification limits.

## Unreleased 0.4.0 overview source

Development work for #69 adds native `:pulse`/`:overview`, scoped health/capacity
summaries and typed drill-downs. Its configured Prometheus Service-proxy reader
supplies real CPU/memory `query_range` history with literal selectors, visible
backend binding, missing-sample gaps and independent expiry. It does not install
a backend or infer a cluster label from a context name. See the maintained
[overview acceptance record](acceptance/cluster-overview.md) for exact scoped
measurements and remaining evidence.

This work starts from protected main
`ced365fd224d1f6c872fda638f5d7c6d8a1d75c8`, which delivered #68. That baseline
passed 27/27 PR jobs and 22/22 automatic main jobs; these results do not qualify
the later overview source. The implementation's focused history, collector,
reload and UI cases passed as recorded in the acceptance note. The real owned Prometheus trial passed in 100.88 seconds, including actual
chart values, independent raw-backend comparison, keyboard drill-downs, partial
RBAC and verified cleanup. The controlled large-collection observation served
35,000 records within the shared 10,000-item retention bound. Complete
PR #311 subsequently passed 27/27 jobs at
`20e82dbac29c2a47dca3be2510a32f1b7a75fd42`; the protected squash
`55e5937d955b91a283924650432b54ff2a0a5fc1` passed 22/22 automatic-main jobs.
The measured global result was 20,514/20,764 production lines and 5,941/6,194
branches, with 99.57% changed-line coverage and 86 critical modules at 100%.
Those results qualify the overview source, not later relationship changes.
Source metadata stays 0.3.0; installed public 0.3.0 does not include
this work. Published release records below remain unchanged.

## Qualified 0.3.0 source

The current qualified release source is protected commit
`b1f00706ff3448cded7818633c84ed77e3ca83af`, tree
`efa050ba125172145cb157efbe24ec857c5d9df3`. [#230](https://github.com/carloshm91/kuberich/issues/230)
is closed with its scoped acceptance complete. Version 0.3.0 was published to
PyPI and GitHub Releases on 2026-11-04 by
[release run 41872341380](https://github.com/carloshm91/kuberich/actions/runs/41872341380).
The annotated tag points to the same qualified source, the 24 GitHub asset
digests match, and both actual PyPI distribution downloads match their tested
bytes. The actual Homebrew source formula is active at tap commit
`670925d22df047bb3aae352c54a42e28d453f456`, with its generated formula SHA-256
`a96cd455ca66af8943a310ed04fe421e2d84764d94322007dd665aac0b54d9af`. Source
CI passed both platforms and DCO; a macOS retry addressed an unassigned runner,
without an executed test failure. Bottle publication completed in
[run 41882852493](https://github.com/carloshm91/kuberich/actions/runs/41882852493).
The three public archive digests match their reviewed inputs, and the bottle-only
tap update merged at `3018e8c8f27c7ce060391095a27501a1fe2ae9de`, retaining
the source formula above. Public-pour verification is recorded in
[run 41903084439](https://github.com/carloshm91/kuberich/actions/runs/41903084439),
whose actual results are the authoritative consumer verdict. It was dispatched
from `fix/230-bottle-verification` at
`8fd1e92dffaf98fa307123bec6c6f1a95c2a1149`, not protected main; its consumer
results remain separate from the release-source qualification above. Linux and
Apple Silicon passed. The Intel dependency step reached its 75-minute limit
while Homebrew was compiling Python; the application-install step was skipped.
The retained Intel log SHA-256 is
`af34ec0dca22396b0df5e31f8bf5b1c3fcc3bdb4ac1970b4be324e0fb5c96a65`.
This failed attempt does not establish an Intel application-pour result.

The follow-up verification bounds only Intel dependency setup at 120 minutes
within a 150-minute job; other hosts retain their 75-minute setup and 90-minute
job limits. The application install, pour, version, test and uninstall step
retains its separate 30-minute limit on every host. The fresh
[public-consumer run 41917440980](https://github.com/carloshm91/kuberich/actions/runs/41917440980)
passed all three hosts, including actual public-bottle pour, version, formula
test and uninstall. Intel dependencies took 77 minutes 12 seconds while the
application phase took 66 seconds; the original timeout remains a separate failure.
Its reviewed branch-source evidence remains distinct from protected-main
release-source qualification.

Protected guidance merged at `25265acfa2424a89bec275bf016b255db3b3448a`
after all 27 PR jobs, Repository and DCO passed. The automatic main Quality run
then passed 22/22 jobs and Repository checks. The owner-approved
[website run 41929743259](https://github.com/carloshm91/kuberich/actions/runs/41929743259)
published both surfaces successfully on 2026-11-05 UTC. Its manifest SHA-256 is
`e0e6216605916cc8fcaa9e72ae73552e11302242cf608251cde462c4abf8baa7`.
Both provider deployment/production hosts verified every served file, header
and 404; independent custom-host verification matched 35 files and nine
root/routing checks, including legacy `/docs` and `www` redirects. Both
`kuberich.com` and `docs.kuberich.com` serve the reviewed public 0.3.0 content.
The [delivery closeout](https://github.com/carloshm91/kuberich/issues/230#issuecomment-6647028828)
records deployment IDs, previous deployment targets and the retained receipt.
Pre-deployment HTTPS checks recorded on 2026-11-04 at 17:01 UTC found both
production website hosts serving 0.1.0. Source changes do not deploy them.

Exact-source [manual quality](https://github.com/carloshm91/kuberich/actions/runs/41708242403)
passed all 37 jobs, including the six Linux/macOS Python environments and four
standalone targets. [Repository validation](https://github.com/carloshm91/kuberich/actions/runs/41708121466)
and the [six native Homebrew lanes](https://github.com/carloshm91/kuberich/actions/runs/41716910423)
also passed. Native Homebrew evidence contains nine actual source/bottle upgrade
cases and remains separate from the coordinator native-platform gate.

The single local coordinator passed all 63 gates: 7,262 full-suite cases with
five platform/workflow skips, two further contract rounds of 1,279 passed plus
one macOS clipboard skip each, and all 13 owned-kind verifiers plus installed
quickstart in each of three rounds. Production coverage was 18,836/19,078 lines
(98.73%) and 5,388/5,626 branches (95.77%); changed coverage against the published
0.2.0 source was 3,245/3,351 (96.84%), with designated critical lines and
applicable branches at 100% and no excluded lines.

The real CLI sustained workload measured 1,800.063 seconds and passed all hard
memory, descriptor, thread, restoration and cleanup checks. Numeric 0.x latency
remains advisory. All 211 independently observed process/start-time identities,
176 process groups and created test containers were absent after cleanup; all
58 original command drains passed. The private wrapper used incomplete
leader-thread tracking and deferred adopted-helper orphan reaping until exit;
the final independent all-thread/start-time/group audit supplies the cleanup
proof. The same original command continued by explicit root decision, with no
second campaign or injected runtime reaping.

Canonical local evidence remains under the final-pr307 worktree at
`artifacts/issue230/final-main-b1f/qualification-0.3.0/`. The original
`report.json` SHA-256 is
`6acc558c9728653c2e4257f5aa4091ae11af6c7399bb4e75d87ba27e4913c2d7`;
`summary.md` is
`7f07a49355d661b2e0d7a6c103deb064155f63d3278492788316d1f3bf13970c`.
These reports do not authorize publication. Real-provider certification stays
opt-in under #87; stable architecture/performance goals remain under #88/#212.
Historical failed and cancelled source-specific evidence is preserved.

## Earlier engineering checkpoints

The following sections describe their recorded historical source and policy;
they do not qualify another candidate or describe current package availability.

This maintained internal checkpoint carries the inspected protected source
`1075d6833d9c4e42808bae103978b6bd569cfae9`. Historical preview snapshots remain
unchanged and do not establish current qualification. The brief user
[Status](../first-preview.md) describes the installed and development versions.

The previous maintained checkpoint was inspected at
`857f9ad0216688853142d9b463d5d41cc955114f`; its source-scoped results and
failures below remain historical. Later sections identify subsequent checkpoints.

**KubeRich 0.2.0 is published** on [PyPI](https://pypi.org/project/kuberich/0.2.0/),
[GitHub Releases](https://github.com/carloshm91/kuberich/releases/tag/v0.2.0) and
[Homebrew](https://github.com/kuberich/homebrew-tap).

```sh
brew install kuberich/tap/kuberich
# Alternative with Python 3.12–3.14:
uv tool install --python 3.12 kuberich
kuberich --version
kuberich config check
```

Choose one installation method. Start with
`kuberich --context YOUR_CONTEXT --namespace YOUR_NAMESPACE --readonly`, using
your intended context and namespace. The [installation guide](../installation.md)
covers pipx, standalone archives, updates and removal. To move from 0.1.0, run
`uv tool upgrade kuberich`, `pipx upgrade kuberich` or
`brew upgrade kuberich/tap/kuberich`. Your preferences and kubeconfig stay as
they are.

The [release notes](../release-notes/0.2.0.md) list what is new: themes,
navigation and column preferences, local plugins, ConfigMap and Secret data,
resource jumps, live preference reload, context edits, pod cleanup and
forwarding presets. Homebrew installs a prebuilt bottle on macOS Apple Silicon,
macOS Intel and Linux x86_64.

The [website](https://kuberich.com/) and [documentation](https://docs.kuberich.com/)
still show the 0.1.0 content. Their 0.2.0 update needs separate approval.

## 0.2.0 validation

The exact release commit passed all six Python combinations on Linux and macOS,
the four standalone archive builds and the Homebrew source and bottle installs.
Coverage was 98.78% of lines and 95.93% of branches, with 100% for the critical
modules. Three consecutive rounds passed the contract tests and every local
test-cluster scenario, including cleanup. The published wheel has the same
SHA-256 as the locally built one. Installs from PyPI with uv and pipx, and
upgrades from the published 0.1.0 packages, passed in clean environments.

Real EKS, AKS and GKE clusters are not certified yet; those trials stay opt-in.

## Next development phase: 0.3.0

Contributors can start with the short [architecture overview](../architecture.md)
and [decision index](../adr/README.md). The overview describes the implemented layers,
resource data flow, ownership and security boundaries; migrated decisions and their
unchanged historical source remain separate from current implementation notes.
The [architecture acceptance record](acceptance/architecture-overview.md) lists
the source boundary, focused checks and qualification limits. Its source-scoped
local verification passed 74 existing controls plus applicable static checks;
the exact historical archive remains unchanged. A later required-check correction
waits for a plugin job's final visible status together with its output, after a
real-child/Pilot cleanup-boundary control. Product lifecycle and the original
result/cleanup assertions remain intact. Final PR qualification is separate.

```sh
uv run python -m pytest tests/quality/test_architecture_docs.py
uv run python -m scripts.validate_plan
```

These are local documentation checks. They do not launch the application,
connect to a cluster or publish the website. The installed release remains 0.2.0.

The development checkout now has focused task guides and four generated
references, with 19 content pages plus the index. Start with the
[quick start](../quickstart.md), then use the [everyday workflow](../everyday-workflow.md)
or the guide for your task. Previous guide URLs and heading fragments remain
supported. Generated Markdown also resolves at its canonical paths in GitHub.
The guides cover development-source limits; the installed release remains 0.2.0.
The hosted website still needs its separately approved update.

```sh
uv run python -m scripts.site_reference
uv run python -m scripts.validate_plan
uv run python -m scripts.build_site --output artifacts/issue224/c2-delivery/site
uv run python -m scripts.check_site --output artifacts/issue224/c2-delivery/site
```

The [guide acceptance record](acceptance/task-guides.md) records the tested source,
focused checks and remaining qualification. These commands check documentation
locally; they do not start the application or connect to a cluster.

The local browser check also passed all 43 pages at desktop and mobile widths,
including navigation with JavaScript disabled, with zero accessibility findings.
It follows **Commands and keys** and the **Commands, keys, and launch options**
heading. The [acceptance record](acceptance/task-guides.md#browser-correction)
preserves the original stale-label CI failure and the corrected 79.77-second
Linux/Chrome result, source and cleanup limits. The exact checked command was:

```sh
node scripts/verify_site_browser.mjs artifacts/issue224/c2-delivery/browser-fix/site artifacts/issue224/c2-delivery/browser-fix/qa
```

Development source adds an inline Retry panel for resource-view presentation
failures and a local `kuberich bug-report` command. Report files are private and
redacted; the diagnostic command does not read kubeconfig or connect to a
cluster. Fatal UI errors restore the terminal before printing a crash-report
path. These changes
are not part of the installed 0.2.0 release. Integrated platform, package and
whole-application qualification remain pending.

```sh
uv run kuberich bug-report --output ./kuberich-report.json
uv run pytest tests/ui/test_view_errors.py tests/contract/test_bug_report_cli.py tests/unit/test_diagnostic_reports.py
```

The foundations phase is in progress. Its first task adds full unit/contract/UI
test selection, local xdist workers and a fast CI signal before full qualification.
Worker ownership, failure propagation, coverage combination and timing isolation
have dedicated regressions. The complete fast selection passed locally with
4,588 tests and one expected macOS-only clipboard skip in 158.00 seconds.
The [quality guide](../quality.md#test-layers-and-local-parallel-runs) records the
same-candidate serial comparison, full-run measurements and verification policy.
Complete platform, artifact and coverage checks remain required for the phase.
The installed release is 0.2.0.

```sh
uv sync --locked --group dev
uv run pytest tests/unit tests/contract tests/ui -m fast -n 12
```

Use fewer workers on smaller machines. These are developer checks on owned
fixtures, and do not require access to your Kubernetes contexts.

The development source also corrects plugin review from qualified custom-resource
views. Matching commands can review the selected UID after the view is live;
previous resource names and API versions remain refused while a new view loads.
This correction is not included in the installed 0.2.0 release.

The integrated development source also passes the full-package check against
private test dependencies. Workspace tests now use public command/state boundaries
while retaining captured-target, cancellation and bounded-cache behavior. Full
platform, runtime and coverage qualification remains pending for this foundation
work; the installed release remains 0.2.0.

```sh
uv run python scripts/check_private_access.py
```

## Development: bounded live collections

Development source keeps a resource view live when it reaches 10,000 retained
rows or 64 MiB of retained payload. The view labels incomplete membership;
updates remain tied to resource UIDs. Server queries narrow the Kubernetes
request separately from the local `/` filter:

```text
:server label app=api
:server field metadata.name=api-one
:server clear
```

Generic views also offer `:server compact` for metadata-only Table rows and
`:server full` to restore full objects. Inspection fetches the full object when
needed. These modes preserve existing scope and identity checks. The
[workspace guide](../resource-workspace.md) explains the limits and recovery.

Owned Kubernetes fixtures verified pagination, filtering, compact rows, fresh
full-object reads, watch updates and cleanup. Large-fixture contracts check
retention bounds; they do not certify sustained throughput, process RSS or a
long-running soak. This behavior is not in the installed 0.2.0 release.

## Development: kubeconfig compatibility

Development source supports explicit Basic credentials and empty optional
kubeconfig connection fields. Reads, guarded writes and delegated tools keep
the same captured identity. Known unsupported fields receive an actionable
message. For legacy OIDC, an explicit offline command generates a reviewable
exec-plugin migration fragment without copying tokens or changing kubeconfig:

```sh
uv run kuberich kubeconfig oidc-migration --help
```

The command above was checked without connecting to a cluster. The
[context guide](../context-sessions.md) documents migration, supported fields and
remaining limits. Captured/background plugin output masks known prepared Basic
credentials; foreground output goes directly to the terminal.

Local TLS/API, helper and synthetic provider-shaped contracts have been checked.
Actual EKS, AKS, GKE, Teleport and tailnet accounts are not certified. Full native
and phase qualification remains required. The installed release is still 0.2.0.

## Development: previous command name

The 0.3 development source keeps `kubetrol` as a deprecated command. It prints
one fixed notice to stderr naming `kuberich` and the planned 0.4.0 removal;
stdout and exit codes keep the canonical CLI behavior. The package, imports
and new default paths use KubeRich.

```sh
uv run kuberich --version
uv run kubetrol --version
```

These commands report 0.3.0 in the prepared development source. The published 0.2.0 package does not
include the new warning. Existing preference/environment/log compatibility stays
supported. Explicit preference migration keeps previous files and reports
creation only once; see [configuration](../configuration.md#legacy-preview-compatibility).

## Development: one phase verification command

The development checkout now provides a coordinator for the existing checks:

```sh
uv run python scripts/qualify.py --help
uv run python scripts/qualify.py 0.3.0 --collect-only
```

The first command explains the options. The second writes an honest pending
report without starting tests or clusters. A local run executes the existing
checks once and records their source, original logs, cleanup and remaining
native/repetition requirements. Read the [phase verification guide](../releases.md#reproduce-phase-verification)
before running the full command. The installed application remains 0.2.0.

Failed canonical release-candidate audits now retain their own partial output
separately for diagnosis. The original failure still fails verification.

## Development: runtime latency observations

For 0.x development, runtime latency observations retain their original targets
and report whether they met them. Small overshoots do not replace functional
correctness as a release blocker. All workload, resource, memory, cleanup and
coverage checks remain required. Strict runtime limits remain available with
`KUBERICH_STRICT_RUNTIME_BUDGETS=1` and become mandatory for major-version 1
candidates; the deliberate blocking negative controls always remain strict.
Focused policy, receipt and release controls passed 423 cases. Three actual
aggregate-UI, HTTP-backend and mounted-terminal cases also passed, retaining both
always-strict blocking controls and full positive workload/cleanup checks. These
are local prerequisite checks, not full platform or coverage qualification.
The [quality policy](../quality.md#performance-evidence)
explains the exact observation and validation contract.

```sh
uv run pytest tests/quality/test_runtime_budget.py tests/quality/test_runtime_coverage.py tests/quality/test_backend_runtime.py
```

## Development: owned X11 clipboard qualification

The native clipboard trial now observes exact selection receipt on a disposable
Xvfb display. A controlled delayed real writer reproduces the earlier immediate
read failure; missing/wrong-selection and cancelled-reader controls keep their deadlines
and require owned process cleanup. The clipboard cohort passed 32 cases with one
explicit macOS-only skip on Linux. This changes developer qualification; the
published application remains 0.2.0. Native/full required checks remain pending.

```sh
uv run pytest tests/contract/test_clipboard.py tests/contract/test_x11_readiness.py tests/unit/test_clipboard.py
```

### Development checkpoint: Wayland clipboard

The unreleased checkout can copy through `wl-copy` in local Wayland sessions.
Automatic detection prefers Wayland over XWayland and keeps OSC52 over SSH.
The helper receives plaintext on stdin and closes on replacement or application
exit. The native 1 MiB limit and terminal 64 KiB limit still apply.

```sh
uv run pytest tests/unit/test_clipboard.py tests/contract/test_clipboard.py \
  tests/contract/test_wayland_clipboard.py tests/ui/test_clipboard.py -n 2 \
  --cov=kuberich --cov-branch --cov-report=json --cov-report=xml
```

The original source checkpoint passed 56 tests with one explicit hosted-macOS skip and
100% line/branch coverage in both clipboard modules. Its helpers simulate
`wl-copy`; no real compositor or developer clipboard was used. See
[Wayland verification](acceptance/wayland-clipboard.md) for the measured scope.
Full-package and supported-platform checks remain required before delivery.

## Included in 0.2.0: live preferences

Edit and save the preference file while KubeRich runs. Themes, aliases, column
views, jumps and plugins update within two seconds, and the current view stays.
An invalid file keeps the last valid preferences. A `context_settings` section
can make one context read-only or change its refresh interval. Palettes can use
`'default'` to show the terminal's own background, and
`appearance.full_gvr_titles` shows the API version in titles.

```sh
uv run pytest tests/ui/test_live_preferences.py tests/unit/test_context_settings.py
```

See [configuration](../configuration.md#changing-preferences-while-kuberich-runs)
and [acceptance evidence](acceptance/reactive-preferences.md).

## Included in 0.2.0: resource jumps

Define jumps in the preference file, select a row and type `:jump` or
`:jump NAME`. The related view opens with a label or field filter already set,
for example from a Deployment to its pods or from a node to its pods.
`kuberich config check` validates the definitions.

```sh
uv run pytest tests/unit/test_jumps.py tests/ui/test_jumps.py tests/unit/test_cli_config.py
```

See [resource jumps](../resource-jumps.md) and
[acceptance evidence](acceptance/resource-jumps.md).

## Included in 0.2.0: context edits and pod cleanup

In `:ctx`, `:rename NEW` renames the selected context and Ctrl+D or `:delete`
deletes it. Review shows the file and the change first; a backup is written
before the file is replaced. In a pods view, `:cleanup` reviews deleting the
completed and failed pods shown.

```sh
uv run pytest tests/unit/test_kubeconfig_edit.py tests/unit/test_cleanup.py tests/contract/test_kubeconfig_files.py tests/ui/test_context_cleanup.py
uv run python -m scripts.verify_cleanup_kind --kind /absolute/path/to/kind
```

See [context edits](../context-sessions.md#rename-or-delete-a-context),
[finished-pod cleanup](../resource-operations.md#clean-up-finished-pods) and
[acceptance evidence](acceptance/context-cleanup.md).

## Included in 0.2.0: forwarding presets

The next-release source adds named/container-qualified TCP mappings, local and
exact-context presets, explicit local permission for annotation shortcuts,
kubectl child transport selection and optional bounded reconnects. Non-loopback
binds still need separate confirmation; resource listing never starts a listener.

```sh
uv run pytest tests/unit/test_forward_presets.py tests/contract/test_forward_reconnect.py tests/ui/test_forward_presets.py
uv run pytest tests/terminal/test_port_forwards.py tests/packaging/test_forward_presets.py
```

The final focused command passed 220 cases in 79.79 seconds, including real
source/installed terminals and initial/replacement startup failure regressions. Both new deterministic modules measured 100%
line/branch coverage. Fresh owned-kind trials verified HTTP, named annotations,
both transport modes, listener collisions, deliberate remote bind, Service backend
replacement/reconnect and full cleanup. Required platform/native PR checks and
the cumulative phase qualifier remain independent gates.
See [forwarding behavior](../port-forwards.md) and
[acceptance evidence](acceptance/forward-presets-0.3.md).

Required checks also exposed a table-cache collection pause and a configuration
key-name clipping race. The source now releases retired native cache entries
promptly and sizes key columns from captured metadata before painting. Both have
owned negative controls. The local Python 3.13 runtime trial retained an 89-ms
maximum gap with the original 150-ms limit and active GC; fresh full platform/native
qualification remains required. The maintainer requested stopping after this
ticket's verified delivery, before starting the next implementation issue.

## Included in 0.2.0: terminal navigation

The next source checkpoint adds command/filter recall, inverse/fuzzy/metadata
filters, wide/errors controls, bounded UID ranges and explicit namespace
favorites. Read-only workspaces share chrome and nested command routing;
container status refreshes from the owned Pod watch. Native macOS/X Window System writers and
OSC52/tmux clipboard requests have explicit UTF-8 bounds.

```sh
uv run pytest tests/unit/test_interactions.py tests/unit/test_selectors.py tests/unit/test_metadata_filtering.py
uv run pytest tests/ui/test_interactions.py tests/terminal/test_interactions.py
```

Focused deterministic clipboard/history/range/selector modules passed 100% line
and branch coverage. Pilot verified controls at 40 and 120 columns, live
container status and fatal permission invalidation. Owned kind verified status
patches, same-name UID replacement, nested namespace/context drain and Escape;
that Pod was deliberately unscheduled and is not a real exec/restart trial.
Owned Xvfb and ephemeral hosted macOS verified synthetic plaintext clipboard
roundtrips. Source and installed console/module PTYs verify navigation and exact
OSC52 receipts. The [implementation PR](https://github.com/carloshm91/kuberich/pull/206)
retains the successful protected platform/native and coverage qualification.
See [behavior and limits](../terminal-navigation.md).

## Included in 0.2.0: plugin compatibility and examples

The source classifies all 50 pinned community plugin files and 108 commands,
including two executable helpers. It adds three original reviewed definitions
for Pod inspection, an interactive local kubectl exec and finite background
event collection; 18 synthetic argv adaptations record their changed semantics.
Upstream scripts/virtual views/legacy tools are not automatically imported,
installed or claimed as native features.

```sh
uv run pytest tests/contract/test_plugin_examples.py tests/unit/test_plugins.py
uv run pytest tests/terminal/test_plugin_examples.py
```

See [compatibility and examples](../plugin-compatibility.md) and
[acceptance evidence](acceptance/plugin-compatibility.md). Runtime prerequisites,
read-only trust, output/Stop behavior and separate service identities are explicit.

## Included in 0.2.0: plugin execution

The next-release source adds `:plugins`, `:plugin NAME`, typed Review/Run forms,
resource-scoped shortcuts and `:pluginjobs`. Capture, background and native
foreground commands use owned processes, explicit read-only trust, bounded
captured output and private single-context credentials. Context/UID invalidation
and exit drain processes before removing connection files.

```sh
uv run pytest tests/contract/test_plugins.py tests/ui/test_plugins.py
uv run pytest tests/unit/test_credential_child.py tests/unit/test_plugin_commands.py
uv run pytest tests/terminal/test_handoff.py
```

See [the invocation guide](../plugins.md) and [acceptance evidence](acceptance/plugin-execution-0.3.md).
Foreground local plugins deliberately use native terminal handoff; pod/container
shells remain embedded. Arbitrary local programs are not sandboxed, and direct
foreground output cannot be redacted by KubeRich.

## Included in 0.2.0: plugin configuration

The source validates explicitly configured global/context plugin files, exact
resource scopes, shortcut overrides, typed inputs and captured literal variables.
This configuration checkpoint executes no command; interactive invocation and
owned process execution follow in the next task.

```sh
uv run pytest tests/unit/test_plugins.py tests/contract/test_plugin_files.py
```

The offline CLI test also runs `kuberich --config <owned-fixture> config check`,
verifies no sentinel command was executed and confirms the file is unchanged.
See [configuration and trust](../plugins.md) and [evidence](acceptance/plugin-contract.md).

## Included in 0.2.0: navigation preferences

The next-release source supports per-view navigation keys, literal command aliases
and resource-specific column order, visibility, width, alignment and typed sort.
`:views` applies a session choice or explicitly saves globally/per context.
Help/completion reflect effective settings; invalid overrides retain working
navigation and the original file. Server-column signatures prevent stale saved
positions from being interpreted under a changed schema.

```sh
uv run pytest tests/unit/test_navigation_preferences.py tests/contract/test_navigation_preferences.py
uv run pytest tests/ui/test_navigation_preferences.py tests/terminal/test_preferences.py
```

The source PTY verifies actual remapped keys, alias completion, private saves,
reopening and terminal restoration against an owned local API. Expanded filters, resource jumps, reactive reload and
plugins remain later work. See [the guide](../navigation-preferences.md) and
[measured acceptance](acceptance/navigation-preferences.md).

## Included in 0.2.0: appearance

The next-release source provides `:themes`, `:theme` and `:about`, custom opaque
palettes, environment/context/global precedence, explicit preference saves and
runtime `--invert`. Version notices are disabled by default; opt-in checks are
asynchronous, bounded, cached and offline-safe. See [the guide](../themes.md).

```sh
uv sync --locked --group dev
uv run kuberich --command themes
uv run kuberich --invert --command about
```

The commands were exercised through actual source/installed-console/module PTYs,
including NO_COLOR, preview/cancel, a real save, 40-column About and terminal
restoration. Owned HTTP/cache and Pilot cases cover errors, cancellation,
precedence and private persistence. [Appearance acceptance](acceptance/appearance.md)
records measured scope; the issue-linked PR retains exact-head platform gates.
No real cloud was used.

## Included in 0.2.0: configuration data

The next-release source adds Enter / `v` on ConfigMaps and Secrets: a key/size
index with values hidden by default, explicit per-key reveal/copy, UTF-8/Base64
selection, bounded output and fresh UID/version-bound reads. Secret manifests
use the existing deliberate editor disclosure, redacted review, strict dry-run
and separate conditional Apply. Ordinary inspection stays redacted.

```sh
uv sync --locked --group dev
uv run kuberich --context YOUR_CONTEXT --namespace YOUR_NAMESPACE --readonly
```

These commands run the checkout.
Owned-loopback Pilot and real PTY verification cover the controls; disposable-kind
verification covers actual Secret/ConfigMap reads and guarded edits. Measured
final acceptance is retained in [configuration-data evidence](acceptance/configuration-data.md).
No maintainer cluster was used; real-cloud certification remains deferred.

## Available workflows

The current implementation supports live pods, context and namespace tables,
standard resource views and discovered custom resources. Commands complete
inline, filtering uses `/`, and Vim-style navigation retains the selected
resource as the table refreshes.

Enter on a pod opens its containers; Enter on a container opens its logs.
Current, previous and aggregate logs, embedded shells, pod/Service forwarding,
captured attach and guarded file transfers are implemented. Reviewed changes
include annotation updates, manifest dry-run/Apply, scale/restart/rollback,
deletion and Job/CronJob operations.

Version 0.2.0 adds themes, configurable navigation and views, local plugins,
deliberate Secret editing, terminal refinements and Homebrew bottles. Metrics and
advanced node/debug operations remain planned. Complete K9s parity and stable 1.0
compatibility are later milestones.
The [guided workflow](../everyday-workflow.md) describes the current controls,
and the [release phases](../releases.md) explain what belongs to each version.

## 0.1.0 validation

The website and documentation contain fictional examples and actual application
renders from owned fixtures. Both generated surfaces passed checks across
57 offline-preview pages, including desktop/mobile navigation, accessibility
and local links. The public build has 30 pages without duplicate guides. Its
exact deployed artifact passed all 30 desktop and 30 mobile browser cases,
keyboard/copy/no-JavaScript navigation and zero automated accessibility
violations. Live custom-domain checks independently matched the served content;
the remaining asset-header cache finding above is retained without a waiver.
Exact main `3dbf9c0118193aa11635baea6ae2a0b36bee4c6e` passed all six source
Python combinations and all four native executables. Original audits and native
provenance passed independent review. Measured coverage was 99.0987–99.1296%
lines and 96.8382–96.9721% branches, with 100% for designated critical modules.
Three fresh consecutive rounds passed all thirteen owned-cluster scenario
families with caller configuration preservation and cleanup.

Actual TestPyPI/PyPI uploads, SBOM/build attestations, immutable annotated tag and
all 24 public GitHub attachment digests passed verification. Public PyPI-by-name
uv and pipx installs passed version/help/default-preference checks, no-op upgrade
and uninstall in owned environments. The public Linux x86_64 archive also passed
CLI checks outside the checkout. The other archive bytes match their native
hosted qualification. The published Homebrew formula passed Linux/macOS style,
online audit, source install, CLI tests and uninstall before protected merge.
There is no prior public release to claim as a version-upgrade baseline.

These safe local commands have been verified against the candidate:

```sh
uv sync --locked --group dev
uv run kuberich --version
uv run kuberich --help
uv run kuberich config check
```

They do not contact Kubernetes or execute authentication helpers. Connecting
requires an explicitly intended kubeconfig/context; see [first launch](../quickstart.md).
The default preference permits writes. Use `--readonly` for a first connection;
write actions require the corresponding Kubernetes permissions and their
operation-specific target/review controls.

The [candidate evidence](acceptance/first-release-preparation.md) retains measured
results and limits. [Historical engineering checkpoints](preview-history.md)
remain available separately. Real cloud-provider and physical-terminal
certification still require their later opt-in trials.

### Wayland platform fixture correction

The focused clipboard command above now passes 59 cases with one explicit
macOS-only skip on Linux (17.32 seconds). It covers native failure/fallback
behavior for X11, Wayland and macOS through an inert driver on every host.
The first hosted macOS failure was a missing platform boundary in synthetic
Linux fixtures; it is retained in run `41280079738`. No native host or compositor
qualification is inferred from the synthetic cases.

### Wayland parent integration

The local parent integration preserves the application clipboard queue and the
owned X11 receipt checks. Its 225 focused helper/process/queue/public-UI and
documentation cases passed in 51.54 seconds. The critical clipboard domain
retains 100% line and branch coverage; the native service including its queue
measured 96.77% of lines and 91.18% of branches, with 94.74% changed-line coverage.
The [acceptance record](acceptance/wayland-clipboard.md#parent-integration-verification)
separates these results from the earlier source checkpoints. No real Wayland
compositor, host clipboard or cluster was used. The installed version remains
0.2.0; full supported-platform and package qualification remain pending.
### Opened plugin job results

After opening a running job in `:pluginjobs`, its status, exit code and completed
output now update without pressing Enter again. Cursor movement keeps the opened
job until another Enter; retired history releases its displayed result.

The tested local regression command was:

```sh
uv run pytest tests/ui/test_plugin_jobs.py tests/ui/test_plugins.py \
  tests/contract/test_plugins.py tests/terminal/test_plugins.py \
  tests/quality/test_release_policy.py \
  --basetemp artifacts/plugin272/tmp/regression-01 \
  --cov=kuberich --cov-branch \
  --cov-report=json:artifacts/plugin272/regression-coverage.json \
  --cov-report=xml:artifacts/plugin272/regression-coverage.xml \
  --junitxml=artifacts/plugin272/regression-tests.xml
```

The selection passed 326 cases on Linux/Python 3.12, including source CLI
terminal restoration. The final two UI cases also passed after strengthening
the output-only check. Changed application lines measured 100%; complete
platform, package and coverage gates remain required. The original macOS
failure and the unchanged-main negative controls are retained in
[plugin execution evidence](acceptance/plugin-execution-0.3.md).

The 326-case result and changed-line measurement above are retained historical
evidence from the original correction. They do not qualify the refreshed
delivery head or its newer prerequisite tree; current-parent validation is
recorded separately before delivery.

## Parent verification follow-up

The protected parent's automatic-main Quality run `41444530467` failed its Fast
job `125274306280` in the deleted-initial-record retention contract. The original
failure is retained. The reviewed result-ownership correction below addresses
the diagnosed lifetime; final PR qualification remains pending. The earlier
complete PR qualification remains source-scoped and does not turn that later
failure into a pass.

## Internal documentation relocation

The internal-evidence migration retains all 102 pre-existing immutable payloads
and their original source records. Three already-recorded editing, startup-budget
and terminal-navigation snapshots retain their `1875994d5c4bd7946b0196aa4fe9e4679a6810d6`
source identities, for 105 immutable payloads total. The original
`first-preview-0.3.md` remains the unprotected prepared `aad1a0b2` source; it has
not been relabeled as protected or substituted for this maintained checkpoint.

Current planning data moves into the three existing operational JSON locations.
The actual protected task-guide and architecture acceptance records move into
maintained internal Markdown, with ordinary current-source link checks. All
runtime code, qualification stages and unrelated behavioral tests at that first
integrated tree remained the actual protected parent. This included the plugin-job completed-result wait,
strict private/startup gates and the two corrected browser labels.

The first integrated tree `6566f1a52cc9703fd5107f8d49c84c01068dc66d`
passed 480 existing focused controls in 50.22 seconds (51.44 seconds including the
runner). They cover internal/history identity and exclusion, links and document
dispositions, architecture, guide redirects, the plugin census, release policy,
and owned-loopback HTTP transport. There were no failures, errors or skips.
Ruff, formatting, the private-access audit, the current workflow's full strict
type target union and seven documentation modules also passed. These are source-
scoped local results; the earlier 458-case preparation receipt remains historical.

The exact focused command was:

```sh
uv run python -m pytest -q tests/quality/test_internal_docs.py tests/quality/test_documentation_links.py tests/quality/test_documentation_structure.py tests/quality/test_architecture_docs.py tests/quality/test_user_guides.py tests/contract/test_plugin_examples.py tests/quality/test_release_policy.py tests/quality/test_release_transport.py --basetemp=/tmp/kuberich-226-docs-v170ybg9/pytest --junitxml=artifacts/issue226/protected-857f/tests.xml
```

After that cohort, capability evidence paths were reconciled directly from the
actual parent's data to the selected relocation aliases, preserving all other
capability values. The checkpoint received this measured note. Final reference,
plan and both site-mode build checks apply to the resulting candidate separately.
These checks do not certify a new native artifact, provider, performance result
or hosted deployment. They do not resolve the parent Fast-retention failure.

Final reference validation and module-plan validation passed, including 895 local
Markdown links. Both offline site modes passed: preview output had 43 pages and
1,508 local links/assets; public-mode output had 23 pages and 799 links/assets.
The strict workflow union covered 234 source files, and the supplemental docs
check covered seven files. Both builds still report source version 0.2.0 and
perform no publication.

## Reproducible historical-source setup

Repository checks and Quality test shards now fetch the existing PR 277 and
PR 290 head refs once, in explicit setup steps bounded to two minutes. The same
command is documented for contributors. Normal Markdown validation remains
offline and fail-closed, with all 105 receipt identities and payloads unchanged.
Current-only site builds, release-byte verification and installers do not need
these original historical Git objects.

A clean isolated reachable-only checkout of the local `9ea3523` candidate lacked
the `1875994` source commit before setup. An actual bounded fetch from the two
existing GitHub PR refs supplied it; all 105 original contexts and the offline
plan check then passed. There were no alternates or copies of the shared object
store. This proof uses explicitly local candidate ancestry for `aad1a0b2`: the
descendant is not public yet. Remote PR 290 already contains `dd0a67ee`; its normal
descendant push will also retain the candidate's `aad1a0b2` ancestry. No synthetic
ref, tag, source binding or protected-main claim was created.

The focused documentation/workflow follow-up passed 106 controls in 17.13 seconds
(18.16 seconds including the runner), with no failures, errors or skips. It
covered the existing link, internal-record, disposition and CI-policy controls,
including both bounded setup/order assertions. Ruff, formatting and whitespace
checks also passed. Receipts are retained separately under
`artifacts/issue226/source-history-setup/`; the earlier 480-case evidence remains
unchanged and source-scoped. At that setup checkpoint, public delivery still awaited review and the separate
parent Fast-retention prerequisite; the reviewed integration follows below.

## Parser result-ownership prerequisite

The separately reviewed prerequisite
`3feefd3bcdc846e5a83bed31846b2deee9d13f61` is merged normally into this candidate.
The original automatic-main failure `41444530467` / `125274306280` remains
retained. Its weak-reference assertion exposed a real executor/Future lifetime:
a completed parser could retain the initial resource payload during a live
DELETE even though the consumer kept no history.

`parse_owned` now transfers the parsed value through an owned cell, leaving the
executor completion result as `None`, and clears the cell after handoff or
cancellation. Cancellation/error draining is preserved. The original watch
oracle and watch-function ASTs remain unchanged. The new regression holds the
initial worker at the same publication barrier and checks the weak reference at
the live DELETE, before allowing worker drain; it does not add a wait or GC call
to the original oracle.

The prerequisite's independent verification passed 303 controls and strict/static
checks. Its exact `parse_owned` coverage was 18/18 executable lines and 2/2
branches; changed executable-line coverage was 17/17. These measurements belong
to that reviewed prerequisite source, not a repeated local campaign here.
Final integration checks and complete current-head CI remain separate.

The necessary exceptions to protected-parent byte preservation are explicit:
`src/kuberich/services/resources.py` and the added retention regression in
`tests/contract/test_watches.py` carry this reviewed fix; two CI setup steps fetch
existing PR histories before offline source validation. Other runtime behavior,
packaging, qualification gates and unrelated tests retain the protected parent.
All 105 historical payloads and source receipts remain exact. The source version
stays 0.2.0; no artifact, website or hosting publication is performed.

The frozen integration `59c572eb1136d10005df5f4d92d85993387ef042`
passed the original and new retention cases together with the existing internal
history, link, disposition and workflow controls: 108 cases in 17.08 seconds
(18.12 seconds including the runner), with no failures, errors or skips. The
exact command was:

```sh
uv run python -m pytest -q tests/contract/test_watches.py::test_deleted_initial_records_are_released_when_consumer_keeps_no_history tests/contract/test_watches.py::test_initial_parser_completion_retains_no_deleted_record_while_worker_unwinds tests/quality/test_documentation_links.py tests/quality/test_internal_docs.py tests/quality/test_documentation_structure.py tests/quality/test_ci_policy.py --basetemp=/tmp/kuberich-226-integration-_vqnp4d4/pytest --junitxml=artifacts/issue226/parser-integration/tests.xml
```

The current 234-file strict workflow union, seven documentation modules, Ruff,
formatting, private-access audit, checked references and plan validation all
passed. The plan validates 896 local Markdown links. Because `resources.py` is
an enrolled site input, both offline outputs were rebuilt and checked: preview
43 pages / 1,508 links and assets, public mode 23 / 799, with 20 canonical
documentation pages and version 0.2.0 in both. Their manifests perform no
publication. The final evidence-only checkpoint note changes no enrolled input.

Receipts remain separate under `artifacts/issue226/parser-integration/`. These
108 integration cases, the earlier 480 documentation cases, the 106 setup cases
and the prerequisite's 303 cases overlap and must not be added together. They
do not substitute for fresh complete current-head hosted/native CI, which is
still pending, or for release/provider/performance qualification.

## Internal evidence delivery

The internal-evidence candidate was delivered through PR 290 at protected squash
`13a6c5cc8da72c36a360d2a68f07553c2959889a`, tree
`f75eed2feffeddbe161d49581f9ead786654829b`, with sole parent `857f9ad`.
Its exact `e67183c` source passed all 27 selected Quality jobs, including four
native targets, with matching Repository checks and DCO. The original failed
main run and the earlier local cohorts remain retained and source-scoped.
No release or website publication was part of that source delivery.

## User-focused release history

The release-history migration preserves the reviewed published 0.1.0 and 0.2.0
user changes, both authored notes, and the existing frozen-note contract. The
published mapping keeps all 168 original blocks: 148 user-change blocks map to
134 concise changelog entries or note sections, and 20 maintainer-only blocks
have explicit removal reasons. All three original source blobs retain their
protected `919f617` identities. Existing measured preparation receipts remain
historical; they do not qualify this integration.

Unreleased now records the actually inspected protected `13a6c5c` changelog,
not the older prepared `3c8745c` parent. Its 24 source blocks map to concise
current benefits, including captured Basic masking and fatal UI terminal/crash
report recovery. A further entry describes releasing deleted-resource memory
during live updates, from the delivered parser prerequisite. The stale pending
startup-policy binding is removed without inventing a replacement source.
The published tail and its mapping are unchanged. Every change remains one
plain-language line with at most 25 visible words; internal process stays out of
the user release copy.

The current 105 immutable records, three operational inputs, maintained
checkpoint/acceptance pages, corrected browser evidence, parser retention fix,
qualification gates and two explicit history-fetch setup steps are preserved.
The document inventory adds only the map and author template, for 339 entries.
Fork-clone instructions remain with the separate contributor-guidance task.
Source version remains 0.2.0. No production code changes, package/tag/release,
remote release-body edit, website/DNS change or other publication is included.
Fresh local checks and complete current-head hosted qualification are pending.

The frozen integration `e2394e4e02788fba780e4bd49cd4f7eae6dc4f47`
passed 149 existing release-history, frozen-note, owned-HTTP transport, internal
record, link and document-disposition controls in 39.20 seconds (40.43 seconds
including the runner), with no failures, errors or skips. The exact command was:

```sh
uv run python -m pytest -q tests/quality/test_changelog_style.py tests/quality/test_release_notes.py tests/quality/test_release_transport.py tests/quality/test_internal_docs.py tests/quality/test_documentation_links.py tests/quality/test_documentation_structure.py --basetemp=/tmp/kuberich-227-docs-pg1otc8k/pytest --junitxml=artifacts/issue227/protected-13a6/tests.xml
```

The actual workflow strict union (234 files), seven documentation modules, Ruff,
formatting, private-access audit, checked references and the 899-link module-plan
check also passed. Both previously qualified offline site manifests still match
every enrolled input; no redundant standalone rebuild was run. The focused
controls include current navigation/site exclusion and document dispositions.
Production executable code is unchanged, so changed-production coverage is N/A,
not a new 100% result. Complete current-head hosted/native CI remains pending.
Receipts are under `artifacts/issue227/protected-13a6/`. These source-scoped results
make no new release, installation, provider, performance or publication claim.

## Release-history delivery

PR 292 delivered the user-focused release history at protected squash
`614f3f89f314cfc1a98dc0e2ac753506ce257ce5`, tree
`5d97314de68af2fdf9ec0023e2e79bf99d2fb929`, with sole parent `13a6c5c`.
The exact `11aff35` head passed all 27 selected Quality jobs, including four
native targets, plus matching Repository checks and DCO. The 149 local controls
remain source-scoped evidence. No remote release body or publication changed.

## Current contributor essentials

Active agent, contributor and quality instructions now keep the current delivery
contract, boundaries and verification policy within 60, 150 and 250 lines.
Bug, feature and task forms link the shared contract instead of copying it.
The global limit remains ONE implementation issue, with agent ownership inside
that issue. Continuous authorized source delivery, existing approvals, local
maintainer identity/sign-off, explicit domain-purchase/publication approval and
owned disposable-cluster rules remain intact.

Three exact pre-condensation instruction snapshots and their source/hash receipts
are kept maintainer-local from actual protected `614f3f8`, outside tracked source
and public CI. Existing public Git history and all 105 historical payloads/origins
remain unchanged; internal records in a public repository are not confidential.
The public inventory adds only the new task form, for 340 documents, with the
same three operational JSON inputs and 100 historical aliases.

Fork contributors now fetch the existing PR 277/290 histories explicitly from
the canonical HTTPS URL without changing remotes. Validators remain offline and
fail closed. The current checkpoint and acceptance links remain accessible;
qualifier guidance names the full current strict/private/startup stage sequence.
The quality policy states both startup and runtime/collection latency as advisory
for 0.x, preserving every original budget, actual miss, strict opt-in, major-1+
enforcement, strict negative control and hard resource/functional/ownership gate.
Actual-parent architecture, release instructions, runtime, qualification stages,
CI setup and unrelated tests are unchanged. Source version remains 0.2.0;
production changed-code coverage is N/A, not a new 100% result.

A later automatic-main Python 3.14 shard failed job `125357973367` while opening
the HTTP watch in the independent bounded server-interval case `[0.1-1]`, with
`ConnectionProblem TIMEOUT`. The original artifact `13154722289` is retained by
its owner. Cause is under diagnosis; this documentation work changes no watch
assertion or budget and does not resolve that result. Delivery remains held for
the reviewed prerequisite and fresh candidate qualification. Local verification
and complete current-head hosted/native results are still pending here.

The frozen documentation source `226703d9b00ec8f9ade9a318520c7902ae71afe8`
passed 95 focused contributor-policy/form, link, internal-record, disposition and
architecture controls in 21.16 seconds (24.80 seconds including the runner), with
no failures, errors or skips. The exact command was:

```sh
uv run python -m pytest -q tests/quality/test_contributor_essentials.py tests/quality/test_documentation_links.py tests/quality/test_internal_docs.py tests/quality/test_documentation_structure.py tests/quality/test_architecture_docs.py --basetemp=/tmp/kuberich-228-docs-7u06ojn6/pytest --junitxml=artifacts/issue228/protected-614f/tests.xml
```

The current strict workflow union (234 files), seven documentation modules,
Ruff/format/private-access, checked references and the 885-link module-plan gate
also passed. Both qualified parent site manifests match every enrolled input;
no redundant standalone rebuild was run. Existing navigation/site-exclusion
controls passed. These are documentation-only results: production coverage is
N/A and no provider, performance, installation or native qualification is inferred.
Receipts are under `artifacts/issue228/protected-614f/`. The parent watch-open
failure remains under diagnosis, and fresh complete current-head hosted/native
CI and public delivery remain pending.

## Reviewed test-contract prerequisites

The automatic-main run for protected `614f3f8` terminated as FAILURE: 20 jobs,
16 success, three failure and one skip. Two original source shards failed, and
the aggregate gate failed. The originals retain the watch server-interval
`[0.1-1]` HTTP-open timeout and the aggregate source-picker retired/table-count
assertion. The original controller comparison was false and close metadata was
missing; later controls do not establish a unique historical cause or a product
fix. Canonical failures and those diagnostic limits remain retained.

Reviewed child `36e01250d1242f230038872acc8ed9279ac92b0e` changes only the watch
interval test and its public aiohttp imports. It checks all four actual production
interval/request/ClientTimeout values at the public HTTP-call boundary, including
None establishment, EOF and cleanup. Existing real-HTTP deadline, renewal and
cancellation controls remain byte-exact; no product API, budget or runtime code
changes. Its source-scoped watch/pipeline cohort passed 84 cases in 13.56 seconds
with static checks; those helper results are not a repeated campaign here.

Reviewed child `f0a25faf28abdc89a486ce1c7cdaaca3c13903be` adds exactly one wait
for retired ownership 64 AND the mounted picker table's 67 rows, immediately
before the original assertion. Every assertion, 34-cycle loop, 0.3-second pause,
helper budget, UID/Space/Escape check and production byte stays unchanged. The
same-public-gate fixed comparison passed one case in 5.54 seconds; the four-file
aggregate cohort passed 138 cases with Ruff/format/private and 195-file helper
strict checks. The controller/metadata limits above remain part of that evidence.

Both reviewed children are merged normally into the fresh delivery branch.
They are explicit necessary TEST-ONLY exceptions to otherwise exact protected-
parent preservation. Original 95-case documentation, 84-case watch/pipeline and
138-case aggregate receipts remain separate, source-scoped and unsummed. No new
application coverage, runtime qualification or unique-cause claim follows from
these controls. The final combined selection, actual workflow strict union and
fresh complete current-head hosted/native qualification remain pending.

The combined frozen source `999408a907ba4737723d155ca90e3fb67aed766e`
passed exactly 100 selected cases in 23.05 seconds (24.22 seconds including the
runner), with no failures, errors or skips: the five documentation/policy files,
all four watch interval values and the target source-picker UI case. The command was:

```sh
uv run python -m pytest -q tests/quality/test_contributor_essentials.py tests/quality/test_documentation_links.py tests/quality/test_internal_docs.py tests/quality/test_documentation_structure.py tests/quality/test_architecture_docs.py tests/contract/test_watches.py::test_watch_server_interval_is_an_independent_bounded_integer tests/ui/test_aggregate_logs.py::test_source_picker_uid_recreation_expired_selection_and_manual_space --basetemp=/tmp/kuberich-228-integration-k4l0_811/pytest --junitxml=artifacts/issue228/final-integration/tests.xml
```

The actual workflow strict union (234 files), seven documentation modules,
Ruff/format/private-access, checked references and module-plan validation passed.
Both previously qualified site manifests still match every enrolled input; no
standalone rebuild was needed. All five forbidden ancestry guards, private-copy
permissions, 105 historical identities, three operational inputs, 100 aliases and
340-document inventory remain intact. Original and helper cohorts stay separate;
no broad 84/138/full/native campaign was repeated. Production coverage remains N/A.
Receipts are under `artifacts/issue228/final-integration/`. Fresh complete current-
head hosted/native qualification and root-reviewed public delivery remain pending.

### Contributor-guidance CI correction

The first PR #303 source `869cccf462d6c2f02acc1a1195d12c169898cf3e`
did not qualify. Application quality run `41481687428` ended with 24 jobs:
20 successful, two failed, one cancelled and one skipped. The idle-timeout
backoff test recorded `[0.25, 0.5, 0.25, 0.5]` instead of the expected three
delays; the aggregate gate failed and the Application matrix stayed skipped.
The cancelled macOS part had no acquired runner or test steps; its original
annotation identifies hosted-runner acquisition capacity. All four native jobs,
Repository checks and DCO passed, which does not replace the failed qualification.

One controlled execution of the unchanged original test retained its failed
assertion. Actual HTTP 503/503 responses, one LIVE observation and the 2.1-second
idle-body timeout correctly produced the expected reset to 0.25 seconds. Only
then, a controlled delay before the incidental final request was cancelled by
the unchanged 0.1-second handshake deadline, adding the extra 0.5-second backoff.
This proves a sufficient route, not the unique historical hosted cause. The
original failure, raw control failure and cleanup/source receipts remain intact.

Reviewed child `1026e18b23d914f2cb6083cb7e0e8cd1ee32d13a` changes only
that test. LIST setup uses its ordinary deadline; the intended watch phase keeps
0.1 seconds and the enclosing run keeps five seconds. The test stops through
the existing `Finished` control after recording the third sleep. It still
requires real HTTP 503/503, one LIVE state, the actual idle TIMEOUT, exact delays,
checkpoint and request counts, plus drained handlers and a closed client pool.
All other functions, shared fixtures, production code and hard controls are exact.

The child passed 84 watch/pipeline cases in 14.52 seconds (18.09 with the runner),
with no failures, errors or skips. Ruff, formatting, private-access checks and
the actual workflow strict union of 234 files passed. All owned local commands and
the original CI observer are reaped. Root and independent review approved the
change; it is integrated without rewriting the published parent. Receipts are
under the helper's `artifacts/issue228/idle-backoff-contract/` and the delivery's
`artifacts/issue228/root-tracking/`. Combined integration checks and fresh complete
current-head hosted/native qualification remain pending. Source version is 0.2.0;
no application coverage percentage or release/publication follows from this fix.

The corrected combined frozen source `922e2340d8ef754d3fac9e39ef092cf19b8e55ae`
passed 101 cases in 25.68 seconds (26.88 with the runner), with no failures,
errors or skips. This is the earlier 100-case documentation/interval/picker
selection plus the corrected established-idle-timeout case. The exact invocation,
source and owned-process receipts are in
`artifacts/issue228/idle-integration/tests-command.json`; canonical output is
`tests.xml` and `tests.log` in that directory. The source stayed unchanged through
the run; the child/process group and private test directory are gone. The
helper's strict/static input files are byte-identical after this checkpoint-only
integration. The earlier 84-case cohort and original failed control remain
separate source-scoped records. Fresh complete current-head hosted/native CI
is still required before protected delivery; no unchanged CI attempt was retried.

## Documentation quality and current media checkpoint

Protected source `af6beb02318a31ed196e4bd880e563f23659baf9` delivered the
contributor-policy changes and scoped watch/picker test corrections with all 27
pull-request jobs, four native runners and matching Repository/DCO checks.
Its automatic-main [Quality run 41494869111](https://github.com/carloshm91/kuberich/actions/runs/41494869111)
was cancelled on attempt one: Fast job `125447165896` reached the unchanged
15-minute deadline at 99% without naming the remaining node. Of six instantiated
jobs, one passed, one was cancelled, the gate failed and three were skipped;
no native qualification ran. Repository run `41494869103` passed. Original
artifact `13167985028` remains intact (SHA-256
`b742493b5010341b678191266d4156abe0b60983f636dd43015548693ee756e8`).
The retained four controlled children completed and drained, but this does not
identify every unfinished test or establish a unique cause. The next required
run keeps the selection, workers, controls and deadline, adding public verbose
node logging and a nonfatal 60-second Python stack dump for diagnosis. No
unchanged CI attempt is retried, and no product hang fix is claimed.

Frozen documentation source `35c280aa131ddabcd9313159902e9754920afe61` passed
246 focused documentation, capture, site, link/history, contributor, architecture
and CI-policy cases in 95.11 seconds, with zero failures, errors or skips. Ruff,
formatting (861 files), the actual workflow strict union (234 files plus nine
documentation modules), private-access checks, generated references and the
module plan passed. The 340 disposition rows, 105 immutable payloads/origins,
three operational source receipts and 100 relocation aliases remain unchanged.
Production code and its coverage inventory are unchanged; changed production
coverage is not applicable.

Required source/link/navigation/publication checks passed for 20 user pages and
885 local Markdown links. The retained report contains four prose advisories and
15 bounded public HTTPS observations: 14 reachable URLs and one 301 marked for
review. Redirects and external fragments were not followed or certified.
Per-page length, STYLE and Markdown observations remain advisory for 0.x.

Both images were freshly rendered from clean committed source
`fba017cb540efc3b7ae940c5272081c7aa61411b`, application tree
`cbc45d9f9cf427c99674dc7c612eddd4f90ecec6`, version 0.2.0. The command used
no historical image import and no ambient kubeconfig. Synthetic loopback data
produced five resource requests and one log request; redaction, released client
and API, closed pool/stream, zero active handlers and removed temporary directory
were checked before writing the images. Both vectors and the landing rendering
were visually reviewed. Earlier recorded media remains historical in Git.

Fresh preview/public builds and checks passed with 43/23 HTML pages and
1,508/799 checked links/assets. The unchanged browser verifier passed 43 desktop
and 43 mobile pages in 80.135 seconds: no accessibility violations, browser
failures or external requests, with keyboard, no-JavaScript navigation, clipboard
success/denial and overflow controls intact. The preview browser run does not
claim public-host navigation or screen-reader certification. Its process was
reaped and process group absent; owned browser/server cleanup completed. Locked
browser-tool audit reported zero vulnerabilities.

Canonical local receipts are in `artifacts/issue229/local/`: `tests.xml`,
`static.json`, `site-commands.json`, `browser-command.json` and `verification.json`.
The retained advisory/browser reports are under `artifacts/site-qa/`; actual
capture inputs/results are under `artifacts/issue229/capture-fba017c/` and the
tracked media inventory. Fresh complete current-head hosted/platform CI remains
pending. Source version stays 0.2.0; no publication or release is performed.

## Prepared 0.3.0 source checkpoint

Protected `6384fb1a25ac19b8c494cc6fb1b87e6d28bfaac4` delivered documentation
quality and current synthetic media through PR #304 with all 27 required PR jobs,
four native runners and matching Repository/DCO checks. Issue #230 now prepares
the source version and authored notes before freezing the final qualification
candidate. This preparation does not complete the foundations gate.

The source/own lock version is 0.3.0 without dependency upgrades. Published
0.1.0/0.2.0 records and notes remain unchanged. The new authored note has one
baseline-null disposition; all 340 earlier rows, 105 immutable origins/payloads,
three operational source receipts and 100 aliases remain unchanged. Exactly two
existing census expectations change from 340 to 341 for that new document.
Runtime, Q17, architecture, workflow policy and all other tests remain unchanged.

The existing media remains a recorded clean 0.2.0 render from source `fba017c`,
not newly captured 0.3.0 evidence. The real 0.3.0 preview must rebuild both site
surfaces. Public indexing must reject unpublished 0.3.0 against the unchanged
publication inventory; existing published fixtures cover that separate mode.
Local preparation results follow below. Full exact-main qualification, owned-cluster
repetitions, installations and the six-environment release matrix remain pending;
no manual CI, tag, package or site is published.

Source `2eabe106a687efb25325caa49af051cb7b2780ac` passed 508 focused
release-note/policy, document-history/link/structure/schema/site and CLI cases in
98.34 seconds, with zero failures, errors or skips. Its strict workflow union
(234 files plus nine documentation modules), Ruff/formatting (862 files),
private-access audit, neutral reference check and 890 local Markdown links passed.
The new source imports from this checkout and both CLI version forms report 0.3.0.

The 0.3.0 preview rebuilt both surfaces and passed 43 HTML pages and 1,508
links/assets. Public indexing correctly rejected unpublished 0.3.0 before creating
output; existing published 0.2.0 fixtures passed their public-mode regressions.
The existing browser verifier passed 43 desktop and 43 mobile pages in 80.393
seconds, with zero accessibility violations, browser failures or external requests;
keyboard, no-JavaScript, clipboard and overflow controls passed. The browser/server
closed, its process was reaped and process group absent. This checks preview bytes
and does not qualify or deploy a public 0.3.0 site.

The authored note now uses durable user-facing installation, upgrade and removal
commands for the existing channels, with 0.2.0 as the actual upgrade baseline.
Those commands are qualification targets, not claims of current 0.3.0 availability.
Preparation status stays here and in Unreleased instead of becoming permanently
pending prose in an immutable public release body. The original source-scoped
508-case, static, browser and note-freeze receipts remain under
`artifacts/issue230/preparation/`; focused revised-note checks remain separate.
The coordinator is still reviewing the installation-upgrade baseline before any
final source freeze. This preparation does not complete #230 or authorize publication.

## 0.3.0 preparation: published upgrade coverage

The reviewed installation correction is integrated after the durable-note change.
It preserves the existing private RC-to-stable source rehearsal and adds the real
published predecessor, selected strictly below the candidate version. Source
upgrades use the recorded 0.2.0 formula at
`cbe421cac5331407771b7b82279d69b533665cd2`; bottle upgrades use its reviewed
bottle-only update at `a878dbd38d7ae0ac81fd9fcba37b4b104bad641d` and require an
actual baseline pour. Both bind the published source
`344222174a85868bb7836ecd1fcc91e15f65d269`. Existing version, old-keg,
configuration, PTY, cold/warm install and removal assertions remain enforced.

Independent review checked the four test/support changes and retained public
formula, distribution and bottle metadata. The isolated source passed 55 offline
cases in 12.93 seconds, Ruff/formatting (863 files), the private-access audit and
the actual strict workflow union (234 files). These results establish neither
native installation nor an actual pour. The corrected six native installation
jobs remain required on the final protected 0.3.0 source.

The revised public note separately passed 34 cases; those are not added to the
earlier 508-case cohort. Its frozen body is unchanged by the installation
correction. Final combined preparation checks follow on the integrated candidate;
full exact-main qualification, three contract/owned-cluster rounds and a fresh
30-minute sustained workload remain pending. No runtime, dependency, workflow,
runner, permission, numeric budget or publication policy changed.

## 0.3.0 qualification: Python upgrades and fixture publication

Protected `5fa8641153ed77895490d8d0b1f682eae4cee8f5` merged preparation
through PR #305 after all 27 PR quality jobs, Repository/DCO and six native
Homebrew jobs passed. Its automatic main run passed all 22 jobs, but the
[manual full-matrix run](https://github.com/carloshm91/kuberich/actions/runs/41535651646)
failed. A descendant-control collector read a created-but-empty PID file;
its later reaping assertion failed. The aggregate failed and the application
matrix did not run. All four native builds passed, but neither they nor the
automatic run qualify the failed manual matrix. The original failure is retained.

The installation review also found that Python-manager upgrades covered only a
private RC with identical application payload. Source
`29ae374a9c54320f4ba2dfde9e5adce2696467e3` adds the actual published 0.2.0
wheel while retaining both RC cases. All four real uv/pipx upgrades and 11 offline
pin, metadata and dependency controls passed locally on Linux CPython 3.12.12.
The old wheel's SHA-256 matches official PyPI and GitHub records; its actual
payload differs from the current 0.3.0 wheel. Existing normal no-op/upgrade,
configuration, installed navigation/shell and uninstall assertions remain.

The partial 5fa sustained workload was explicitly cancelled after 470 seconds
for this further source correction. Its source stayed unchanged and owned CLI,
API and process groups drained. It is a cancelled diagnostic, not a completed
30-minute observation. The fixture correction now publishes the complete owned
PID atomically. Both existing control variants passed on CPython 3.13.12 with
their real descendant, unrelated-process, cancellation, forced-termination and
cleanup assertions unchanged; command owners drained. Combined checks and
fresh final-source qualification remain pending. No product, workflow, deadline,
coverage or publication policy is relaxed.

## Interrupted PID publication in verification helpers

PR #306 delivered the Python-upgrade and descendant-fixture corrections at
protected `1075d6833d9c4e42808bae103978b6bd569cfae9` after all 27 PR
quality jobs and Repository/DCO checks passed. Its automatic-main Fast run
`41654279758` failed a different fixture: the cancelled X11 reader created its
PID file before completing its contents. Cancellation could interrupt that write;
the later integer read failed even though the runner's zero-active-process check
passed. The original log and failed result remain retained. An unchanged passing
manual Fast occurrence does not correct that race.

The correction publishes complete owned PID files atomically in the X11 reader
and two equivalent forced-timeout fixtures for installer and cluster-process
cleanup. These two preventive paths were identified by source inspection; no
historical failure is claimed for them. Original cancellation, process/group
checks and deadlines remain unchanged. A source-scoped audit found the other
terminal/UI/support publishers already atomic or synchronized through completed
output or readiness markers.

The partial 1075 workload was cancelled after 271.43 seconds for this tracked
correction. Its source stayed clean and all five owned processes and three
groups drained. It does not establish normal-finish terminal restoration or a
complete memory plateau. Final corrected-main qualification remains required;
no production, workflow, coverage, budget or publication policy is relaxed.

## O01 #68: resource metrics implementation checkpoint

The source now reads current metrics through the selected per-context client,
with discovered API versions, serialized 15-second batches and 60-second sample
expiry. Pod/workload/Node/container rows keep numeric sorting and UID selection.
Availability states, missing/zero denominators, uncertain complex Pod budgets and
vendor-neutral extended-resource capacity/requests remain explicit. No Metrics API
installation, Prometheus, historical chart, package or website publication occurs.

The initial focused command passed **135 tests** on Linux CPython 3.12.12; later
source corrections and qualification results are in the acceptance record:

```sh
uv run pytest tests/unit/test_metrics.py tests/unit/test_metrics_projection.py tests/contract/test_metrics.py tests/ui/test_metrics.py tests/ui/test_pods.py tests/ui/test_interactions.py -q -n 4 --tb=short
```

The open-container Pilot trial refreshes values through measured zero, 403, 404
and valid data, then expires the last good sample while a subsequent HTTP read
is held. Scope/context/exit contracts close actual local HTTP reads and preserve
the synthetic kubeconfig. Full source verification is recorded separately in
[resource metrics acceptance](acceptance/resource-metrics.md); this focused
checkpoint does not claim hosted/native/provider or release qualification.

The later owned context/native-resource trial passed in **83.7 seconds** on
frozen `a553ab6`, including exact real ordinary-Pod budget cells and independently
uncertain init/Node allocation cells. The complete local suite retained
**7,450 passed / 1 fixture-size failure / 5 native-only skips**; its valid OSC52
oversize refusal exposed an unbounded success-copy fixture. The corrected
source/installed-console/installed-module and refusal family passed **54 cases
with 1 macOS-only skip**, requiring actual decoded 54,611-byte clipboard frames
and terminal cleanup. The [acceptance record](acceptance/resource-metrics.md#owned-trial-and-retained-full-source-results)
has the exact commands, failed-suite coverage measurements and original failure
receipts. Current-head hosted qualification remains pending; these focused
corrections do not convert the original failed campaign into a pass.

Independent review then found and corrected main-table cache expiry when AGE
refresh is long and a subsequent metrics request remains pending. One owned
batch deadline now publishes `metrics cache expired` independently of AGE/read
completion, retaining budgets, original timestamps and selection. A conservative
batch can expire a newer member early; it does not invent an older sample time.
The focused metrics family passed **186 cases**, including actual Pod/Node/workload
cells, fresh replacement, scope/context/exit cleanup and repeated cancellation
during timer retirement. The [expiry acceptance](acceptance/resource-metrics.md#main-table-expiry-independent-of-age-and-pending-reads)
records the command and measured module coverage. Current-head hosted full
qualification remains pending for the integrated metrics head; original reports are retained.

The branch now integrates completed 0.3.0 delivery from protected main
`25265acfa2424a89bec275bf016b255db3b3448a` without changing its published
registry, release notes, changelog history or dependency lock. The integrated
metrics focus passed **186 cases in 18.19 seconds**; all three new critical
deterministic modules measured 100% lines/branches, and the I/O poller measured
98.204%/92.188%. Static/type/plan/reference checks and **140 documentation/site
contracts** passed. All 198 production-file hashes remained unchanged. See the
[integration record](acceptance/resource-metrics.md#integration-after-completed-030-delivery)
for exact commands and limits. Hosted current-head gates remain pending; these
checks do not replace the retained failed full-suite campaign or qualify a release.
