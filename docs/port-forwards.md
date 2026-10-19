# Managed TCP port forwards

KubeRich supports pod and core/v1 Service forwarding through your installed `kubectl`.
It captures the selected context, namespace, resource UID and connection settings.
No command changes your original kubeconfig or its current context.

1. Open pods with `:po` or Services with `:svc` and select a row.
2. Press **Shift+F** (`F`) or submit `:portforward`.
3. Enter one to eight comma-separated `local:remote` TCP mappings.
   `8080:80` requests local 8080; `:80` or `0:80` asks for an available local port.
   The initial remote port is a hint from the first declared TCP port, or 8080.
   Remote ports can also use a declared port name: `8080:http` or `:http`.
   Pod mappings can qualify a regular container: `web::8080:http`. Ambiguous,
   absent and non-TCP names are rejected. Service names resolve to Service ports;
   `kubectl` translates their target ports on the selected backend.
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
The UI states these rules. Reconnections are disabled by default. The review form
can opt into **0–3 reconnect attempts** after the `kubectl` process disconnects.
**RECONNECTING** appears only after the old process/listener/private file have
been cleaned up. Each attempt rechecks the captured UID and current connection,
uses fresh private connection material and starts a new owned process after
bounded backoff. Permission denials, deleted/replaced resources, lost context,
invalid readiness, occupied ports and explicit Stop are not retried. A Service
restart can select a different current backend. Dynamic local ports may change;
always read the newly observed **BOUND (LAST)** value after reconnection.

The owner checks the exact pod/Service UID before launch and after readiness, and
rechecks it every second while active. Missing, replaced, deleting or finished pods,
permission/connection loss and process death stop the affected forward. A selected
Service backend pod exiting can end `kubectl` before the Service itself changes.
Named declarations are also revalidated against the captured numeric mappings.
If a Service keeps its UID but reassigns the selected name to another port, the
forward stops and requires fresh review. Backend target-port changes are distinct
from Service-port changes and can be resolved on an opted-in restart.
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

## Presets and annotation shortcuts

The review form includes a **Preset** selector. Local named presets live in the
KubeRich preferences file; they do not modify kubeconfig or cluster manifests:

```yaml
schema_version: 1
forwarding:
  schema_version: 1
  auto_annotations: false
  presets:
    web:
      ports: "8080:http,9090:metrics"
      address: "127.0.0.1"
      transport: auto
      retries: 1
  contexts:
    example-production:
      auto_annotations: false
      presets:
        admin:
          ports: "0:https"
          address: "::1"
```

An exact context entry replaces the global forwarding preferences; unspecified
values in that entry use safe defaults. Limits are 32 presets per entry and 128
context entries. `manual` and `annotation` are reserved preset names.
`kuberich config check` validates the local structure without loading a cluster;
port-name resolution happens against the selected resource when starting.
Loading a preset never selects **Allow connections from other hosts**. A
non-loopback preset still needs that separate confirmation.

For migration, KubeRich recognizes `k9scli.io/port-forwards` and
`k9scli.io/auto-port-forwards` annotations. Comma-separated Pod values use
`container::[local:]remote`, for example:

```yaml
metadata:
  annotations:
    k9scli.io/port-forwards: "web::8080:http,metrics::0:metrics"
```

An omitted local port uses the resolved remote number; an explicit `0` or empty
local part requests a free port. Numeric remote ports are also accepted.
Service annotations use `[local:]service-port` without a container.
The auto key takes precedence if both keys exist. Invalid annotations stop the
action with a diagnostic; they do not silently fall back to different mappings.

**Annotations never start a listener merely because a resource is listed.**
Pressing **Shift+F** normally opens review. To allow an auto annotation to bypass
that review on later explicit **Shift+F** actions, set `auto_annotations: true`
locally or select **Allow auto-port-forward annotations for this context this
session** while starting a reviewed forward. The checkbox changes only this
running app's exact-context permission; it does not save files. With no local
opt-in, even an auto annotation opens review. Annotation shortcuts always use
loopback, automatic transport selection and no reconnections.

## kubectl transport selection

The review form and named presets accept:

| Value | Child process behavior |
| --- | --- |
| `auto` | Preserve captured `KUBECTL_PORT_FORWARD_WEBSOCKETS`; otherwise use kubectl's default. |
| `websocket` | Set `KUBECTL_PORT_FORWARD_WEBSOCKETS=true`; kubectl can fall back to SPDY if the upgrade fails. |
| `spdy` | Set `KUBECTL_PORT_FORWARD_WEBSOCKETS=false`. |

Only the owned child's environment changes. KubeRich does not modify your shell
environment, helper identity or other sessions. These labels select kubectl's
behavior; they do not claim to observe which protocol the server negotiated.
This flag is separate from `KUBECTL_REMOTE_COMMAND_WEBSOCKETS`, which controls
kubectl exec/attach/copy. A proxy or server rejecting both protocols still fails
visibly. See Kubernetes' [environment-variable reference](https://kubernetes.io/docs/reference/kubectl/kubectl/#environment-variables).

## Verification and remaining scope

[Acceptance evidence](acceptance/port-forwards.md) covers real loopback processes,
Pilot, actual source/fresh-install terminals and actual TCP/HTTP through an owned
kind pod and Service. Those fixtures never use the caller's active cluster.

This implementation accepts TCP ports and one bind address per session.
It does not discover external forwards or support UDP. See [attach and file transfer](container-attach-copy.md) for those
separate workflows. Real cloud-provider compatibility requires authorized trials.

Kubernetes documents the underlying [kubectl command](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_port-forward/)
and [pod/Service port-forward workflow](https://kubernetes.io/docs/tasks/access-application-cluster/port-forward-access-application-cluster/).
