# Investigate a workload

Follow a workload from its table to its containers and logs, then return to the
same resource view. You need read access to the workload, its pods, and their
logs. Start in read-only mode; this walkthrough changes no resources.

## Start with the workload

When you need a wider starting point, development source provides a
[cluster overview](cluster-overview.md). Open `:pulse` to inspect health, capacity
and usage, then press Enter on a summary to open its matching resource list.
The installed 0.3.0 release predates this overview.

```sh
kuberich --context demo-lab --namespace demo-apps --readonly
```

Replace the fictional names with your permitted scope. Type `:deploy` and press
Enter to list Deployments. Use `/` to narrow the list, then Enter to return focus
to the table.

Press `d` for details, `y` for YAML, or `e` for events on the selected row.
These pages show a read snapshot. `/` searches the document, `n` and Shift+N move
between matches, and Escape returns to the resource table. Values in ordinary
inspection pages are redacted.

## Follow owners and dependencies

Development source adds `:xray` on the selected Deployment. Expand its controller
and Pod relationships with Enter/Right; selector matches remain separate from
UID-checked ownership. Select a current object and use `o` or `:open` to open its
resource view. Use `:back` to return to the graph and its expansion state.

For a ConfigMap, Secret, ServiceAccount, PVC or PriorityClass, `:usedby` lists
supported static declarations. An empty incomplete scan does not prove unused.
See [resource relationships](resource-relationships.md) for supported fields,
source scope and permission limits. Installed 0.3.0 predates these views.

## Read logs across the workload

On the Deployment row, press Shift+L or type `:logsall`. The viewer reads logs from
containers whose controller chain leads to that Deployment. It does not treat
matching labels alone as proof that a pod belongs to the workload.

Each line identifies its source. Press `c` to see the source list. At most eight
readers run at once; select a waiting source and press Enter to read only it.
Press Space to choose a set of up to eight, or `a` to return to automatic selection.

Press `p` to pause incoming output. Press `f` to toggle following the newest line;
follow and pause are separate controls. Press Escape to return to the Deployment.
See [read logs](log-viewer.md) for export limits and current/previous instances.

## Inspect one pod

Type `:pods`, filter to the pod you want, and press Enter. The container table
shows regular, init, and existing ephemeral containers. State, readiness, restart
counts, and other displayed fields update while the same pod remains selected.
The declared CPU/memory requests and limits stay visible. Development source
also shows live CPU(m), memory(MiB), explicitly labelled usage percentages and
sample availability. See [current metrics](resource-workspace.md#current-cpu-and-memory-metrics)
for read permissions, units, partial totals and uncertain allocation limits.

Select a container and press Enter for its logs. Escape returns through
logs → containers → pods. Selection and scroll position survive ordinary updates;
a deleted or replaced pod cannot become a different shell or log target.

## Open a shell when needed

A shell can change the container. Quit and restart with `--write` only when you
intend that access:

```sh
kuberich --context demo-lab --namespace demo-apps --write
```

Select the pod, press Enter, then `s` on the intended running container. The shell
opens inside the workspace. Enter `exit` or press Ctrl+D to return. Ctrl+] closes
the local session. The image needs the configured shell and your account needs
`pods/exec` access. See [shells and attach](container-shell.md).

## Return to earlier views

Use Alt+Left or `:back` to restore the previous view, scope, filter, sort, and
selection. Alt+Right or `:forward` moves forward again. New navigation replaces
the forward history. History lasts for this running application only.

Use `:status` for a full connection error and `:retry` after correcting it.
For changes to replicas, rollouts, or Jobs, use the separate
[workload operations](workloads.md) guide and check every review before confirming.
