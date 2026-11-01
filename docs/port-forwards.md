# Forward a TCP port

Forward a Pod or Service through your installed kubectl. You need write mode,
read access to the target, and `pods/portforward` permission. Service forwarding
also needs permission to select its backend pod.

## Start a forward

1. Select a row in `:pods` or `:svc`, then press Shift+F or type `:portforward`.
2. Enter one to eight comma-separated TCP mappings. `8080:80` requests local
   port 8080; `0:80` or `:80` requests a free port. A declared name is accepted,
   such as `8080:http`. Pods may qualify a container: `web::8080:http`.
3. Keep `127.0.0.1` for this machine only. Another literal IP is accepted;
   non-loopback access also requires **Allow connections from other hosts**.
4. Check the target and choose Start.

**READY** means kubectl reported all requested listeners and the target passed
another identity check. **BOUND (LAST)** shows the observed ports. A Service's
backend port can differ from its Service port. Use the reported local port when
you asked for a free one.

Ambiguous or missing port names, non-TCP ports, hostnames, multicast addresses,
and address lists are refused. There is one bind address per session.

## List and stop sessions

`:pf` or `:portforwards` lists this application's sessions. `/` filters the list;
use arrows or `j`/`k` to select one. Press `s` or **Stop selected** to close it.
**STOPPING** means cleanup is still running; **STOPPED** means it completed.
Leaving the list does not stop a forward.

Forwards survive resource-view and namespace changes on the same connection.
Changing context, retrying authentication, replacing the connection, or quitting
stops them. There are at most eight active sessions and 32 recent records. The
list does not discover forwards started by other terminals.

## Reconnect deliberately

Reconnections are off by default. Review can allow up to three attempts after a
previously ready kubectl process disconnects. A process that fails before readiness
is not repeatedly restarted. Permission denial, deleted/replaced targets, occupied
ports, invalid readiness, and explicit Stop are not retried.

**RECONNECTING** follows cleanup of the previous process. Each attempt checks the
same target again. A Service can select a different current backend. A dynamically
selected local port may change; read **BOUND (LAST)** again after reconnection.

The target is also checked every second while forwarding. Deletion, replacement,
connection loss, or changed named-port mappings stops the forward. These checks
reduce the name-recreation race; kubectl's server-side target selection is not
atomic with the check.

## Save a preset

Add a local preference entry, then run `kuberich config check`:

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
```

Select it in Review. Context entries replace global forwarding settings for that
exact context. There are at most 32 presets per entry and 128 context entries.
A preset never enables non-loopback access without its separate confirmation.

KubeRich recognizes `k9scli.io/port-forwards` and
`k9scli.io/auto-port-forwards` annotations. Pod values use
`container::[local:]remote`; Service values use `[local:]service-port`.
The auto annotation takes precedence. Invalid values produce an error.

Listing a resource never starts a listener. Shift+F normally opens Review.
To let an auto annotation skip Review on later explicit Shift+F actions, enable
`auto_annotations` locally or the form's context-session opt-in. Annotation
shortcuts use loopback, automatic transport selection, and no reconnections.

## Select a kubectl transport

`transport: auto` preserves the launch environment's
`KUBECTL_PORT_FORWARD_WEBSOCKETS` value or kubectl's default. `websocket` sets it
to true; kubectl may fall back to SPDY. `spdy` sets it to false. These choices
control kubectl and do not report the negotiated protocol. A proxy that rejects
both transports still causes a visible failure.

A missing kubectl, denied request, occupied port, or readiness timeout requires
correcting the cause and starting a new forward. Read-only mode permits listing
but blocks starting. For connection or proxy errors, see
[contexts and authentication](context-sessions.md).
