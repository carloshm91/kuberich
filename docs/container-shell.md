# Open a shell or attach

Open an embedded terminal for a selected container. You need kubectl on PATH,
a trusted connection, pod read access, and `pods/exec` for a shell or `pods/attach`
for attachment. Read-only mode blocks both actions.

## Start a shell

1. Start with an explicit context and namespace in write mode:

   ```sh
   kuberich --context demo-lab --namespace demo-apps --write
   ```

2. Replace those fictional names with your intended scope. Select a pod and press
   Enter, or use `x`, `:shell`, or `:exec` to open its container table.
3. Check the container name and state. Press `s` or `x` on the intended container.

The shell opens full screen inside the Textual workspace. Its frame identifies
the context, namespace, pod, and container. The default command is `sh`; the image
must contain it. Configure another argument list in preferences if needed:

```yaml
schema_version: 1
shell: ["/bin/bash", "-l"]
```

Run `kuberich config check` after editing. Arguments are passed literally; shell
expressions are not interpreted by KubeRich. The setting applies to the next shell.
A startup `--command shell` is unavailable because a selected pod is required.

## Return without leaving the workspace

| Control | Result |
| --- | --- |
| `exit` or Ctrl+D | Exit the shell and return to containers |
| Ctrl+] | Close this local exec session and return |
| Ctrl+C | Interrupt the remote program |
| Ctrl+Q | Quit KubeRich and stop its local processes |

While the terminal is live, Escape, arrows, Tab, `q`, `:`, and `/` reach the remote
program. Full-screen editors and ANSI colors use the embedded emulator. Resizing
changes the remote terminal size. Escape after returning to containers restores
the preceding pod table and its selection.

## Review terminal history

Click **History**, or press Alt+PageUp/Shift+PageUp, to review a frozen copy of
normal-screen output. The remote program keeps running. Full-screen alternate
buffers do not enter normal-screen history.

- Arrows or `j`/`k`, page keys, and `g`/Shift+G move locally.
- `/` or Ctrl+F starts literal, case-insensitive search. Enter finds a match;
  `n`/Shift+N move through matches.
- `v` or Space starts/ends a row range. Shift-click can select a range when mouse
  reporting is enabled. `y` or Ctrl+Y copies selected whole rows explicitly.
- Enter, Escape, `q`, or **Live** returns to the running screen.

History keeps up to 1,000 scrolled rows; a frozen copy keeps its own rows while
live history advances. Search accepts 256 characters; copy accepts 64 KiB after
control escaping and recognized-credential redaction. Output can still contain
secrets the application cannot identify. Remote clipboard escape requests are
inert; no output copies automatically.

## Attach to an existing process

Use `:attach` on a pod, then `a` on a running container. Attach connects to its
existing main process. That process's stdin and TTY settings decide whether
interaction is possible; this action does not create a new shell.

Press Ctrl+P then Ctrl+Q to send kubectl's detach sequence. Ctrl+] closes the local
session. Ctrl+C reaches the existing process and can affect the workload.
Ctrl+Q alone quits KubeRich. Closing or detaching does not request pod deletion.

## Handle a failed or stale session

A deleted, replaced, completed, or deleting pod cannot start an old selection's
session. Select the pod again after a context or UID change. KubeRich checks the
pod before launch, but Kubernetes exec/attach targets names and has no atomic UID
precondition; replacement between the check and server request remains possible.

Exit 126/127 often means the configured image shell is missing. Check kubectl,
permissions, the selected container, and its state before trying again. An image
without a shell needs a suitable image; SSH is not required for pod exec.

The private kubectl connection file is deleted after return. The source kubeconfig
and current-context are unchanged. Local cleanup cannot promise termination of a
remote exec process after a lost connection. Raw interactive output is visible
in the terminal and is not copied into application diagnostic logs.

Mouse reporting, terminal graphics, and advanced keyboard protocols are not
implemented inside the remote emulator. For file movement, use
[file transfers](container-attach-copy.md).

## Diagnose a Linux node (development source)

Development source adds `:node-shell` on a selected Node. Published 0.4.0 does
not include this action. It creates one temporary diagnostic pod; SSH credentials
are not used. The shell starts in the diagnostic container, with the node's root
filesystem at `/host`; KubeRich does not automatically chroot.

This profile grants host root access: the container is privileged, runs as root,
shares host PID/IPC/network namespaces and mounts `/host` read-write. Container
limits and the disabled service-account token mount do not make it a sandbox.
The review shows these effects before creation. Cancel is the default.

### Configure an approved image and namespace

The feature is disabled until explicitly enabled. Select an existing namespace
whose policies permit this diagnostic profile, and an approved Linux image with
`/bin/sh` and `/bin/sleep` for the node's architecture. Use its immutable digest:

```yaml
schema_version: 1
node_shell:
  schema_version: 1
  enabled: true
  namespace: diagnostics
  image: registry.example.com/ops/diagnostics@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
  requests: {cpu: 10m, memory: 32Mi}
  limits: {cpu: 250m, memory: 128Mi}
  startup_timeout_seconds: 60
  session_timeout_seconds: 3600
```

Replace that fictional image/digest and namespace with reviewed choices, then run
`kuberich config check`. Reload preferences with `:reload`. Loading preferences
does not pull images or create pods. Normal kubelet image pulls can occur after
confirmation. There is no per-dialog image override or fallback image.

Requests must be positive and no greater than limits. CPU is bounded to eight
cores, memory to 8 GiB, startup to 5–300 seconds and sessions to 60–3600 seconds.
The initial host mount and privilege profile are fixed, not arbitrary templates.
Linux and macOS clients can diagnose Linux Nodes; Windows Nodes are unsupported.

### Review, open and return

1. Connect explicitly in write mode, open `:nodes` and select the intended Node.
2. Enter `:node-shell`. KubeRich reads that Node and the configured namespace,
   checks their UIDs and performs a strict server create dry-run.
3. Review the context, Node UID, namespace, image digest, pod name, privileges,
   host mount, limits and deadlines. Choose **Create and open** deliberately.
4. Wait for scheduling and startup, then use the existing embedded terminal.
   `exit` or Ctrl+D returns; Ctrl+] closes locally; Ctrl+C interrupts remotely.

The identity needs Node/namespace reads, pod create/get/delete and permission for
kubectl's `pods/exec` connect request. Admission, Pod Security and RBAC decisions
remain authoritative. Denial does not trigger a policy change or weaker profile.

The normal scheduler uses required affinity to the selected Node. KubeRich does
not set `nodeName`, add tolerations, uncordon or change taints. An unschedulable,
tainted, unavailable or unreachable node can therefore time out. Image failures
also stop startup. These failures retain the cleanup outcome separately from
the actual create result in `:writes`.

On return, KubeRich drains local exec and requests deletion of only the Pod UID
returned by creation. It confirms absence before discarding the recovery record.
Accepted deletion, finalizers, denied reads/deletion or a lost connection may leave
cleanup pending. No force deletion or finalizer removal occurs. A deadline can
stop a running pod on a healthy kubelet; it does not delete its API object or
guarantee cleanup on an unreachable node.

### Recover after interruption

Use `:node-shell-recover`, or start with
`kuberich --command node-shell-recover`, to inspect the private local journal.
This destination does not automatically connect or authenticate. Close an active
diagnostic session before recovering its record.

Choose **Inspect** only after explicitly connecting the recorded context. Cleanup
additionally checks captured connection evidence and the namespace UID, requires
write mode and presents a separate default-Cancel review. A same-name replacement
is preserved. Unknown-UID creates cannot be adopted or deleted through recovery,
even if a later observation looks identical. **Forget** removes only the local
record after confirmation; it does not change a remote pod or claim cleanup.

Read-only mode allows local listing/inspection but blocks new diagnostic creation,
exec and recovered deletion. Tightening read-only or disabling the feature during
an existing session first stops exec; its original lease may still finish cleanup
of that session's returned UID. Changed image/limits apply to the next review.

Connection matching is routing/trust/configured-identity evidence, not a universal
cluster identity. Bearer-only or otherwise ambiguous identities are bound to the
current prepared session; reconnect recovery cannot assume they are equivalent.
Records contain bounded metadata, never kubeconfig credentials or terminal output.
Unsafe, corrupt or unavailable journals block new creation until inspected.

Fresh Node and Pod checks reduce replacement races, but scheduling and exec have
no atomic cross-resource UID precondition. UID-conditioned deletion does protect
a same-name replacement during cleanup. Linux disposable-cluster and terminal
tests do not certify every cloud provider or admission policy.
