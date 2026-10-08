# First things to try

## Initial private website checkpoint: #150

The initial landing and sixteen user guides now build locally from the maintained
repository documentation. Both the landing with `/docs/` and a separate root docs
host are prepared. The actual tested command is `uv run python -m scripts.build_site`;
`uv run python -m scripts.check_site` validates the generated output.
Local preview is `uv run python -m http.server 8715 --bind 127.0.0.1 --directory artifacts/site/www`.
Read [site instructions](website.md) and [acceptance evidence](acceptance/initial-website.md)
for measured checks and pending candidate/publication limits. Nothing has been
published; DNS and private repository visibility are unchanged. Continuous private
work does not require an intermediate maintainer trial.

## KubeRich identity checkpoint: #149

The maintainer chose **KubeRich** and confirmed purchasing `kuberich.com`.
Canonical checkout commands are:

```sh
uv sync --locked --group dev
uv run kuberich --version
uv run kuberich --help
uv run kuberich
```

The `kubetrol` console alias still launches the same application. Existing
preferences are read in place, and `kuberich config migrate` explicitly creates
the new file while retaining the original. See [configuration compatibility](configuration.md).
The repository is now `carloshm91/kuberich` and remains private; its old URLs and
SSH address redirect to the preserved repository. [Acceptance evidence](acceptance/identity-migration.md)
records 2,977 passing cases on each Linux Python 3.12/3.13/3.14 interpreter,
above 99% lines and 97% branches, and 100% critical/changed-line coverage.
Actual source/installed terminals, uv/pipx alias install/uninstall and all eight
owned Kubernetes rehearsals passed. Native macOS/full hosted release qualification
remain pending. The exact installed rehearsal command was
`uv run python -m scripts.verify_quickstart --wheel /tmp/kuberich-149-evidence/frozen-dist/kuberich-0.0.1.dev0-py3-none-any.whl --kind /tmp/kubetrol-tools/kind --kubectl /tmp/kubetrol-tools/shell/bin/kubectl --evidence /tmp/kuberich-149-evidence/kind-quickstart.json`.
The temporary binaries and wheel in that earlier command were removed by an
environment restart after qualification. Regenerated packages/audits are retained
locally under `artifacts/identity-149`; the acceptance report records this limit.
Continuous private delivery does not require an intermediate maintainer trial.
Public installation, website/DNS and visibility changes remain separately
authorized launch steps.

Earlier checkpoints below preserve original tested commands and artifact names.

## Workload operations checkpoint: M03 #45

[Selected workload operations](workloads.md) add `:scale`, `:restart` and explicit
`:rollback` with Review/default Cancel/separate Confirm. `:rollout` reads actual
progress and works in read-only mode; Cancel does not claim a server undo.
The automated command is
`uv run python -m scripts.verify_workloads_kind --kind /tmp/kubetrol-tools/kind --evidence /tmp/kubetrol-45-evidence/kind.json`.
Actual Deployment and StatefulSet/DaemonSet rollback, narrow RBAC, HPA and failure/
cancellation checks passed on an owned cluster, which was deleted.
[Acceptance evidence](acceptance/workloads.md) records 2,952 passing cases on each
Linux Python 3.12/3.13/3.14 interpreter, over 99% production lines and 97%
branches, and all 34 critical modules at 100%. Native source/fresh-wheel terminals,
builds and locked/fresh dependency audits also passed; native macOS and the full
hosted release matrix remain outstanding.
Private work proceeds without intermediate maintainer trials;
public installation/release remains separately gated.

## Manifest edit checkpoint: M02 #44

The preview adds [selected manifest editing](editing.md) through `:edit` / Shift+E:
explicit local disclosure, native editor, redacted diff, strict server dry-run
and separate guarded Apply. Cancel has default focus; `--readonly` blocks edits.
The automated command is `uv run python -m scripts.verify_editing_kind --kind /tmp/kubetrol-tools/kind --evidence /tmp/kubetrol-44-evidence/kind.json`.
All 12 real API checks passed on an owned disposable Kubernetes cluster, which
was deleted. [Acceptance evidence](acceptance/editing.md) records 2,836 tests
passing on each Linux Python 3.12/3.13/3.14 interpreter, independent coverage gates
above 99% lines and 97% branches, and all 33 critical modules at 100%. Actual
foreground-editor and fresh-wheel terminal trials also passed. Native macOS and
full hosted release qualification remain outstanding.
Secret manifest disclosure, scale/rollout and deletion retain their separate
tasks. Continuous private work does not require an intermediate maintainer trial.

## Guarded write checkpoint: M01 #43

The preview adds [explicit annotation changes](mutations.md): `:annotate` prepares
an identified change, Review shows context/namespace/name/UID/version/effect, and
deliberate Confirm sends one guarded patch. `:writes` retains public outcomes;
`--readonly` blocks modifications. Editing, scaling and deletion remain separate
tasks. The automated command is `uv run python -m scripts.verify_mutations_kind --kind /tmp/kubetrol-tools/kind --evidence /tmp/kubetrol-43-evidence/kind-final.json`.
Actual writes, stale UID/version refusal and real RBAC denial passed on an owned
disposable cluster, which was deleted. See [acceptance evidence](acceptance/mutations.md)
for final qualification status: 2,730 tests passed on each Linux Python
3.12/3.13/3.14 interpreter, independent coverage gates passed, and all 32 critical
modules reached 100%. Native source/fresh-wheel terminal and actual Kubernetes
behavior passed; full macOS/hosted release qualification remains pending. Continuous private delivery does not require a
manual maintainer trial at this checkpoint.

## Port-forward checkpoint: S05 #42

The preview adds [managed pod/Service TCP forwarding](port-forwards.md): Shift+F
on a selected pod/Service opens mappings; `:pf` lists and `s` stops selected.
Forwards survive namespace changes and stop on context/retry/exit. The automated
owned-cluster command is `uv run python -m scripts.verify_port_forwards_kind --kind /tmp/kubetrol-tools/kind --kubectl /tmp/kubetrol-tools/shell/bin/kubectl --evidence /tmp/kubetrol-42-evidence/kind.json`.
Actual Pod/Service HTTP and cleanup passed on a newly owned disposable cluster;
see [acceptance evidence](acceptance/port-forwards.md). Source/package publication
and full hosted/macOS release qualification remain separate gates. Continuous
private implementation proceeds without requiring intermediate manual trials.

## Standard resource checkpoint: B05 #41

The preview adds 15 [standard resource tables](standard-resources.md). An initial
scoped launch is `uv run kubetrol --context YOUR_CONTEXT --readonly --command 'deploy YOUR_NAMESPACE'`.
Use `:deploy`, `:svc`, `:job`, `:cm`, `:sec`, `:no`, `:pvc`, `:pv` or `:sc`;
Enter opens details and `y` opens redacted YAML. This checkpoint's automated
owned-cluster command is
`uv run python -m scripts.verify_contexts_kind --kind /tmp/kubetrol-tools/kind --evidence /tmp/kubetrol-41-evidence/kind-frozen.json`.
It passed with real LIST/WATCH/GET for every advertised family and removed its
disposable cluster. See [acceptance evidence](acceptance/standard-resources.md).
Scaling/editing and publication remain separate tasks. No intermediate manual
trial is required; continuous private implementation proceeds after verification.

## Private CI checkpoint: #109

The installed preview and launch command below are unchanged. Private development
uses all Linux Python minors plus one macOS baseline per PR; full six-environment
qualification is mandatory before release. Actual hosted after-change timing
remains pending while Actions cannot start. See [the usage audit](acceptance/private-ci.md).

## Current installation and trial guide: W01 #39

Use the [current quickstart](quickstart.md) for one ordered trial of the installed
preview. Checkout launch example:
`uv run kubetrol --context YOUR_CONTEXT --namespace YOUR_NAMESPACE --readonly`.
For a deliberately selected test scope, `--write` enables embedded shells even
when the preferences are read-only. Public 0.0.1/PyPI/Homebrew publication remains
pending #40; the source checkout reports `0.0.1.dev0`. Earlier sections below
preserve historical checkpoints.
The installed Linux candidate rehearsal passed with this exact command:
`uv run python -m scripts.verify_quickstart --wheel /tmp/kubetrol-39-evidence/target-3.13/canonical-rc0/release-candidate/dist/kubetrol-0.0.1rc1-py3-none-any.whl --kind /tmp/kubetrol-tools/kind --kubectl /tmp/kubetrol-tools/shell/bin/kubectl --evidence /tmp/kubetrol-39-evidence/quickstart-frozen-rc.json`.
It exercised read-only navigation/logs and a write-enabled embedded shell outside
the checkout, then removed its own installation and disposable cluster.
See [measured W01 evidence](acceptance/quickstart.md) for scope and limitations.

The installable CLI, local preferences and first terminal window are available
from the development checkout, including the live pod table, container logs and embedded shells. Use the latest
resource-workspace trial below; earlier sections record previous checkpoints and may name
short-lived branches that have since been deleted.
Current delivery continues without waiting for intermediate manual trials. The
maintainer will test the installed product and provide feedback later.

## Disposable-cluster checkpoint: Q01 #38

The preview remains usable. Integration scripts verify their generated API
endpoint against the actual owned Docker node before fixture writes and clean up
on graceful cancellation, failure and success. Tested command:
`uv run python -m scripts.verify_kind_lifecycle --kind /tmp/kubetrol-tools/kind --evidence /tmp/kubetrol-38-evidence/kind-lifecycle.json`.
It proves real setup cancellation, ready cancellation and injected body failure.
See [integration qualification](integration-testing.md) for tools and commands.
No additional resource view is claimed.


## Homebrew preparation checkpoint: D03 #37

The app UI and development version are unchanged. A canonical local RC now
produces a verified source formula and tap scaffold. Actual installation is
qualified in an owned Linux container; public tap creation and macOS/online checks
remain D04. The tested local check is
`uv run pytest -q tests/quality/test_homebrew.py tests/quality/test_release_transport.py`.
See [Homebrew delivery](homebrew.md) for candidate commands and limits. No new
intermediate manual trial is required.

## Release pipeline checkpoint: D02 #36

The installed pod/log/embedded-shell UI is unchanged. Release preparation now
verifies an exact candidate bundle, source identity and original artifact bytes;
publication is a separately reviewed workflow and is not available under the
current private/billing/protection restrictions. The exact local test command is
`uv run --locked --python 3.12 pytest tests/quality/test_release_policy.py tests/quality/test_release_transport.py tests/packaging/test_release_candidate.py`.
See [release pipeline](release-pipeline.md) for local-only candidate commands,
owner setup, complete matrix requirements and recovery. No tag/package is published.

## Dependency security checkpoint: Q04 #35

The terminal behavior remains the installed pod/log/shell preview below. Q04 adds
automated installed-runtime audits, original license notices and artifact-linked
SBOM evidence; it adds no new resource action. Its exact local preview command is
`uv run --locked --python 3.12 pytest tests/quality/test_supply_chain_policy.py tests/contract/test_hostile_boundaries.py tests/packaging/test_supply_chain.py`.
See [dependency security](dependency-security.md) for the full build/verify flow.
There is still no published package or release; hosted/macOS qualification remains
the public-release gate.

## Installed artifact qualification: D01 #34

The development launch remains `uv run kubetrol`. Local wheel/source builds now
exclude tests, development scripts, caches and undeclared private files while
retaining the complete application, styles, metadata and license.
Required packaging checks install both formats with real isolated `uv tool`
and pip-backed `pipx`, then exercise their exposed CLI and terminal outside the
checkout. They own and remove their tool installations.

The tested qualification command is:

```sh
uv run --locked --python 3.12 pytest tests/packaging
```

See [distribution](distribution.md) and [D01 acceptance](acceptance/distribution-artifacts.md)
for measured status. Public PyPI/Homebrew installation and version `0.0.1`
remain the separate release gate; no intermediate manual trial is required.

## Terminal reliability: Q02 #33

The same development command remains `uv run kubetrol`. The default shell stays
inside the interface. This checkpoint adds actual SSH/tmux checks and repairs
external shutdown, malformed shell sequences and text retention on resize.
SSH loss closes the application and its child outside tmux; a tmux session can
be reattached with the same embedded shell still running. Cancelling a shell
before its pod preflight completes returns to containers without launching it.

The tested terminal command and prerequisites are in
[terminal compatibility](terminal-compatibility.md), with final qualification in
[Q02 acceptance](acceptance/terminal-qualification.md). No intermediate manual
trial is required; macOS and physical clipboard certification remain explicit
public-release/environment checks.

## Azure helper contracts and explicit login: C07 #22

The workspace now has `:login` for the declared Azure kubelogin helper. Existing
sessions remain usable through normal `uv run kubetrol`; device/browser login can
use the native terminal explicitly, restore the UI and reconnect. Read-only mode
permits authentication while still blocking cluster actions. Tokens are captured
privately; native prompts use stderr, and stdin follows Never/IfAvailable/Always.

The tested local check is:

```sh
uv run pytest tests/contract/test_azure_credentials.py tests/contract/test_aks_verifier.py tests/ui/test_azure_sessions.py tests/terminal/test_azure_login.py tests/unit/test_credential_helpers.py
```

These tests use synthetic providers and owned APIs/PTYS. Actual AKS/Entra trials
remain deferred to Q05 #87; no intermediate manual trial is required to continue.
See [AKS behavior](aks-authentication.md) and [acceptance](acceptance/aks-authentication.md).

## EKS helper contracts: C06 #21

The EKS work preserves the existing workspace, logs and embedded shell trial below.
Local contracts now distinguish recognized AWS login/role errors and serialize
expiring-token refreshes. Delayed concurrent 401s cannot discard newer cache
revisions, and delegated shells retain the selected session's AWS environment.

The exact local contract check is:

```sh
uv run pytest tests/contract/test_eks_credentials.py tests/contract/test_eks_verifier.py tests/ui/test_eks_sessions.py tests/unit/test_credential_helpers.py
```

These are synthetic/loopback tests. The maintainer deferred their real-cluster
trial until the installed preview; actual EKS certification remains pending Q05 #87.
The optional real read-only command and its limits are in
[EKS authentication](eks-authentication.md).

## Responsive header logo: #132

From the latest main checkout in an interactive terminal:

```sh
git pull --ff-only
uv sync --locked --group dev
KUBETROL_THEME=k9s uv run kubetrol
```

At 120+ columns and 16+ rows, the upper-right header displays the original
five-row `ktrol` ASCII logo. At 70–119 columns it uses a small `ktrol` wordmark
to preserve shortcut space; narrower/shorter terminals hide it. Resize, then
visit `:ctx`, `:ns`, pods, containers and logs: header geometry stays consistent
at the same terminal size. `--logoless` and `--headless` still hide the logo.
The project, package and command remain `kubetrol`, with version `0.0.1.dev0`.

The navigation trial below remains applicable. Tab/click focus feedback is
tracked separately in #61; this branding change does not resolve it.
See [actual renders and measured qualification](acceptance/header-logo.md).

## Bordered commands, context table and container details: #129

From the latest main checkout in an interactive terminal:

```sh
git pull --ff-only
uv sync --locked --group dev
KUBETROL_THEME=k9s uv run kubetrol
```

The environment override selects the reference theme even if existing
preferences name another theme; it changes no file. Add `--context YOUR_CONTEXT`
if needed.

1. Check context/cluster/user aliases and installed `0.0.1.dev0` above the table.
   Press `:` and type `c`: `context` appears as a suggested suffix on that
   same bar, without a dropdown. Down cycles candidates; Tab accepts one.
   The command bar has a rectangular border. At heights under 16 rows it keeps
   side borders to leave usable table space. Press Escape, then `/` to try the
   separate filter row; focus does not move the outer frame.
2. Enter `:ctx` (or press `c`) for the normal context table. `/` filters names,
   cluster/auth-info aliases and default namespaces locally. Escape first clears
   the filter, then returns to the preceding resource view. Enter connects to
   the highlighted context and opens pods. Browsing does not change kubeconfig.
   From a filtered context table, `:ns YOUR_NAMESPACE` opens pods with a clear
   query; pressing `c` afterward restores the local context filter.
3. Enter `:ns` for the live namespace table. Filter with `/`, select with arrows
   or `j/k`, then Enter for pods. Escape first clears a filter, then follows
   the bottom route back to namespaces. `0` opens all namespaces.
4. Enter a pod to inspect its container image, ready/state/restarts, probes,
   requests/limits and ports; scroll horizontally with arrows if needed.
   These values are from the captured pod snapshot; reopen to refresh them.
   Missing status shows `—`/Unknown. CPU/MEM columns show configured requests/
   limits, not live consumption. Enter a container for logs. Check that the outer frame and header columns stay in place while the
   available shortcuts change. Click Pause and the search input; resize and return
   to the original size. Escape follows the bottom route.
5. In containers, `s` opens the existing embedded shell. `exit` or Ctrl+] returns
   to that container; Ctrl+C interrupts the remote program and Ctrl+Q quits.

Update notices, cluster metrics and custom/live themes remain planned.
See [workspace behavior](resource-workspace.md) and
[qualification evidence](acceptance/context-container-workspace.md).

| Checkpoint | Required work | What can actually be tried |
| --- | --- | --- |
| Installed CLI | F01, then F02 quality gates | Run help/version from an installed development wheel |
| Local preferences and diagnostics | F03 | Run `info`/`config check`, create defaults and inspect sanitized local logs |
| First terminal window | F01 → F02 → F03 → B01 | Launch the Textual shell, navigate, open help, resize and quit; show an honest unconnected state |
| Launch contract | F05 | Help/version, visibility flags, policy, effective refresh and connection overrides; later features fail explicitly |
| Context session | C01 | Connect, select contexts/namespaces, retry and observe distinct connection errors |
| Resource read backend | C02 | Verify real discovery and paginated snapshots on an owned disposable cluster; the UI table is still empty |
| Resource synchronization backend | C03 | Verify live UID state, reconnect and cancellation; UI subscription/table integration follows |
| First live cluster view | F04/F05, C01-C04, B02/B03/B04 | Choose context/namespace, inspect live pods, filter and open details/events |
| Logs and interactive shell | S01-S04, credential/PTY/integration checks | Follow current/previous logs, choose a container, enter its shell and return safely |
| Public 0.0.1 preview | D04 and every v0.0.1 acceptance gate | Install through tested PyPI/Homebrew channels and follow the verified first-user guide |

The implementation order deliberately puts B01 immediately after configuration
and quality foundations. At each checkpoint, the implementing PR must provide the
exact tested development-install/run command and state which capabilities exist.
Avoid publishing guessed installation commands before the package exists.

For the CLI checkpoint, run `uv sync --locked --group dev`, then
`uv run kubetrol --help` and `uv run kubetrol --version` from the checkout.
No cluster or kubeconfig is required. See the README for details.

For the F03 checkpoint, run `uv run kubetrol info` and
`uv run kubetrol config check`. Neither writes files. To test initialization
without touching your default preferences, choose a temporary directory:

```sh
trial_dir=$(mktemp -d)
uv run kubetrol --config "$trial_dir/preferences.yaml" config init
uv run kubetrol --config "$trial_dir/preferences.yaml" config check
uv run kubetrol --config "$trial_dir/preferences.yaml" info
```

The second `config init` at the same path must refuse to overwrite and exit 3.
`info` now reports `terminal_ui_available: true` and `cluster_connected: false`.
See [preferences](configuration.md) for optional debug-log testing.

## First terminal window: B01

From an interactive terminal in the checkout:

```sh
uv sync --locked --group dev
KUBECONFIG=/nonexistent/kubetrol-preview uv run kubetrol
```

1. Confirm you see Kubetrol, `Context: —`, `Namespace: —` and `Disconnected`.
   The resource table has headers and no rows because no cluster is connected.
2. Press `?` to open help, then `Esc` to return.
3. Press `/`, type a few letters, then `Enter` to return to the table. `Esc`
   clears the active filter. The input works; there are no resources to filter yet.
4. Press `:`, type `help`, then `Enter`. Close the help with `Esc` or its Back button.
5. Resize the window. Context, namespace, connection state and controls stay
   accessible down to the tested size of 40 columns by 12 rows. In narrow windows,
   use left/right arrows in the table to see columns outside the viewport.
6. Press `q` while the table has focus, or Ctrl+Q anywhere, to return to your shell.

Feedback: report whether it opens, whether help/filter/quit work, and your
terminal name and size if anything overlaps or is difficult to read.
The [control reference](terminal-preview.md) covers focus, themes and errors.
Context selection is available in C01 below; pods, logs and exec remain upcoming.

## Launch options: F05 stage 1

```sh
uv sync --locked --group dev
uv run kubetrol version --short
uv run kubetrol --readonly --headless --command help
```

Close help with Esc. Confirm the header is hidden and `Read-only` appears at the
start of the status. Type `:shell` and Enter: the status must say read-only blocks
it. Press `q` from the table to return to your shell. You can separately try
`uv run kubetrol --logoless` or `uv run kubetrol --crumbsless` and compare the header
and scope bar with the default launch.

`--context`, kubeconfig, namespace and timeout selection are now implemented by
C01; see the next checkpoint. F05 #19 now adds effective connection overrides
and periodic table refresh. See the [full launch contract](k9s-cli.md).

### F05 connection checkpoint

The following launch form was exercised with owned fake APIs, actual source and
installed CLI terminals, and a disposable kind cluster. Replace the example
aliases/files/namespace with your own explicit selection:

```sh
uv sync --locked --group dev
KUBETROL_THEME=k9s uv run kubetrol --context YOUR_CONTEXT --refresh 2
```

For the first feedback pass, open `:ctx`, return with Escape, open `:ns`, select
a namespace, then open a pod and its container logs. The selection/filter should
remain stable as table ages update. Connection overrides are optional; when
needed, cluster/user aliases, certificate paths and impersonation are documented
in the [connection contract](k9s-cli.md#effective-invocation-connection).
Cloud provider qualification and later resource/action views remain separate.

Cloud authentication and real-terminal checks run early. A successful mocked UI
is useful feedback, but it does not certify that EKS/AKS credentials, exec,
reconnects or clean-machine installation work. Provider contract tests and actual
cloud smoke results are recorded separately.

The maintainer is notified when each checkpoint is ready. Feature milestones are
scope gates, not promised dates. Bugs discovered during these trials become
focused issues; release numbers change through the documented release workflow.

## Context sessions: C01

From your interactive terminal, using a kubeconfig you already trust:

```sh
uv sync --locked --group dev
uv run kubetrol
```

1. Check the context, namespace and connection state. Resource rows remain empty:
   this checkpoint discovers namespaces; the pod browser comes next.
2. Press `c` (or F2), choose a context with arrows and Enter. Check its state updates.
3. Press `n` (or F3), choose a namespace and Enter. For restricted namespace-list RBAC,
   type `:ns YOUR_NAMESPACE` and Enter instead.
4. Press `i` or type `:status` and Enter to read the complete connection message.
5. Press `r` or type `:retry` and Enter to reconnect; Ctrl+Q returns to your shell.

Letter shortcuts work outside the text fields; Escape returns to the table.
If your terminal intercepts F2/F3, type `:ctx` or `:ns` and Enter instead.
The context-preview correction (#102) accepts null optional exec lists, including
`env: null` in doctl-generated configuration. Restart from the corrected branch
before trying the context again; no kubeconfig edits are needed.

Optionally launch with `uv run kubetrol --context YOUR_CONTEXT -n YOUR_NAMESPACE`.
Nothing changes your kubeconfig or its current context. Report the connection
state/message and whether the selectors and quit work; never paste credentials
or kubeconfig contents. Provider-specific qualification is still pending.
See [supported authentication and limits](context-sessions.md).

## Resource reads: C02 backend checkpoint

The backend now discovers resource types and reads consistent paginated snapshots.
There is no new terminal interaction to try in this PR: `:ns NAME` selects a scope
and the table still has no pod rows. C03 (updates), C04 (store) and B02 (table)
complete the first visible pod view. Command/argument suggestions with Tab are
accepted work in B03 #27, not implemented completion in this checkpoint.

To verify this backend without using a real cluster, run:

```sh
uv sync --locked --group dev
uv run pytest tests/unit/test_resources.py tests/contract/test_resources.py
```

The tests own their loopback servers and synthetic credentials. For the actual
Kubernetes qualification command and retained evidence, see
[resource discovery](resource-discovery.md).

## Resource updates: C03 backend checkpoint

The backend now keeps resource snapshots updated through a recoverable watch.
The terminal still shows the context/namespace checkpoint with no pod rows;
C04 #25 integrates context/scope ownership and B02 #26 provides the visible table.

For this block's isolated behavioral trial:

```sh
uv sync --locked --group dev
uv run pytest tests/unit/test_watches.py tests/contract/test_watches.py
```

These tests cover real loopback HTTP streams, opaque versions, duplicate events,
UID recreation, expired versions, permissions, retries and cleanup. The required
kind check also exercises actual resource changes in an owned disposable cluster.
See [synchronization behavior and limits](resource-watches.md).

## Active view ownership: C04

From an interactive terminal in the development checkout:

```sh
uv sync --locked --group dev
uv run kubetrol
```

1. Choose a context with `:ctx` or `c`. Look for `Live` and the pod count.
   **The table still has no rows**; B02 #26 supplies them next.
2. Type `:ns YOUR_NAMESPACE` and Enter. Check the namespace and count update;
   the old snapshot is cleared while the new scope loads. `:ns *` selects all.
3. Press `i` or enter `:status` for the full message. Lost connectivity or denied
   reads must show stale/error state, rather than a successful empty list.
4. Close details with Esc, try another context or `:retry`, then Ctrl+Q to quit.

Report whether the context/namespace and count match `kubectl` for that scope,
and the safe status message for a failure. No credentials or kubeconfig contents
are needed. These commands are qualified with owned fake APIs, real PTYs and a
disposable kind cluster; actual cloud-provider qualification remains pending.
See [active-view behavior](resource-views.md) for isolated tests and limits.

## Quiet-watch correction: #107

From this correction's branch, in your interactive terminal:

```sh
git fetch origin
git switch fix/107-watch-preview
uv sync --locked --group dev
uv run kubetrol
```

Choose a context with `:ctx`, then type `:ns YOUR_NAMESPACE` and Enter. Look for
**Resource data ready** and **Live · N pods**. Leave it open for 30 seconds:
ordinary watch renewal should keep Live without periodic reconnect warnings.
The table still has no rows; B02 #26 adds them next. `:ctx` is a shortcut hint,
not an automatic context change. A real failed stream still shows stale/error
state; press `i` to read the full safe message. Ctrl+Q returns to your shell.

For feedback, report the namespace/count and, if a retry still appears, only its
safe status text. These steps use your chosen trusted local configuration; the
automated evidence uses owned fake APIs and a uniquely created/deleted kind cluster.


## Live pod table: B02 #26 — current trial

Run from your checkout in an interactive terminal:

```sh
git switch main
git pull --ff-only
uv sync --locked --group dev
uv run kubetrol
```

1. Enter `:ctx`, choose your context and press Enter.
2. Enter `:ns YOUR_NAMESPACE` and Enter. You should now see actual pod rows with
   READY, STATUS, RESTARTS and AGE. Compare with `kubectl get pods -n YOUR_NAMESPACE`
   using that same context. A successful empty scope says **No pods in this scope**.
3. Use arrows/PageDown; `s` cycles sorting and Shift+S reverses it. Left/right and
   Home/End scroll columns. Click a header if you prefer the mouse.
4. Leave it open for 30 seconds. Existing rows/selection should remain stable and
   ages update. A genuine outage keeps rows with a stale warning.
5. Try `:ns *` for all namespaces, then Ctrl+Q to return to your shell.

Report whether rows/count match the chosen scope, which state looks wrong if any,
and whether navigation feels comfortable. Details/logs/exec have their own tickets.
See [pod semantics](pod-table.md).
No public package/release has been published.

## Commands and filters: B03 #27 — current trial

```sh
git switch main
git pull --ff-only
uv sync --locked --group dev
uv run kubetrol
```

1. Type `:ctx ` followed by the first letters of your context. Check the visible
   suggestions, select with Up/Down, press Tab and then Enter.
2. Type `:ns ` and part of your namespace; Tab and Enter should open its pods.
   If namespace listing is denied, type the complete permitted name instead.
3. Press `/`, type part of a pod name and Enter. Check **visible/total pods**.
   Escape in the table clears it. Try `/re:api|worker` for regex matching.
4. Change namespace with `:ns NAME`, then `:back` and `:forward`. Scope, filter,
   sorting and surviving pod selection should return. Alt+Left/Right also work.
5. Type `:help` for the current commands; Ctrl+Q returns to your shell.

Report whether Tab chooses the expected literal name, counts/filter results match,
and history returns to the intended view. These commands only read your chosen
cluster; credential helpers retain the established local trust model. Test evidence
uses owned APIs and a disposable kind cluster. See [navigation behavior and
limits](command-navigation.md); no public package or release has been published.

## Resource inspection: B04

From an interactive terminal on updated `main`:

```sh
uv sync --locked --group dev
uv run kubetrol
```

1. Use `:ctx` and `:ns` to choose your context and namespace; select a pod row.
2. Press `y` for YAML, `d` for details, and `e` for related events.
3. Press `m` to show/hide managedFields. Press `/`, type `containers` and Enter;
   `n`/`N` move through matches.
4. Use arrows and PageUp/PageDown to scroll; Ctrl+Y copies redacted text if the
   terminal permits clipboard writes.
5. Escape leaves the search input, then returns to the table with its selection,
   sorting, filter and viewport retained.

Report whether the selected pod opens, whether events show data or a clear
permission error, and whether search/return work in your terminal. Reopen to
refresh inspection data. Logs and shell remain upcoming. See the
[viewer contract](resource-inspection.md) and [B04 evidence](acceptance/B04.md).

## Log transport: S01

The selected-container transport now has API/encoding/cancellation tests and an
owned-cluster trial. This backend checkpoint adds no terminal log action yet;
S02 supplies the viewer and controls. Continue testing the live table and B04
inspection above. Developers can run:

```sh
uv run pytest tests/unit/test_logs.py tests/contract/test_logs.py
```

See [log semantics and limits](container-log-transport.md).

## Container logs: S02 — current trial

From an interactive terminal on updated `main`:

```sh
git switch main
git pull --ff-only
uv sync --locked --group dev
uv run kubetrol
```

1. Choose your context/namespace with `:ctx` and `:ns`. Select a pod and press
   Enter to see its containers, then Enter on a container to read its logs.
   Check that the title names it. `l` remains the direct log shortcut.
2. Press `g` to read the oldest retained output, then `G` (Shift+G) to follow
   the newest. `j/k`, arrows and page keys scroll; upward movement leaves follow.
3. Press `/`, type visible text and Enter; `n/N` move through matching lines.
4. Press `p` to pause reception. Try `g`, `G` and `f`: navigation still works,
   and following does not unpause. Press `p` again to resume reception.
5. Try `w` for wrapping, `t` for timestamps and `?` for all controls.
   Escape leaves an input, then returns logs → containers → pods; Ctrl+Q quits.

Compare against `kubectl logs` for the same explicit context, namespace,
container and time window. Report any safe error text and whether scrolling,
search, resize and return work. Retention is bounded to 5,000 lines and 4 MiB;
the dropped counter explains missing older history. Previous output may be
unavailable before a container restart. Read-only mode supports this viewer.
See [log behavior and limits](log-viewer.md) and [S02 evidence](acceptance/S02.md).
Interactive shell remains the next product checkpoint; no public release exists.

## Enter navigation: feedback #115 — current trial

From an interactive terminal on updated `main`:

```sh
git switch main
git pull --ff-only
uv sync --locked --group dev
uv run kubetrol
```

1. Type `:ns ` and part of a namespace. Select the suggestion with Up/Down and
   Enter. Check that its pods appear without reopening the namespace picker.
2. Select a pod and press Enter, including a pod with only one container.
   Select a container and press Enter again to read its logs.
3. Press Esc to return to containers, then Esc to return to the pod table.
   Check that the selection and viewport remain where you left them.
4. On pods, `d` still opens details and `l` still opens logs directly. In the
   container table, `j/k` and `g/G` navigate; Ctrl+Q quits.

Container names/types come from the selected pod snapshot; reopen to refresh.
Live container health and ephemeral container browsing remain later work.
Report whether namespace arrow/Enter selection and both returns work in your
terminal. See [behavior and limits](container-navigation.md) and
[measured acceptance evidence](acceptance/enter-navigation.md).

## Process and terminal foundation: S03

The shared local-process runner and native terminal adapter are implemented.
This backend checkpoint does not add a pod/container shell shortcut; S04 #32
provides that user-facing route and actual Kubernetes exec qualification.
Continue the pod/container/log trial above. Developers can run:

```sh
uv run pytest tests/unit/test_processes.py tests/contract/test_processes.py tests/unit/test_terminal_lease.py tests/ui/test_handoff.py tests/terminal/test_handoff.py
```

These tests use owned synthetic local programs and real PTYs, including keyboard
input, resize, Ctrl+C, repeated handoffs, startup failure, cancellation and parent
termination. No user kubeconfig or cluster is used. See the
[process/terminal contract](process-handoff.md) and
[measured acceptance evidence](acceptance/S03.md).


## Selected-container shell: #121 — current embedded trial

From an interactive terminal on merged `main`, with kubectl installed and a
kubeconfig you trust:

```sh
git switch main
git pull --ff-only
uv sync --locked --group dev
uv run kubetrol
```

1. Choose your context with `:ctx`, then `:ns YOUR_NAMESPACE`.
2. Select a running pod and press Enter. Choose its container with Up/Down.
3. Press `s` (or `x`). The shell opens **inside a full-screen Kubetrol frame**,
   with context, pod and container visible. Try `pwd`; resize the window and
   check that the frame stays visible. Ctrl+C interrupts the remote program.
4. Type `exit` or press Ctrl+] to close the shell. Check that the same container
   remains selected. Press Esc to
   return to the same pod and viewport.
5. Alternatively, `x`, `:shell` or `:exec` on pods opens the container picker.
   Enter on containers still opens logs; shell launch always requires `s`/`x`.

Read-only mode refuses shell execution. An image without `sh`, a stopped
container or denied pods/exec permission returns an actionable message. For a
different image shell, configure a YAML argument list such as
`shell: ["/bin/bash", "-l"]` and restart. The shell must exist in that image.
See [shell controls, requirements and limits](container-shell.md) and
[measured embedded-shell evidence](acceptance/embedded-shell.md).

For feedback, report whether the selected container is correct and whether
exit, resize and return preserve the table. No credentials or kubeconfig
contents are needed. Automated trials use owned fake APIs, actual PTYs and an
explicitly created/deleted kind cluster; they do not use your contexts.
