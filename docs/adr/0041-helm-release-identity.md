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

## Catalog and lifecycle extension

M09 #233 keeps the same service/client owner and adds a Kubernetes-independent
catalog service. Application HTTP owns classic indexes and explicitly registered
OCI chart paths, private Basic/bearer credentials, independent CA trust and
separate approved token/download origins. No ambient Helm/Docker repositories,
helpers, cookies, proxy credentials or Kubernetes identity enter catalog HTTP.
Metadata/credential files use private no-follow atomic storage and exact receipt/
generation checks; external replacement never silently rebases existing authority.

Frozen ChartSnapshot bytes bind package SHA-256, catalog revision/generation and
OCI manifest/layer digests. A cumulative archive policy covers bundled directory/
compressed dependencies and schemas before every native consume. V2-only packages,
a supported subset of dependency constraints, supported offline schema dialects
and local fragment references deliberately limit accepted input. Legacy
requirements metadata, remote dependency/schema loads and signature-verification
claims are excluded. Digest integrity alone is not publisher authenticity.

Install, upgrade and uninstall use explicit release addresses without fabricated
UIDs. Namespace active UID, complete selected-backend storage identity, current
client/request, chart/values/options and live ordinary destination UID/version or
true absence bind one-use review authority. Cached desired/old destinations share
256-object/8-MiB retention limits. Native dry-run precedes a redacted live desired-
state diff; supported named CREATE admission uses separate strict `dryRun=All`
requests. Those passes neither simulate final update/SSA/delete patches nor reserve
batch quota. Hooks have separate discovered effects; CRDs are skipped. Release JSON
does not serialize a complete bundled-subchart CRD inventory for uninstall.

Values are private opaque leases. Fresh defaults or current supplied values are
explicit choices; upgrade resets values with the complete override file. Trusted
editor disclosure is separate and one-use. Every Helm verb/probe has explicit
kubeconfig/context/namespace and private Helm plus credential-empty Docker config;
debug and plugins are off. No download, post-renderer, force/adoption or automatic
rollback/cleanup route bypasses review. Confirmation is consumed synchronously
before its admitted task can await. Cancellation drains subordinate owners before
private-file removal and client closure, while observations preserve launched-write
uncertainty. Final rendering and multi-object writes remain non-atomic.

Uninstall defaults to kept history and explicit background propagation. Purge,
hooks, cascade and waits are reviewed; history removal and ordinary resource
absence/retention/deletion-pending are separate observations. Helm 3 name-based
deletion and Helm 4 skip/unverifiable ownership behavior cannot promise atomic
deletion. CRDs, kept objects, hook effects, PVC data and finalizers may remain.

## Consequences and verification

The application retains at most 500 list rows, 200 history rows, bounded process
and document bytes and complete bounded storage identity pagination. Incomplete,
stale, denied and unknown states remain visible. Helm's internal read/memory
cost and unsupported storage/status semantics are not hidden by these limits.

Pure contracts, actual owned fake CLI/HTTP fixtures, Pilot/PTY trials and the
original chart in `scripts/verify_helm_kind.py` cover their distinct boundaries.
The chart uses both pinned tools and storage drivers with actual rollback,
hooks, denied metadata, recreation, timeout and cancellation. The original M06
install/upgrade fixtures remain historical setup evidence; new product lifecycle
proof is recorded separately in [M09 acceptance](../internal/acceptance/helm-lifecycle.md).
Final coherent native, installed and exact-head hosted checks remain pending there.
Follow the
[quality policy](../quality.md); local evidence is not provider/native release
certification. See the [user workflow](../workloads.md#browse-helm-releases-in-development-source).
