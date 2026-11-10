# 0043: Own privileged node diagnostics through returned Pod identity

Status: in implementation; real API, UI and complete protected gates remain pending.

## Context

A node shell requires a deliberately privileged workload, not SSH credentials.
Creating that workload, opening exec and removing it have separate failure states.
An uncertain create does not prove ownership of a later object with the same name.
Application exit or changed preferences must not discard known cleanup authority.

## Decision

Keep the feature disabled by default. An operator chooses one digest-pinned image
and an existing namespace in validated local preferences. The fixed Linux profile
uses host PID/IPC/network namespaces, privileged root and a writable `/host` mount.
The image supplies `/bin/sh` and `/bin/sleep`. Resource limits and finite deadlines
do not turn host root access into a sandbox. No image override, automatic chroot,
additional mounts, policy relaxation or SSH helper is part of this profile.

Use the normal scheduler with required node affinity to the captured Node name;
do not set `nodeName`, add tolerations or change taints. Fresh Node/namespace UIDs,
connection and configuration generations bind a one-use review. A strict create
dry-run validates the full execution profile before a single SDK-owned POST.
Permit only enumerated API defaults; reject unexpected containers, environment,
volumes or security changes. Dry-run identity never confers cleanup ownership.

Capture a matching successful create response's Pod UID before subsequent spec
validation. Durably record that UID before readiness or exec. A bounded, drained
create/receipt/file transition retains identity through cancellation. A malformed
or lost response remains uncertain; no retries or name/label-based adoption follow.
Write history reports creation independently of eventual terminal cleanup.

Reuse the existing embedded terminal, process runner, PTY and private connection
staging. The session owner outlives dismissed screens and stops exec before cleanup.
Context replacement, expiry, disablement and read-only tightening stop new work.
The original active lease retains only authority to clean up its returned Pod UID.

Delete with an atomic UID precondition and ordinary finite grace, without a status
resourceVersion condition. Accepted deletion is not confirmed absence. Observe
404 or a different UID before removing the local record. Conflicts, denied deletion,
finalizers and timeouts retain an honest pending outcome; never force deletion,
remove finalizers, delete collections or remove a same-name replacement.

Keep versioned, bounded, credential-free records in private application state.
No-follow descriptors, ownership/mode checks, atomic writes, fsync and an exclusive
nonblocking lease protect local recovery state. First-frame startup scans only
local files; it does not connect, authenticate or run helpers. Explicit recovery
uses the already selected connection, matched routing/trust/identity evidence and
namespace UID, followed by a separate cleanup review. New read-only recovery cannot
delete. Unknown-UID records offer inspection or explicit local forgetting only;
forgetting does not claim remote cleanup.

## Limits and verification

Node scheduling and Pod exec expose no atomic cross-resource UID precondition.
Fresh checks reduce but cannot remove same-name replacement races at those APIs.
Deletion does have an atomic UID condition. A bounded Pod lifetime cannot guarantee
cleanup on an unreachable node or delete its API object after application failure.
Connection fingerprints are routing evidence, not a universal cluster identity.

Pure models, filesystem races, owned HTTP faults, public Pilot controls and source/
installed PTYs establish separate contracts. An early disposable-kind trial must
exercise real creation, exec and UID cleanup before extensive UI implementation.
Final qualification additionally covers admission/RBAC/scheduling failures,
interruption, recovery, unrelated objects, platform coverage and protected checks.
See [acceptance](../internal/acceptance/node-shell.md) and
[quality policy](../quality.md).

The upstream [node diagnostic guide](https://kubernetes.io/docs/tasks/debug/debug-cluster/kubectl-node-debug/),
[scheduling guide](https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/)
and [DeleteOptions contract](https://kubernetes.io/docs/reference/kubernetes-api/definitions/delete-options-v1-meta/)
inform these independent implementation boundaries.
