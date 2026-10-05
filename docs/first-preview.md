# First things to try

The installable CLI, local preferences and first terminal window are available
from the development checkout. Live Kubernetes views are subsequent checkpoints.
Do not wait for every epic or the complete 1.0.0 parity audit to get feedback.

| Checkpoint | Required work | What can actually be tried |
| --- | --- | --- |
| Installed CLI | F01, then F02 quality gates | Run help/version from an installed development wheel |
| Local preferences and diagnostics | F03 | Run `info`/`config check`, create defaults and inspect sanitized local logs |
| First terminal window | F01 → F02 → F03 → B01 | Launch the Textual shell, navigate, open help, resize and quit; show an honest unconnected state |
| Launch contract | F05 stage 1 | Try help/version subcommands, visibility flags, initial help and read-only command guards; pending features fail explicitly |
| Context session | C01 | Connect, select contexts/namespaces, retry and observe distinct connection errors |
| Resource read backend | C02 | Verify real discovery and paginated snapshots on an owned disposable cluster; the UI table is still empty |
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
