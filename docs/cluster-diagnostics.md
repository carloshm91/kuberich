# Investigate workload failures

Use Diagnostics to connect observed Pod or workload failures with conditions,
container state, Events and referenced storage. It explains the evidence and
its limits so you can decide what to inspect next. It performs no automatic
remediation. These views are available in
development source; the installed 0.3.0 release predates them.

Start with a context and namespace you are allowed to read:

```sh
kuberich --context demo-lab --namespace demo-apps --readonly
```

All context, namespace, resource and executable names in this guide are fictional.
You need permission to read the relevant Pods, workloads, Events and referenced
PersistentVolumeClaims. A forbidden source remains visible and does not make
an empty result evidence that everything is healthy.

## Collect and inspect evidence

1. Type `:diagnostics` to collect Pod evidence in your selected namespace. If
   the header selects all namespaces, the overview uses all namespaces.
2. To investigate one workload, select its real resource row and type
   `:diagnose`. Supported roots are Pods, Deployments, ReplicaSets, StatefulSets,
   DaemonSets, ReplicationControllers, Jobs and CronJobs.
3. Read **SOURCE**, source status and **AGE**, then select a finding and press
   Enter. The detail screen shows its severity, explanation, exact field paths,
   reasons, object identity, observation times and available actions.
4. Press `o` to open the current resource, `e` to open an available Event, or
   `n` to choose the next Event. KubeRich reads the object again and checks its
   unique Kubernetes identity, its UID, before opening it.
5. Where available, press `l` for current container logs or `p` for previous
   container logs. Opening a finding alone fetches no log bytes. Press Escape
   to return; see [read logs](log-viewer.md) for viewer controls and limits.

Use `/` to filter literal table text. Source and summary rows remain visible.
The Severity and Source column headers control sorting. Normal Back/Forward
navigation restores the filter, selection and scroll position, then collects
fresh evidence. Source and finding rows are informational; normal resource
changes require opening an actual resource and passing their usual checks.

## Interpret a finding

| Category | What the evidence can establish | What it cannot establish |
| --- | --- | --- |
| Image pull | A container reports an image acquisition error or backoff | Whether credentials, registry availability or the image itself caused it |
| Scheduling | An explicit unschedulable condition or a matching scheduling Event was observed | That a Pending phase alone means scheduling has failed |
| Crash loop | A container reports `CrashLoopBackOff`; available restart and previous termination facts add context | The application's underlying cause, or a crash loop from restart count or `OOMKilled` alone |
| Readiness | A readiness condition is false or a running container reports `ready=false` | That a readiness probe caused it; a generic `Unhealthy` Event does not identify the probe type |
| Volume | A matching mount, attach, map or binding failure Event, or an explicit claim's phase/conditions, was observed | That a Pending claim is the cause; delayed binding can be expected |
| Workload | A selected workload reports a relevant condition, with available generation information | Failure from zero Pods, replica differences or a suspended CronJob alone |

`Unknown` means the condition is unknown. Unclassified conditions remain
information rather than an invented cause. Completed Pods do not produce an
active readiness failure merely because readiness is false. Kubernetes explains
these distinctions in [Pod lifecycle](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/)
and [container probes](https://kubernetes.io/docs/concepts/workloads/pods/probes/).

Events must match the observed object's UID, namespace, name and API kind/group.
A same-name replacement does not inherit another object's Events. An Event more
than an hour old is historical; missing, invalid or future Event time is unknown.
A current scheduled condition can supersede an earlier scheduling Event. An old
condition transition time alone does not prove that the current condition is old.

**AGE** describes when KubeRich collected each source or evidence item. Evidence
becomes stale after 60 seconds; there is no automatic polling. A source can be
both partial and old. Workload conditions can also be stale when their reported
generation precedes the workload's current generation. Read both limitations.
The final collection time does not make older evidence fresh.

## Keep the header and investigated object separate

`:diagnose` uses the selected root object's namespace, even if the header shows
another namespace or all namespaces. For example, a Deployment in `demo-other`
keeps that collection scope while the header still says `demo-apps`.

`:diagnostics` clears the root and returns to the header's namespace overview.
Choosing a namespace, including choosing the same namespace again, also clears
the root and starts that overview. History restores its saved header and root
together and reads current evidence again. Context changes cancel previous work;
an old session or a recreated root cannot silently become the new target.

Namespace overviews initially collect Pod status and matching Events. Selected
workload mode also reads root conditions and Pods verified through controller
UIDs. Matching labels alone do not establish ownership. Selected-root mode can
read up to 16 distinct explicitly referenced claims; repeated declaration paths
remain separate evidence. Native diagnostics do not read Secret or ConfigMap
values, environment values, container commands or log samples.

## Run Popeye explicitly

Popeye is an optional, separately installed local executable. The integration
accepts the **Popeye v0.22.1** version tuple and its supported JSON report layout.
Other versions or layouts produce an unsupported/rejected source. See the
[upstream project](https://github.com/derailed/popeye/tree/v0.22.1) for the tool.

Add a definition for an exact context in your
[preferences](configuration.md#create-and-check-preferences):

```yaml
schema_version: 1
observability:
  schema_version: 1
  contexts:
    demo-lab:
      popeye:
        executable: /opt/demo-tools/popeye
        sections: [pods]
        timeout_seconds: 60
        trusted_read_only: true
```

Replace the fictional absolute path with the executable you installed and trust.
Sections use canonical linter names, such as `pods` or `deployments`; the
[configuration reference](config-reference.md) lists the accepted fields.
Run `kuberich config check` after editing.

Selected sections control the report, rather than all API reads the external
tool may perform. Popeye can preload other resource families, including
PodDisruptionBudgets, even for a Pod-only report. Such denied reads remain
visible as incomplete/forbidden sources. A score of 100 or an empty finding
list does not establish health when source coverage is incomplete.

`trusted_read_only: true` is your explicit classification of that local program.
It permits its execution in read-only mode; it does not sandbox the executable.
Leave it false unless you trust that program to perform only reads. Without
that classification, read-only mode refuses execution. Native collection still
works when Popeye is absent, unsupported or refused.

A global `observability.popeye` is the fallback for contexts without an explicit
observability context entry. A context entry replaces the global observability
block, including history; its fields are not merged. Redeclare any history or
tool settings that context should keep. An explicit context `popeye: null`
disables the tool for that context.

Type `:popeye` when you want a run. Opening Diagnostics, refreshing, restoring
history and changing context never run it automatically. In root mode, Popeye
receives the root's namespace; the selected root UID does not limit its scan to
that one object. With the example above, a root in `demo-other` means Popeye
scans namespace `demo-other`, even while the header says `demo-apps`. An overview
of all namespaces requests an all-namespace scan.

The source shows the producer version, selected sections, outcome, deadline and
limits. A valid report can accompany exit code 0 or 1; other process outcomes
do not establish a completed scan. Popeye severity and source stay separate
from native evidence. A report
usually names an object without its UID: opening it reads the current object,
and historical identity remains unverified. Unsupported or ambiguous references
have no resource action. Previous logs are not inferred from a name-only report.

The configured scan deadline defaults to 60 seconds and accepts 1–120 seconds;
the version probe has its own 5-second limit. Combined scan stdout/stderr is
limited to 8 MiB. The external tool uses a private, temporary configuration for
the selected connection and preserves its credentials, TLS and impersonation.
KubeRich stops the process and removes temporary material when the run ends or
is cancelled. External API read count is **unknown**; the native read quota does
not govern another program's discovery, preloads or permission reviews.

## Cancel, refresh or recover

Type `:diagnostics cancel` to stop the active native collection or Popeye run.
KubeRich drains the work before another run starts. Already displayed evidence
keeps its observation times, and unfinished sources show cancelled/incomplete
status. Refresh collects native evidence again and clears previous Popeye output;
it never reruns Popeye. Use `:popeye` for another explicit external scan.

A same-scope Popeye run keeps available native evidence and its read count, then
replaces the previous Popeye result. Native evidence remains available if the
tool fails or is cancelled. Different contexts, namespaces, roots or session
generations do not carry old report rows into a new scope.

Native collection allows 64 logical reads, 10,000 input objects, 16 MiB of input,
2 MiB of compact facts and a 30-second collection deadline. Pagination and
interrupted charged reads count toward its read quota. Discovery, authentication
retries, explicit resource opening and log reads have separate limits. These
figures do not bound all network traffic or total application memory.

The combined display keeps at most 1,000 findings and 2 MiB of text, including
source notices and evidence. Native findings have priority; Popeye uses the
remaining space. Omitted finding and evidence counts stay visible with partial
status, including when no external finding fits. Missing privileges, unavailable
APIs, malformed data, missing tools and time/output limits remain distinct from
a successful empty result. Even **No failure evidence found in the collected
sources** is not a cluster health certificate.

Read the source detail, narrow your namespace if necessary, correct the specific
permission or dependency problem, then refresh. If an object was recreated,
return to its resource table and select it again. For expired authentication,
follow [context recovery](context-sessions.md#recover-a-connection).
