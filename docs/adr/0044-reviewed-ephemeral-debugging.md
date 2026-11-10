# Reviewed ephemeral-container debugging

Status: implementation in progress; integration and actual runtime evidence are pending.

## Context

An ephemeral container is an irreversible addition to an existing Pod's spec.
It is neither an exec subprocess nor a temporary diagnostic Pod. Disconnecting
does not remove its declaration, restart it or establish process termination.
The selected Pod and target container can change while the operator reviews it.

## Decision

Use the captured per-context client for a conditional JSON Patch to the
`pods/ephemeralcontainers` subresource. Test the reviewed Pod UID and opaque
resourceVersion atomically, then append exactly one declaration. Require bounded
subresource discovery and a strict server dry-run before enabling a one-use,
default-Cancel confirmation. Edits invalidate the old review. Revalidation does
not automatically rebase, rename, weaken or retry the write.

The bounded Linux profile uses an explicitly entered digest-pinned image and
literal command arguments. It runs as a positive nonroot user/group, drops all
capabilities, disables privilege escalation and uses RuntimeDefault seccomp.
The operator may explicitly choose a writable root filesystem. Workload mounts,
environment, tokens, arbitrary profiles and resource reservations are not copied.
Inherited Pod namespaces, identity and image-pull context remain visible.

Bind a named regular/init target to its observed running instance. Alternatively,
explicitly choose Pod namespaces. Runtime support determines whether targeting
works and which processes are visible; API acceptance cannot prove that result.

Keep the permanent-addition receipt, readiness, remote container state and local
terminal state separate. An unverifiable or lost write response stays uncertain
and is never retried or adopted from a later matching name. A verified addition
with an unverified admitted profile cannot attach under that review.

Reuse `AttachService`, `ShellSession`, `ProcessRunner` and the embedded
`ShellScreen`. Fresh checks bind initial and explicit later attachment to the
observed declaration and running instance. One retained owner serializes polling,
reserves one local terminal and drains work before releasing its client.
Cleanup never deletes the Pod or removes an ephemeral declaration.

## Consequences

- Completed entries continue to occupy their names until the Pod disappears.
- A detached or disconnected debug process may remain alive remotely. Completion
  requires a fresh terminated status, independently of local process exit.
- Read-only mode permits session inspection, but blocks preparation, addition
  and attachment. Tightening policy stops local attachment without rollback.
- Strict Pod versions can expire during status churn; the operator reviews again.
- Admission can reject the fixed profile or change it beyond supported defaults.
  KubeRich does not relax policy or fall back to elevated privileges.
- Kubernetes attach is name-based and has no atomic UID/instance precondition.
  Revalidation reduces, but does not eliminate, its final connection race.
- Sessions retain at most 256 displayed remote rows and 32 local outcome records.
  Display limits do not turn an incomplete input into safe mutation authority.
- Real provider/runtime certification remains separate from owned Linux-cluster
  and local terminal evidence.

## Implementation and evidence

The pure model is [ephemeral_debug](../../src/kuberich/domain/ephemeral_debug.py);
the single-attempt [adapter](../../src/kuberich/adapters/ephemeral_debug.py) uses
the existing guarded mutation transport. The retained
[service](../../src/kuberich/services/ephemeral_debug.py) owns reads and terminal
leases. Actual outcomes and original failed attempts belong in
[acceptance](../internal/acceptance/ephemeral-debug.md), rather than this decision.
