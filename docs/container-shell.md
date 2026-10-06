# Selected-container native shell

On pods, `x`, `:shell` or `:exec` opens the container table. Enter on a pod also
opens that table, including single-container pods. Choose a regular/init container
with arrows or `j/k`, then press `s` or `x` to launch its configured shell.
Enter/`l` still opens logs. Pod `s` continues to change the sort column.

Kubetrol suspends the UI and delegates the actual terminal to
[kubectl exec](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_exec/).
Keyboard input, Ctrl+C and window-size changes reach the foreground program.
SIGTERM during handoff cleans up the owned process and exits the CLI with 143
after terminal restoration. Type `exit` to return to the same container selection; Esc returns to the
retained pod table. A failed exec also returns to that view. Long feedback can
be read by focusing/scrolling its region, including at 40×12.

## Requirements and preferences

Install kubectl on PATH, using a [client version supported by your cluster](https://kubernetes.io/releases/version-skew-policy/#kubectl).
Use trusted Kubernetes configuration and credentials; configured exec-auth
helpers remain trusted local programs. The selected account needs pod reads
and pods/exec permission; the Kubernetes server makes the authorization decision.
Read-only mode blocks shells before file preparation or executable lookup.

The default image command is `sh`. To choose another shell, edit Kubetrol
preferences and restart:

```yaml
schema_version: 1
shell: ["/bin/bash", "-l"]
```

This is an argument list, with 1–32 nonempty strings. It is passed literally after
kubectl's `--`, without shell interpolation. The image must contain that program.
`config check` validates the preference; it does not connect or execute anything.
Initial `--command shell` is unavailable because launching a shell requires a
selected pod and container. The interactive aliases take no command arguments.

## Captured scope and return

The action captures the owned client/session, context, namespace, pod name/UID,
container, shell argv, environment and working directory before awaiting work.
A GET verifies that the pod still has the captured UID and container, and that
it is not deleting or completed. Scope invalidation blocks launch. A replacement
between that check and kubectl's server request remains a Kubernetes race:
exec-by-name has no atomic pod-UID precondition. Kubetrol does not claim otherwise.

Kubectl uses a private snapshot of the prepared session's endpoint, TLS material
and credential mechanism, with explicit context/namespace/pod/container flags.
Changing the original kubeconfig after connection cannot redirect this action.
The snapshot is mode 0600 inside the owned mode-0700 SDK directory and is deleted
after return or cancellation. Certificate files live until their client closes.
The original kubeconfig and current-context are never rewritten.

Missing local kubectl, denied pod reads, deleted/replaced pods, unavailable
containers and nonzero exec exits produce safe feedback. Exit 126/127 suggests
an unavailable image shell. Other kubectl failures name the exit code and
permission/state/shell checks; raw stderr appears only in the deliberately
handed-off terminal and is not retained in UI diagnostics. Exec is never retried
automatically. An image without a shell requires a suitable image or the later
ephemeral-debug workflow, not an invented SSH connection.

## Verification and remaining scope

See [measured S04 acceptance evidence](acceptance/S04.md) for the qualified commit,
coverage, actual terminal/cluster trials and unavailable platform checks.

Behavioral checks cover immutable capture, exact arguments, private file modes,
UID replacement, stale views, read-only policy and repeated cancellation/cleanup.
Pilot trials cover selected-container launch, compact feedback and retained
cursor/viewport. Source and freshly installed CLI PTYs cover actual foreground
ownership, input, resize, Ctrl+C, fullscreen use, failures and terminal restoration.

The isolated Kubernetes trial creates and deletes its own cluster and fixtures:

```sh
uv run python -m scripts.verify_shell_kind --kind /path/to/kind --kubectl /path/to/kubectl
```

It requires kind 0.33.0 and kubectl 1.36.4, pins the Kubernetes 1.36.4 node and
Alpine images by digest, and exercises the actual CLI with two containers,
configured/default/missing shells, full-screen vi, resize, interruption, repeated
return and denied pods/exec. It also edits only its owned source kubeconfig after
connection to verify the prepared session remains pinned. Evidence is written to
`artifacts/cluster/shell.json` and `artifacts/terminal/kind-shell-*`.

SSH/tmux/macOS qualification remains Q02/full platform CI. EKS/AKS/provider smoke
qualification remains C06/C07/C08. Attach, file transfer, node/ephemeral shells
and terminal emulation remain separate work. This provides native local-terminal
container exec; it does not establish complete K9s capability parity.
