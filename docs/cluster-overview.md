# Inspect cluster health

Use Pulse to compare node, pod and workload summaries, then open the resource
list behind a count. The overview described here is available in development
source; the installed 0.3.0 release predates it.

You need read access to the resource families you want to inspect. Current usage
needs a Metrics API implementation such as metrics-server. History needs a
configured Prometheus Service and permission to read its Kubernetes Service
proxy. Each source reports its own availability, so missing metrics or denied
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
only to the exact fictional context `demo-lab`:

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
        scheme: http
        cluster_label: cluster
        cluster_value: demo
        matchers:
          job: cadvisor
```

Set the Service fields and label values to those used by your backend. Requests
use your selected Kubernetes connection and its Service-proxy permission. Run
`kuberich config check` after editing. A valid change to the active backend
restarts Pulse's collection and cancels the previous query. An invalid change
keeps the last valid preferences.

The configured endpoint alone does not prove that its series belong to your
Kubernetes cluster. `cluster_label` and `cluster_value` declare your chosen
binding. They must be configured together and agree with any matching selector.
Without them, charts explicitly report an unverified backend scope. KubeRich
does not derive a Prometheus cluster label from your context name. The active
namespace adds a `namespace` matcher; a conflicting configured namespace is an
error.

The backend must already expose `container_cpu_usage_seconds_total` and
`container_memory_working_set_bytes` with `container` and `pod` labels. The
queries sum matching containers; CPU uses a five-minute counter rate and memory
uses working set. Missing matching series appear as no data.

The requested interval is the previous 15 minutes at 15-second resolution. Numeric values accompany the sparklines; `·` marks a missing sample.
Missing values are gaps, while an observed zero stays zero. CPU displays mCPU
and memory displays MiB. The visible scale uses the available samples.

The history row shows the backend selectors, query interval, query time and
availability. Evaluation timestamps do not prove the time of the backend's
scrape. Empty, partial, failed, forbidden and expired history remain explicit;
they do not turn into zero usage. Cached charts expire after 60 seconds.

This overview does not install metrics-server or Prometheus. Broader per-resource
history, network/filesystem charts and additional backend discovery remain
unavailable. To disable a context's history, set its `history` to `null`; this
also overrides a global history connection. See
[configuration](configuration.md#configure-overview-history) and the generated
[configuration fields](config-reference.md) for the accepted declarations.
