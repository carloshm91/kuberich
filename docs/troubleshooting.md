# Troubleshooting

Start with the visible state and the operation that failed. Authentication,
permission, resource synchronization and local terminal errors have different
causes. The examples below use fictional `demo-lab` and `demo-apps` names; replace
them with an explicitly intended scope when running a command locally.

## Check the local installation

```sh
kuberich --version
kuberich --help
kuberich info
kuberich config check
```

These commands do not connect to Kubernetes or execute authentication helpers.
`info` describes the local application, dependency versions, preference paths and
resolved preferences. It does not prove that a cluster connection is healthy.
`config check` validates preferences without changing files.

If the command is missing, inspect the executable location reported by your
installer. uv and pipx tool executables must be on your shell's PATH. A locally
extracted standalone archive uses its own `./kuberich` entry point; retain the
complete extracted directory. See [installation](installation.md).

If `--version` reports an unexpected build, identify which executable your shell
resolves and which channel installed it. Upgrade through that same channel;
installing another copy does not upgrade the original one.

## A context is missing or different

KubeRich loads `--kubeconfig` when supplied. Otherwise it reads the configured
`KUBECONFIG` file list or the ordinary default. `--config` is an application
preferences file, not a kubeconfig.

Use an explicit path and context to make the intended selection unambiguous:

```sh
kuberich --kubeconfig /absolute/path/to/kubeconfig \
  --context demo-lab --namespace demo-apps --readonly
```

`:ctx` lists the loaded local catalogue; Enter selects a context. Browsing the
catalogue does not rewrite kubeconfig or authenticate. Names preserve case and
can include spaces. For merged files, relative certificate/helper paths resolve
against the file that supplied their entry.

A context switch cancels the previous connection and rejects its late results.
It does not change kubectl's persisted current context. Invocation overrides
continue to apply during that KubeRich invocation. See [context sessions](context-sessions.md).

## Authentication fails while kubectl works

Compare the explicit kubeconfig, context, namespace and inherited environment in
both commands. A kubectl invocation from another terminal can have a different
PATH, provider profile, cache directory or login session.

KubeRich captures helper identity and environment for a context session. If you
changed a profile, environment variable or kubeconfig after launching, start a
fresh invocation to deliberately use the new settings.

| Visible condition | Next step |
| --- | --- |
| Missing helper | Install the executable declared by the selected kubeconfig and make it available on the effective PATH. |
| Expired EKS credentials or SSO | Complete the intended AWS CLI profile login externally, then `:retry`. |
| Azure CLI login required | Establish the intended `az login` session for a configured `azurecli` entry, then retry. |
| Interactive exec helper required | Use explicit `:login` in a native terminal. It runs the declared helper, without inferring another provider mode. |
| Unsupported legacy credentials | Migrate the intended entry to supported exec/token/certificate configuration following the provider's instructions. |
| Helper timeout | Check provider login/connectivity. Background helpers have closed stdin and bounded execution; they cannot wait indefinitely for a prompt. |

`:login` restores the workspace after completion or cancellation. Authentication
is allowed in read-only mode because it enables reads. Provider tools own their
login caches; KubeRich does not store a second cloud identity database.

[EKS](eks-authentication.md), [AKS](aks-authentication.md) and
[credential interoperability](kubeconfig-interoperability.md) explain supported
contracts and the limits of real-provider certification.

## The session is connected but the table is empty

Connection status and resource status are separate. A successful namespace
discovery does not establish permission to list every resource family.

1. Clear the local filter: Escape leaves its input first, then clears the filter
   from the table. Confirm whether the visible count changes.
2. Check the context and namespace in the header. `:ns demo-apps` selects an exact
   namespace; `:ns *` requests an all-namespace scope that needs broader permission.
3. Distinguish **No resources** from **Permission denied**, **Stale** or a removed API.
   A successful empty list is valid; a denied list is not presented as empty data.
4. For a failed discovered API, return to `:pods` or another available resource.
   `:refresh` renews discovery and the selected watch; `:retry` reconnects the session.

When namespace listing is denied, direct selection of a permitted namespace can
still work. Changing to all namespaces does not bypass Kubernetes RBAC.

## A live view says stale or reconnecting

The view retains its last successful snapshot during a temporary watch/network
failure and marks it stale. Bounded reconnect/relist work runs in the background;
it does not establish that retained rows describe the current server state.

Check VPN/network reachability and the selected API endpoint locally. `:status`
opens connection details. `:retry` creates a new owned session; changing context
also replaces it. A quiet stream can renew normally, so absence of new rows alone
does not mean resources disappeared.

TLS errors require checking CA, hostname and client certificate configuration.
Timeout/unreachable states concern connectivity or request deadlines. Resolve
the stated cause before retrying rather than weakening TLS verification.

## Logs or a shell fail

Logs require a valid captured pod/container and permission for `pods/log`. Previous
logs may be absent even when current logs work. A replaced/deleted pod invalidates
the captured selection; return to the table and select the current object.

Shells additionally require write mode, local `kubectl`, permission for `pods/exec`
and an available configured shell in a running container. Read-only mode deliberately
blocks launch. The embedded terminal does not implement every graphics, mouse or
advanced keyboard protocol; a program using those features can exceed its scope.

`exit`/Ctrl+D returns normally; Ctrl+] closes the owned shell. During local history
review, Escape returns to remote-key routing. See [shell controls](container-shell.md).

## A key or clipboard action does not work

Terminal emulators and tmux can consume function keys or Alt combinations. Use
`:ctx` and `:ns` when F2/F3 are intercepted, and `:back`/`:forward` when Alt navigation
is unavailable. Consult the current view's `?` help.

Copy sends redacted text through terminal OSC52 support. SSH/tmux forwarding and
the terminal's clipboard permission determine whether the host receives it.
The application showing a copy result does not certify the host clipboard.
Use a reviewed explicit file export where supported if clipboard integration is
unavailable. [Terminal compatibility](terminal-compatibility.md) describes the scope.

## A change is blocked, conflicted or uncertain

Review and Confirm are separate. Missing write mode, a stale captured UID/version,
an autoscaler or insufficient permission can block a change before writing.
A conflict requires reading the current object and preparing a new review.

An uncertain outcome means a sent request may have applied even if its response
was lost. Inspect the object and `:writes` before another attempt. KubeRich does
not automatically replay writes. Leaving a review does not undo a confirmed action.

See [guarded changes](mutations.md), [editing](editing.md) and [workloads](workloads.md)
for operation-specific restrictions.

## Report a problem

Include the KubeRich version and installation channel, OS/architecture, Python
version for source installs, terminal/tmux/SSH arrangement, the visible state and
the smallest sequence that reproduces the problem. Describe expected and actual
behavior. State whether it also reproduces with an owned disposable cluster.

Use fictional context, namespace, resource and account names in a public report.
Do not attach kubeconfig, token/helper output, private certificates, credentials
or customer logs. Inspect screenshots and copied diagnostics before sharing:
application redaction cannot recognize every private business name or log message.
For vulnerabilities, follow [the security reporting policy](../SECURITY.md).
