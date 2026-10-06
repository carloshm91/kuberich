# First things to try

The installable CLI, local preferences and first terminal window are available
from the development checkout, including the live pod table and container logs. Use the latest
S02 trial below; earlier sections record previous checkpoints and may name
short-lived branches that have since been deleted.
Do not wait for every epic or the complete 1.0.0 parity audit to get feedback.

| Checkpoint | Required work | What can actually be tried |
| --- | --- | --- |
| Installed CLI | F01, then F02 quality gates | Run help/version from an installed development wheel |
| Local preferences and diagnostics | F03 | Run `info`/`config check`, create defaults and inspect sanitized local logs |
| First terminal window | F01 → F02 → F03 → B01 | Launch the Textual shell, navigate, open help, resize and quit; show an honest unconnected state |
| Launch contract | F05 stage 1 | Try help/version subcommands, visibility flags, initial help and read-only command guards; pending features fail explicitly |
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
C01; see the next checkpoint. F05 remains open until its connection
and execution integrations are qualified. See the [full launch contract](k9s-cli.md).

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
