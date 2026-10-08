# M03 #45 acceptance evidence

Selected workload commands provide default-Cancel Review and separate one-use
Confirm, common read-only policy and guarded captured UID/version. Scaling uses
the actual scale subresource; real narrow RBAC works without parent patch access.
HPA ownership is checked before preparation and execution. Restart and explicit
retained-history rollback respect paused/OnDelete strategies. Rollout monitoring
reads actual state and can stop without claiming a server undo.

## Qualification in progress

Focused domain/HTTP/TLS/Pilot/CLI/CI-policy verification passed 420 cases before
the storage-retention case. Both workload and mutation decision modules reached
100% lines/branches. Five native terminal cases passed, including source scale/
restart/rollback and fresh-wheel console/module launches, with default Cancel,
separate confirmation, resize and terminal restoration.

Actual kind passed Deployment scale/restart/rollout/ReplicaSet rollback, HPA
refusal, forbidden scale writes, scale-only patch RBAC, paused refusal, timeout/
cancellation without undo, progress-deadline failure, and StatefulSet/DaemonSet
ControllerRevision restart/rollback. Its cluster was deleted and absence verified.
Complete Linux interpreter/coverage gates and delivery artifact qualification
remain in progress; this is not public-release qualification.

```sh
uv run python -m scripts.verify_workloads_kind --kind /tmp/kubetrol-tools/kind --evidence /tmp/kubetrol-45-evidence/kind.json
```

## Scope and limits

See [supported behavior](../workloads.md). HPAs can be created after the ownership
check; no cross-object transaction is claimed. ReplicaSet owners can reconcile
manual replicas. Failed StatefulSet pod recovery/deletion remain separate actions.
ReplicationController/generic resources and owner drill-down remain #53/#70;
this does not establish full capability-family parity. Native macOS, full hosted
matrix and cloud certification remain outstanding under the account Actions
block. No public package, tag, release or visibility change is made.
Raw evidence: `/tmp/kubetrol-45-evidence` (local).
