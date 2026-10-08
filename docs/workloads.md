# Workload operations

Select a workload in its resource table before opening an action. Commands capture
the selected context, namespace, name and UID. They require an interactive
selection rather than a `--command` startup view.

| Command | Resources | Behavior |
| --- | --- | --- |
| `:scale` or `:scale 3` | Deployments, ReplicaSets, StatefulSets | Review replicas, then separately Confirm a guarded `/scale` patch. |
| `:restart` | Deployments, StatefulSets, DaemonSets | Review a pod-template timestamp change, then Confirm. |
| `:rollback` or `:rollback 1` | Deployments, StatefulSets, DaemonSets | Restore the template from one explicit retained controller revision. |
| `:rollout` | Deployments, StatefulSets, DaemonSets | Read actual controller progress, including in read-only mode. |

Cancel has default focus. Input Enter prepares a review without writing. Review
identifies the resource/version/effect; separate Confirm consumes one prepared
change. Changed input invalidates the review. Counts range from 0 to 2147483647;
zero stops replicas. StatefulSet scale-down review discloses PVC deletion when
its actual retention policy requests it.

Scale requires workload get and `/scale` get/patch access, without parent patch
permission. Namespace HPA list access checks ownership; an HPA targeting this
workload blocks manual scale. Absent autoscaling v2 falls back to v1; denied or
invalid checks block preparation. An HPA can appear after the check: this is not
a cross-resource atomic transaction. ReplicaSet owners can reconcile manual replicas.

Restart/rollback require parent get/patch. Paused Deployments refuse these actions.
`OnDelete` StatefulSets/DaemonSets need deliberate pod deletion; automatic restart/
rollback is refused. Rolling partitions are respected, without resetting strategy.

Rollback reads Deployment ReplicaSets or StatefulSet/DaemonSet ControllerRevisions
owned by the captured UID. One explicit positive retained revision is required;
absent, ambiguous or unsupported history is refused. Its UID/version is checked
again before writing. Only the template is restored; replicas and strategy stay
current. Failed StatefulSet recovery may require deliberate removal of a failed
pod after rollback; this action does not force-delete pods.

The [shared mutation guards](mutations.md) provide one-use confirmation, atomic
UID/version tests and no automatic replay. Conflicts need a new review. `:writes`
retains confirmed/uncertain outcomes without manifest values. Leaving a confirmed
write view does not undo or repeat the request. Context change/exit drains it.

Monitoring reads observed generation, controller counters, Deployment deadline
failure, paused state and StatefulSet revisions/partitions. API confirmation does
not imply rollout completion. Cancel/Escape stops monitoring without claiming an
undo. After five minutes it times out; reopen progress with `:rollout`.

Sources: [Deployment controllers](https://v1-36.docs.kubernetes.io/docs/concepts/workloads/controllers/deployment/),
[StatefulSet controllers](https://v1-36.docs.kubernetes.io/docs/concepts/workloads/controllers/statefulset/),
[DaemonSet controllers](https://kubernetes.io/docs/concepts/workloads/controllers/daemonset/).
See [acceptance evidence](acceptance/workloads.md) for measured scope and limits.
