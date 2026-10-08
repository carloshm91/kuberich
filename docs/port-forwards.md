# Managed TCP port forwards

S05 #42 adds pod and core/v1 Service forwarding through your installed `kubectl`.
It captures the selected context, namespace, resource UID and connection settings.
No command changes your original kubeconfig or its current context.

1. Open pods with `:po` or Services with `:svc` and select a row.
2. Press **Shift+F** (`F`) or submit `:portforward`.
3. Enter one to eight comma-separated numeric `local:remote` TCP mappings.
   `8080:80` requests local 8080; `:80` or `0:80` asks for an available local port.
   The initial remote port is a hint from the first declared TCP port, or 8080.
4. Keep `127.0.0.1` for access from this machine. A different literal IP address
   can be entered; a non-loopback address also requires selecting **Allow
   connections from other hosts**. Hostnames, address lists and multicast are rejected.
5. Start opens the session list. **READY** means the live process actually
   reported all requested listeners and the captured UID passed another API read.
   **BOUND (LAST)** shows the observed local/backend ports; it remains historical
   after a session stops. For Services, the backend can differ from the requested
   Service port: a Service port 80 can forward to its selected pod's 8080.

`:pf` and `:portforwards` open this list again. `/` filters its public fields;
`j/k`, arrows and `g/G` navigate. **s** or **Stop selected** stops the selected
session and waits for its process group, listener and private connection file to
close. **STOPPING** distinguishes cleanup in progress from **STOPPED**. Escape
returns to your preceding resource view; leaving the list does not stop a forward.
Starting a new forward selects its new row. Status patches retain selection/scroll.

## Connection and resource lifetime

Forwards survive resource-view and namespace changes within the same connection.
Changing context, retrying/re-authenticating or replacing that connection stops
its forwards before SDK/TLS directory cleanup. Application exit stops all forwards.
The UI states these rules. There is no automatic restart or reassignment.

The owner checks the exact pod/Service UID before launch and after readiness, and
rechecks it every second while active. Missing, replaced, deleting or finished pods,
permission/connection loss and process death stop the affected forward. A selected
Service backend pod exiting can end `kubectl` before the Service itself changes.
The server resolves a kubectl target by name, so the UID checks reduce the
name/recreation race; they cannot make kubectl's server-side name resolution atomic.

The list is local to this application instance: up to eight active sessions and
32 recent records. Recent records contain target/status/ports, not credentials,
helper environment or raw subprocess output. It does not discover forwards started
by another terminal. Read-only mode allows listing but blocks starting forwards
before file, API and executable preparation.

`kubectl` must be available in the captured PATH. The process uses a private
mode-0600 kubeconfig staged in the captured client's owned directory, explicit
context/namespace and an argument vector. Existing provider/helper/environment
and connection override behavior is shared with embedded shell delegation.
A missing executable, occupied port, readiness timeout or denied operation gives
a bounded diagnostic without displaying raw helper output. Common Kubernetes
permissions are `get` on the target pod/Service, pod selection for Services and
`create` on `pods/portforward`; server RBAC remains authoritative.

## Verification and remaining scope

[Acceptance evidence](acceptance/port-forwards.md) covers real loopback processes,
Pilot, actual source/fresh-install terminals and actual TCP/HTTP through an owned
kind pod and Service. Those fixtures never use the caller's active cluster.

This implementation accepts numeric TCP ports and one bind address per session.
Named ports, FastForward annotations/presets and additional transport behavior
remain S08 #62; attach/file transfer remain S07 #48. Real cloud-provider trials
remain opt-in Q05 #87, and complete macOS/hosted release qualification is pending.

Kubernetes documents the underlying [kubectl command](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_port-forward/)
and [pod/Service port-forward workflow](https://kubernetes.io/docs/tasks/access-application-cluster/port-forward-access-application-cluster/).
