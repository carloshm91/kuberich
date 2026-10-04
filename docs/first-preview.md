# First things to try

The installable development CLI is the first checkpoint. The terminal interface
and live Kubernetes views are subsequent checkpoints:
Do not wait for every epic or the complete 1.0.0 parity audit to get feedback.

| Checkpoint | Required work | What can actually be tried |
| --- | --- | --- |
| Installed CLI | F01, then F02 quality gates | Run help/version from an installed development wheel |
| Local preferences and diagnostics | F03 | Run `info`/`config check`, create defaults and inspect sanitized local logs |
| First terminal window | F01 → F02 → F03 → B01 | Launch the Textual shell, navigate, open help, resize and quit; show an honest unconnected state |
| First live cluster view | F04/F05, C01-C04, B02/B03/B04 | Choose context/namespace, inspect live pods, filter and open details/events |
| Logs and interactive shell | S01-S04, credential/PTY/integration checks | Follow current/previous logs, choose a container, enter its shell and return safely |
| Public 0.0.1 preview | D04 and every v0.0.1 acceptance gate | Install through tested PyPI/Homebrew channels and follow the verified first-user guide |

The implementation order deliberately puts B01 immediately after configuration
and quality foundations. At each checkpoint, the implementing PR must provide the
exact tested development-install/run command and state which capabilities exist.
Avoid publishing guessed installation commands before the package exists.

For the CLI checkpoint, run `uv sync --locked --group dev`, then
`uv run kubetrol --help`, `uv run kubetrol --version`, and `uv run kubetrol`
from the checkout. The default invocation explains that the terminal UI is not
available yet. No cluster or kubeconfig is required. See the README for details.

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
`info` reports `terminal_ui_available: false` and `cluster_connected: false`.
The first Textual window is B01, immediately after this checkpoint is accepted.
See [preferences](configuration.md) for optional debug-log testing.

Cloud authentication and real-terminal checks run early. A successful mocked UI
is useful feedback, but it does not certify that EKS/AKS credentials, exec,
reconnects or clean-machine installation work. Provider contract tests and actual
cloud smoke results are recorded separately.

The maintainer is notified when each checkpoint is ready. Feature milestones are
scope gates, not promised dates. Bugs discovered during these trials become
focused issues; release numbers change through the documented release workflow.
