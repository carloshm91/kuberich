# Troubleshoot a session

Start with the visible state and the operation that failed. The examples use
fictional context and namespace names; replace them with your intended scope.

## Check the installation

```sh
kuberich --version
kuberich --help
kuberich info
kuberich config check
```

These commands stay offline and execute no authentication helpers. Info reports
local versions, preferences, and paths; it does not test a cluster connection.
If the command is missing, check your install manager's executable directory and
PATH. If its version is unexpected, identify the executable your shell resolves
and upgrade through that installation method. Keep an archive's complete directory.

## A resource view cannot be rendered

An inline error panel means that this view's presentation failed. Use **Retry**
in that panel to try again, or choose another resource. Watch updates do not
repeatedly retry the failed view. Displayed rows may be incomplete; the selected
resource and identity checks still apply to operations. Other views and active
port forwards keep running. A new context or resource scope clears the old fault.

If the whole application exits unexpectedly, it restores the terminal and prints
the location of a private crash report. If the report cannot be written, the
message says so. A normal quit, interrupt or disconnected terminal does not
create a crash report.

## Create a diagnostic report

```sh
kuberich bug-report
# Choose a new destination explicitly:
kuberich bug-report --output ./kuberich-report.json
```

The command writes a mode-0600 JSON file with the installed version, Python and
platform, terminal dimensions when available, preference-check status and a
size-limited redacted tail of the application's own diagnostic log. It also works
when preferences are invalid; the report records that result. Existing files,
symbolic links and special-file destinations are refused.

Reports do not load kubeconfig, contact a cluster, run credential helpers or
include preference contents. Crash reports omit exception values, local
variables, source lines and full traceback paths. Review the file before sharing
it; it stays local until you choose to attach it to a bug report.

## Find the intended context

`--config` selects application preferences. `--kubeconfig` selects Kubernetes
configuration. Otherwise KubeRich merges KUBECONFIG or reads the default file.
Use an explicit path when comparing tools:

```sh
kuberich --kubeconfig /absolute/path/to/kubeconfig --context demo-lab --namespace demo-apps --readonly
```

`:ctx` shows the loaded list; Enter connects. Selecting a context does not change
kubectl's saved current-context. Restart after changing kubeconfig elsewhere.

## Fix authentication

If kubectl works, compare its exact kubeconfig, context, namespace, PATH, provider
profile, cache directory, and environment with the KubeRich launch. Another
terminal can have a different provider session. Start a fresh invocation after
changing helper environment or kubeconfig.

| Message or state | Action |
| --- | --- |
| Auth error or missing helper | Install the declared helper; check login, PATH, and its configured mode |
| Expired EKS/SSO credentials | Complete the intended AWS profile login externally, then `:retry` |
| Azure CLI login required | Establish the intended `az login` session for azurecli mode |
| Interactive helper required | Use `:login` in a native terminal; it runs the declared entry |
| Legacy auth-provider unsupported | Use a current provider helper or the explicit OIDC migration command |
| TLS error | Check CA, server hostname, and client certificates; do not disable verification |
| Timeout or Unreachable | Check VPN, server/proxy reachability, and request deadline |
| Config error | Correct the named configuration problem or choose another context |
| API error | Check endpoint/API availability, then retry deliberately |

Background helpers have closed stdin and a deadline. `:login` permits the declared
interactive behavior and restores the workspace afterward; Ctrl+C cancels it.
Authentication remains available in read-only mode. See
[contexts and authentication](context-sessions.md) for EKS, AKS, GKE, and TLS details.

## Diagnose an empty or stale table

Connection status and resource status are separate. Successful namespace discovery
does not prove permission to list a resource family.

1. Escape leaves an input, then clears the table filter. Check matching/total rows.
2. Check context and namespace. `:ns demo-apps` chooses a known namespace;
   `:ns *` needs all-namespace permission.
3. Distinguish a successful empty list from Permission denied or Stale.
4. `:refresh` renews API discovery and the current resource watch on the same
   client. `:retry` replaces the connection and stops its session work.

A denied namespace list can still permit direct entry of an allowed namespace.
All namespaces does not bypass RBAC. A stale view keeps its last successful rows
while reconnecting; those rows are not proof of current server state.
An absent discovered API remains a visible error. Use `:pods` or another available
view to recover rather than expecting a guessed endpoint.

## Recover logs, shells, and writes

Logs need pods/log permission and a current pod/container. Previous logs may not
exist. Select the pod again after deletion/recreation or a context change.

Shells also need write mode, kubectl, pods/exec permission, and an image containing
the configured shell. `exit`/Ctrl+D returns normally; Ctrl+] closes the local
session. During history review, Escape returns to the live remote screen.
Graphics, mouse reporting, and advanced remote keyboard protocols are outside
the embedded emulator's current support.

A blocked write can mean read-only mode, a stale target, an autoscaler, or missing
permissions. A conflict requires current state and a new review. An uncertain
write may already have applied: inspect the object and `:writes` before retrying.
Leaving a confirmed form does not undo it. See [resource changes](editing.md).

## Keys and terminal compatibility

Use an interactive UTF-8 terminal. If function keys or Alt combinations are
intercepted by a terminal or tmux, use `:ctx`, `:ns`, `:back`, and `:forward`.
KubeRich cannot receive keys consumed by an outer program. `?` shows current
controls. Mouse reporting is off by default; enable `navigation.mouse` and restart
only if wanted. Every operation has a keyboard route.

The interface adapts down to compact terminals; help exposes clipped secondary
information. A font, terminal palette, or emulator can still render glyphs and
colors differently. NO_COLOR and the monochrome theme keep textual state cues.
SSH and tmux need working PTY and resize forwarding. See the
[command/key reference](cli-reference.md) for default navigation.

## Clipboard

Copy is explicit; the application never reads your clipboard to acknowledge it.
`KUBERICH_CLIPBOARD=auto` selects OSC52 over SSH, then local macOS native text,
Wayland `wl-copy` when WAYLAND_DISPLAY is set, X Window System `xclip` when DISPLAY
is set, and otherwise OSC52. Wayland takes precedence when both display variables
are present. `native` requires a native session and skips the automatic SSH
preference; `osc52` explicitly selects your terminal.

Local Wayland needs `wl-copy` on PATH and a working compositor; X Window System
needs `xclip`. Missing or failed helpers can fall back to OSC52 in automatic mode
within its byte limit. Forced-native failures ask you to check the helper or use
`KUBERICH_CLIPBOARD=osc52`. Compositor acceptance still depends on your session.

Native text accepts up to 1 MiB; OSC52 accepts 64 KiB. Invalid or oversized text
is refused rather than truncated. Headless copies stay in application memory.
Wayland and X Window System selection persistence after exit depends on a
clipboard manager. Native helper text travels on stdin, with no MIME guessing
or newline trimming.

The outer terminal must allow clipboard writes. In tmux, allow passthrough for
the intended pane using your own server configuration; KubeRich does not change
it. A sent OSC52 request does not prove the outer clipboard accepted it.
Where supported, save an explicit reviewed file if clipboard integration is absent.
Secret-value copy has separate deliberate-disclosure rules.

## Report a problem

Include application version, installation method, OS/architecture, terminal and
SSH/tmux arrangement, the visible state, and the smallest reproducing steps.
Use fictional names. Do not attach kubeconfig, helper output, tokens, certificates,
credentials, or customer logs. Check screenshots and copied output before sharing;
redaction cannot recognize every private name or message. Report vulnerabilities
through [the security policy](../SECURITY.md).
