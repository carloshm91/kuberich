# Inspect cluster health

Use Pulse to compare node, pod and workload summaries, then open the resource
list behind a count. The overview described here is available in development
source; the installed 0.3.0 release predates it.

You need read access to the resource families you want to inspect. Current usage
needs a Metrics API implementation such as metrics-server. History needs a
Prometheus-compatible backend with the required metric sources. A Service
connection needs Kubernetes Service-proxy read permission; an external URL uses
its own connection settings. Each source reports its own availability, so missing metrics or denied
access does not hide the resource summaries that you can read.

## Open the overview

```sh
kuberich --context demo-lab --namespace demo-apps --readonly
```

Replace these fictional names with your permitted scope. Type `:pulse` or
`:overview` and press Enter. Pulse uses the normal workspace frame, context,
command bar and navigation history.

The table fills as each resource family loads. It includes:

- Nodes that are Ready, NotReady, unknown, cordoned or under pressure.
- Pods by phase, including pending pods without a node and running pods that are
  not ready.
- Deployments, ReplicaSets, StatefulSets, DaemonSets, Jobs and CronJobs, with
  healthy, degraded, completed and unknown states kept separate.
- Current node and active-pod CPU/memory, with capacity, allocatable resources
  and configured pod requests/limits where those totals are known.

Read **DATA / TIME (UTC)** for the source state, scope and observation time.
Nodes are cluster-scoped; pods and workloads use your namespace selection.
`:ns *` selects all namespaces when your account permits it. A denied read says
`forbidden`; an unknown or incomplete value is not a healthy result or a measured
zero. `INCOMPLETE` identifies a source whose available rows do not establish a
complete total.

A zero-desired DaemonSet can remain `unknown` even after its controller has
observed the current generation. Kubernetes can omit optional zero availability
and update counters; Pulse keeps missing health evidence distinct from an
explicit healthy state. Zero counts in the ordinary DaemonSet table do not
establish Pulse health.

Collections refresh one after another, then wait 15 seconds before the next
cycle. Sources are observed at different times, rather than as one atomic
cluster snapshot. Current samples expire after 60 seconds even while a later
read is waiting. Collection limits can leave a source partial; they do not
represent a total-process memory guarantee.

## Open the resources behind a summary

Move to a summary row and press Enter. The resource table opens with that row's
API version, namespace and health or phase filter. For example, a pending-pod
summary opens pending pods; a node-pressure summary uses the same pressure
conditions that produced the count.

Enter on a current CPU or memory row opens the corresponding Node or active-pod
table sorted by that usage, highest first. Active-pod totals exclude succeeded
and failed pods. History rows show a backend query result rather than a selected
Kubernetes object.

Pulse keeps a fixed summary order; its overview rows do not have a column-sort
control. Use `/` to narrow summary rows. Clear that filter to show usage and
history rows again. With the table focused, Escape, Alt+Left or `:back` returns to the previous
view when history is available. Alt+Right or `:forward` returns forward. Pulse
restores its filter, selected summary and scroll position, including a position
inside a chart row. Changing namespace from Pulse returns to the overview in
the chosen namespace.

The live resource list can change after the overview's observation time. A
replaced object does not inherit a previous object's selection. Open a resource
list before using YAML inspection or resource-change actions; a summary count
is not a resource target.

## Interpret capacity and usage

Node usage includes node processes and is separate from the sum of pod usage.
Node capacity and allocatable resources come from the Node API. Pod requests
and limits describe configured declarations, not proof that a resize finished
or a scheduler reservation is active.

Partial membership, missing budgets and complex pod allocation can leave totals
or percentages unknown. Unlimited limits remain distinct from zero. See
[current metrics](resource-workspace.md#current-cpu-and-memory-metrics) for units,
denominators and init-container, sidecar and resize limits.

## Connect overview history

Add an optional history connection to your preferences. This example applies
only to the fictional context `demo-lab`:

```yaml
schema_version: 1
observability:
  schema_version: 1
  contexts:
    demo-lab:
      history:
        namespace: observability
        service: prometheus
        port: 9090
        provider: auto
        cluster_label: cluster
        cluster_value: demo
        matchers:
          job: kubelet
        node_matchers:
          job: node-exporter
        state_matchers:
          job: kube-state-metrics
```

Use your actual Service and scrape labels. The three matcher groups select
container, node-exporter and kube-state-metrics series separately. A configured
cluster selector applies to every source and join. `cluster_label` and
`cluster_value` must agree and be configured together. Without them, the chart
labels its cluster binding unverified; a context name never becomes a label.
The selected namespace narrows namespaced measurements. A conflicting selector
is an error, rather than a broader query.

Run `kuberich config check` after editing. Service queries use the selected
Kubernetes connection and `services/proxy` read permission. Kubernetes authenticates
the API request; that does not authenticate you to the backend. Its proxy removes
Authorization and impersonation headers before forwarding. Backend HTTPS through
this proxy does not provide independent certificate verification by KubeRich.
Use an external HTTPS connection when you need backend credentials or your own CA.

For an external backend, replace the Service fields with a URL:

```yaml
history:
  url: https://metrics.example.com/prometheus
  provider: prometheus
  ca_file: /absolute/path/metrics-ca.pem
  bearer_token_file: /absolute/path/metrics-token
  cluster_label: cluster
  cluster_value: demo
```

This is the `history` fragment inside the same observability block. The URL's
path is the API prefix; it cannot include credentials, query parameters or a
fragment. Token files require HTTPS. This connection does not inherit Kubernetes
credentials, client certificates, proxy settings, cookies or environment-based
credentials. Redirects are refused. Keep the token file private; changing its
contents replaces the connection credentials on the next request. Checking
preferences does not read credential files or contact either server.

Supported provider settings are `auto`, `prometheus`, `victoriametrics` and
`thanos`. Auto checks compatibility without claiming an authenticated product
identity. Set `api_prefix` for a Service endpoint mounted below the root; an
external URL already supplies its prefix. Existing Service-only settings remain
valid. KubeRich installs no metrics components.

## Explore metric history

From Pulse, press Shift+M or enter `:history` for cluster history. From a Node,
Pod or supported workload table, select a row and use the same action. For a
specific container, open the Pod with Enter, select its regular, init, sidecar
or ephemeral container, then press Shift+M. `:hist` is an alias. Read-only mode
permits these metric reads.

The history workspace keeps the selected entity, backend, selectors and source
status visible. Without a configured backend, `d` explicitly searches the selected
namespace for compatible Service candidates. The result can be partial or denied.
`b` cycles through candidates; choosing one applies only to this screen and does
not save preferences. Select a namespace before detection if you opened an
all-namespace view. Detection does not search arbitrary external addresses.

| Key | Action |
| --- | --- |
| `1`–`7` | Select 15m, 30m, 1h, 3h, 6h, 12h or 24h |
| `c`, `m`, `n`, `f` | Show CPU, memory, network or filesystem |
| `[` / `]` | Previous / next device or mount |
| `r` | Collect the selected range again |
| `a` | Switch between Unicode and ASCII charts |
| `u` | Switch workload historical/current membership |
| Escape | Return to the previous view |

Numbers always accompany the chart, including last, minimum, maximum and units.
CPU uses a counter rate; its default lookback is five minutes. `rate_window_seconds`
accepts 60–3600 seconds. Container memory is working set. Node memory uses
host total minus available memory. Network shows receive/transmit
bytes per second. Filesystem shows bytes per device or mount, rather than a
universal total that can count the same storage twice. Node measurements use
node-exporter host metrics, separately from sums of container metrics.

Container network is the Pod's shared network, not traffic attributed to a
single process. Host-network Pods share the host network. The fixed network
profile requires the explicit `container="POD"` sandbox series; a backend without
it reports a source gap. Kubelet versions and scrape configurations may omit
filesystem or sandbox metrics. Missing sources stay unavailable.

Historical workload membership uses kube-state-metrics owner evidence at each
evaluation time. Names do not prove historical UID identity. Current-member mode
instead uses the Pods currently returned by Kubernetes and shows the member
count and observation time. It cannot recover deleted members. Creation and
replacement boundaries leave gaps, including the CPU/network rate lookback.
The displayed Kubernetes UID does not establish an equivalent historical binding.

`·` marks a missing sample; measured zero stays zero. Nonfinite, missing-source,
forbidden, partial and expired values keep their status. Evaluation timestamps
are not proof of scrape freshness. Ranges use at most 721 points per series and
collection may stop at its visible query, series or response limits. Range ends
are aligned to their resolution; a new backend can have no samples on a coarse
grid even when the most recent short-range chart has data.

Collection is explicit and finite. Rapid range changes replace the pending
request; previous requests drain before their replacement. A detail view pauses
Pulse's history reads while health collection continues. The cache keeps results
for at most 30 seconds; displayed results expire after 60 seconds. The expiry
indicator does not poll the backend. Press `r` for a new collection.

Valid backend changes cancel previous work and invalidate exports from the old
configuration; theme-only changes retain results. Changing namespace, context or
target rejects late results. To disable a context's configured connection, set
its `history` to `null`. See [configuration](configuration.md#configure-overview-history)
and [saved exports](exports.md).
