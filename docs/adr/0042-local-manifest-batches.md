# 0042: Anchored local sources and reviewed manifest batches

Status: implemented; complete source/platform gates are enforced by the protected PR.

## Context

A local file is neither a Kubernetes object identity nor an authorized write.
Kustomize can read other files or invoke external functionality. Declarative
apply must preserve unrelated live fields, remove previously managed fields
when omitted, and distinguish a genuinely absent name from a replaced object.
Filesystem edits and multi-resource API changes are not transactions.

## Decision

Keep bounded YAML/resource decisions in `domain/manifests.py` and local dependency
decisions in `domain/kustomize.py`. Preserve the existing single-object editing
parser while adding a bounded multi-document entry point. Raw source/request
bytes stay in short-lived, non-represented records; ordinary previews are redacted.

`ManifestFiles` captures an explicit physical root and uses no-follow directory
descriptors and entry identities. Source capture freezes bytes and hashes, not
an assertion that the surrounding filesystem is transactional. Parent/root
replacement or changed inputs invalidate reviews. Local Save replaces only a
reviewed ordinary entry; its outcome distinguishes changes already committed
from cancellation or cleanup failures. Trusted editors receive private drafts
only after disclosure bound to the captured source identity.

Local Kustomize validates a finite local dependency closure before starting
`kubectl kustomize`. Render only frozen private copies with an empty kubeconfig,
private cache, root-only loading and plugins/Helm/functions disabled. Reject
remote references and unsupported path-bearing features before launch. Renderer,
parser, file workers and staging remain owned until drained; listing never probes
helpers or connects to a cluster.

Add `ResourceAddress` for an exact named destination without an observed UID.
Keep `ResourceTarget`'s real nonempty UID invariant. Only the manifest service
admits named creation; ordinary row patch/delete operations retain their existing
captured-target contract. Write history can represent either kind explicitly,
without a placeholder UID. The mutation-source port exposes a read-only target
property so existing services retain their narrower target types.

For existing objects, use client-side apply's **server dry-run** as a merge
preview. Verify its GVK/name/namespace/UID/version, normalize only permitted
server metadata, derive the existing UID/version-conditional JSON patch and
validate that exact patch again. Persist through the owned SDK transport, never
through a replay-capable delegated `kubectl apply`. This introduces no SSA
field-ownership promise and preserves last-applied merge semantics.

For absent names, validate and commit the same named POST body, including its
last-applied annotation. A create dry-run can have no resourceVersion; that is
not a persistent identity. Actual successful creation still requires a real UID
and version. An atomic POST conflict never becomes an update. Delete captures
real UID/version and uses API preconditions; accepted deletion can remain pending.
DELETE validation derives a `DeleteOptions` body with `dryRun: [All]`; a query-only
option does not override a nonempty options body. The confirmed request retains
the reviewed preconditions and excludes the simulation flag. Actual API trials
must independently prove that preparation preserves ordinary and finalizer-backed
stored objects before any confirmation.

One-use confirmation binds exact source, scope, ordered destinations, requests
and dry-run results. A fallback namespace applies only to documents without one;
changing it invalidates the plan. Original workspace identity remains captured
independently. Execution admission retires the prepared plan synchronously, so
cancelling a queued task cannot preserve a reusable proof. Outcome lists belong
to one admitted execution and cannot be reset by a competing confirmation.
Execute sequentially, revalidate each item and stop on the first
failure or uncertainty. Preserve completed results and mark every later item
unsent. There is no compensating rollback or automatic write replay.

The App's priority Escape route delegates to each manifest screen's awaited Back
handler. Parent navigation waits for that screen's file/process/request cleanup;
generic modal dismissal followed by asynchronous unmount cleanup is insufficient.

## Consequences and verification

All resources must validate before confirmation. Namespace/CRD prerequisites
require separate batches; generated names, force, prune and remote rendering are
outside this contract. Read-only mode blocks editor/save and mutation preparation
at services as well as UI controls. Admission errors expose only bounded codes
and finite known field paths, because freeform text can quote submitted values.

Pure decisions, filesystem races, actual helper processes, controlled HTTP
faults, public Pilot controls and real terminal handoff provide separate evidence.
An early owned-kind proof establishes create/update/managed-field removal while
preserving an unrelated live field before extensive UI work. Complete feature
qualification additionally needs real policy/conflict/partial/delete/cancellation
effects, final frozen-source coverage and required hosted checks. See
[the acceptance record](../internal/acceptance/local-manifests.md) and
[quality policy](../quality.md).
