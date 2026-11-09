# 0041: Helm release identity and owned CLI operations

Status: implemented in development source; cumulative release qualification is separate.

## Context

A Helm release is not a Kubernetes API resource. Its namespace/name/revision
does not provide a Kubernetes UID. The optional Helm executable reads release
storage and may write multiple resources, execute chart hooks and leave partial
effects. Ordinary status JSON itself contains sensitive values and manifests.

## Decision

Keep Helm records in `domain/helm.py`, strict parsers/argv in `helm_cli.py`, and
bounded document redaction in `helm_documents.py`. Use a native view route and
metadata-only navigation bookmarks; never invent a `ResourceTarget` UID for a
Helm release. The initial CLI contracts are exactly 3.22.1 and 4.3.1, with Secret
or ConfigMap storage. Version-specific flags are deliberate and tested.

`adapters/helm.py` owns the optional tool through `ProcessRunner`, captured
credential/provider environment and a staged private per-context kubeconfig.
It removes ambient Helm destination/auth overrides, disables plugins and passes
literal context/namespace argv. The version probe runs only on explicit Helm
use. Dedicated built-in read/mutation process purposes enforce `AccessPolicy`;
Helm read commands are not arbitrary configured plugin commands.

`services/helm.py` pins inspections to complete metadata-only storage history
and exact storage UID/resourceVersion. Reads, disclosure and rollback validate
the captured client, session, workspace generation and revision before and after
effect boundaries. Storage metadata negotiation fails closed; it never falls
back to retaining complete Secret/ConfigMap payloads for identity checks.

Preparation and confirmation create one-use disclosure or rollback intents.
Options or scope changes invalidate confirmation; execution consumes the exact
owned token before its first await. Read-only policy is checked before mutation
preparation and again at execution. Default hooks are disabled. Explicit prior
revision, wait, timeout and hook effects appear in the review.

This is not an atomic compare-and-swap: Helm rereads release names/revisions
after preflight and another actor may intervene. Success requires an observed
expected next deployed revision. A completed command with a verified new failed
revision reports failed/possibly partial; pending, lost, cancelled or unverifiable
outcomes remain unknown. Cancellation still propagates after drain, while the
safe `last_rollback` record preserves uncertainty. No automatic retry or
compensating write follows.

`services/helm_workspace.py` owns one replaceable list task; workspace integration
invalidates requests synchronously and closes service operations before the
client. Detached inspector workers remain owned and drained; revealed text is
cleared on section/screen/scope departure. Domain logic is independent of Textual.

## Consequences and verification

The application retains at most 500 list rows, 200 history rows, bounded process
and document bytes and complete bounded storage identity pagination. Incomplete,
stale, denied and unknown states remain visible. Helm's internal read/memory
cost and unsupported storage/status semantics are not hidden by these limits.

Pure contracts, actual owned fake CLI/HTTP fixtures, Pilot/PTY trials and the
original chart in `scripts/verify_helm_kind.py` cover their distinct boundaries.
The chart uses both pinned tools and storage drivers with actual rollback,
hooks, denied metadata, recreation, timeout and cancellation. Fixture install/
upgrade operations do not expose a product lifecycle feature. Follow the
[quality policy](../quality.md); local evidence is not provider/native release
certification. See the [user workflow](../workloads.md#browse-helm-releases-in-development-source).
