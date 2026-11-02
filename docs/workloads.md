# Operate a workload

Select a workload in its ordinary resource table, check the context and namespace,
and use a command for the intended action. Changes require write mode and the
corresponding Kubernetes permissions. Progress viewing also works read-only.

## Scale replicas

Use `:scale` or `:scale 3` on a Deployment, ReplicaSet, or StatefulSet. Review the
replica count, then choose Confirm separately. Zero replicas stops replicas;
counts range from 0 to 2,147,483,647. StatefulSet scale-down review reports PVC
deletion requested by its actual retention policy.

Scale needs workload GET and `/scale` GET/PATCH. It also checks namespace HPAs;
an HPA targeting the workload blocks manual scale. A denied or invalid HPA check
blocks review. The HPA check and scale request are separate, so an HPA can appear
in between. An owning controller can reconcile a manually scaled ReplicaSet.

## Restart or restore a revision

`:restart` reviews a pod-template timestamp change on a Deployment, StatefulSet,
or DaemonSet. `:rollback` or `:rollback 1` restores one explicit available controller
revision's template. Replica counts and update strategy stay current.

Rollback reads revisions belonging to the selected controller UID and checks the
chosen revision again before writing. Missing or ambiguous history is refused.
Paused Deployments and `OnDelete` StatefulSets/DaemonSets refuse automatic
restart/rollback. Rolling partitions remain in effect. Restoring a StatefulSet
can still require deliberate removal of a failed pod; rollback does not force it.

## Watch rollout progress

Use `:rollout` to read generation, controller counters, revisions, partitions,
paused state, and reported Deployment deadline failure. A successful write does
not mean rollout completed. Escape stops this monitor without undoing a change.
The monitor times out after five minutes; reopen it for current progress.

## Delete one or several resources

Use `:delete` for the selected resource or `:deletebatch` for marked rows. Without
marks, batch review offers the displayed filtered rows and selects none initially.
Space toggles an item. Batches contain at most 100 exact targets and send one
DELETE per target, never a collection-wide DELETE.

Choose Review, select propagation and optional grace seconds, type `DELETE 1` or
`DELETE COUNT` matching the review, then Confirm separately. Cancel has default
focus. The review identifies context, resource, namespace, UID, and version.

| Propagation | Consequence |
| --- | --- |
| Foreground | Dependent cleanup precedes completion of owner deletion |
| Background | The owner may disappear before dependents finish |
| Orphan | Dependents remain |

Blank grace uses the server default. Zero grace does not bypass finalizers or
prove remote processes and external storage are gone. Controllers can recreate
deleted pods. Already-terminating resources are refused; finalizers are shown
but never removed automatically. Deletion checks UID and resourceVersion on the
server, so replacement or concurrent changes require a fresh review.

**Accepted; deletion pending** reports API acceptance, not dependent cleanup.
A follow-up read showing absence confirms only removal of that selected object.
Batches run sequentially with independent results; earlier success is not rolled
back when another item fails. Use `:writes` to read every outcome.

## Clean up finished pods

In `:pods`, narrow the view with a filter, then use `:cleanup`. Completed and
failed pods are listed; running, pending, and already-deleting pods are excluded.
Every listed pod starts selected; Space excludes it. Review and confirm with
`DELETE COUNT`. At most 100 pods are handled per cleanup.

If an object was deleted or replaced before confirmation, nothing is deleted;
review again. A version conflict during execution affects that item while other
items can succeed. Read-only mode blocks cleanup.

## Run or suspend Jobs

Use `:trigger` on a CronJob to review creating one manual Job from its current
template. The review and result show the exact Job name, including an uncertain
creation outcome. The manual Job is independent of the CronJob's schedule and
concurrency policy and can run while the CronJob is suspended. Template TTL and
suspension settings remain part of the new Job.

`:suspend` and `:resume` change `spec.suspend` on a Job or CronJob. Suspending a
CronJob stops future scheduled runs, not existing Jobs. Resuming can start missed
runs. Suspending a Job terminates active pods; resuming can restart execution
and reset its start time. Check these effects before Confirm.

## Recover from a conflict or uncertain write

Every action binds its review to the selected target and change. Input edits
invalidate it; Confirm can be used once. No automatic retry follows a rejected,
interrupted, or lost write response. Inspect current state before another review.
`:writes` keeps recent results for this application session, not a persistent
audit log. See [edit and change resources](editing.md) for shared result meanings.
