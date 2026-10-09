# Dynamic custom-resource backend: C05 #52

## Implemented behavior

The existing per-context SDK transport now supports arbitrary discovered
group/version/resource families through generic LIST/WATCH/GET. Canonical names
and explicit groups resolve aliases without guessing; one family with multiple
served versions is not ambiguous. Server preferences are preserved, and explicit
versions never fall back silently. Namespace scope comes from discovery.

Opt-in Table reads request full objects and keep bounded immutable headers/cells
separate from raw resource manifests. First-page ordinary JSON is accepted;
malformed/unsupported conversion and mid-page representation changes discard the
whole collection before one JSON fallback. Negotiation failure is specific to one
GVR. Permissions, resource identity, pagination and snapshot-limit failures remain
errors. Each watch opening owns its headers and checkpoint; unsupported Table
events force a JSON relist. Repeated cancellation drains real parsing workers.

Workspace refresh owns and drains old readers/watches, retains pending namespace
intent and rebinds a newly preferred version on the same client. Removed selected
types fail explicitly; core selection remains usable. Replacing a context hides
the prior catalogue. No generic terminal command, Table presentation or custom
jump chain is claimed here: B06 #53 owns visible browsing, U02/U06 later own
custom configuration/jumps. CORE01/RES06 remain partially evidenced.

## Measured local evidence

On actual Linux/Python 3.12.12:

```sh
uv run --locked --python 3.12 pytest tests/unit/test_resources.py tests/unit/test_tables.py tests/unit/test_views.py tests/unit/test_watches.py tests/contract/test_resources.py tests/contract/test_watches.py tests/contract/test_workspace.py tests/contract/test_custom_resources.py tests/contract/test_custom_workspace.py -q --cov=kuberich --cov-branch --cov-report=json:artifacts/custom-resource-52/focused-coverage.json
```

The expanded cohort passed **397 cases in 26.48 seconds**. Focused critical
receipts are resources **201/201 lines, 68/68 branches**, Table **102/102,
36/36**, views **112/112, 38/38** and watches **156/156, 62/62**. These focused
results are not whole-production or platform qualification. The final HTTP
subset passed **46 cases in 2.23 seconds**, including literal URL name encoding.

The actual loopback contracts cover paged/full-object Table reads, cluster and
namespace scope, 406/415 and invalid metadata fallback, raw representations,
schema changes, continuation expiry/repeated tokens/version mismatch, identity
and memory bounds, ordinary watch events, fresh headers on renewed streams,
original permission failures and repeated thread cancellation. Workspace contracts
cover install/remove/preference/context changes and partial forbidden discovery.

Initial fixture errors supplied the wrong List apiVersion and an unsupported
helper keyword; correcting those fixtures preserved real structural validation.
They are retained as failures, not counted as passes. A superseded whole local
run was deliberately interrupted after 897 passes to qualify literal GET URL
encoding; that incomplete run does not qualify the final head. An initial real-cluster
verifier used a merge body with the SDK's default JSON Patch representation;
the corrected verifier supplies actual JSON Patch operations. Cluster deletion
was verified on both failed and successful attempts.

## Actual disposable cluster

```sh
uv run --locked --python 3.12 python -m scripts.verify_custom_resources_kind --kind artifacts/operations-46/tools/kind
```

The rehearsal uses the existing explicit kind owner, SHA-pinned Kubernetes
1.36.4 node and a uniquely named cluster with a private generated kubeconfig.
Eight checks qualify CRDs of both scopes and served versions, cross-group alias
collision, paged server Table reads with full GET objects, header/headerless
watch events and drained cancellation, served-version change without SDK
replacement, CRD removal with core reads, and unchanged caller configuration.

Two transport cases are intentionally labelled injections: a private loopback
gateway requests real ordinary JSON rather than Tables, and legacy rather than
aggregated discovery. It forwards to the actual owned TLS session; restricted
discovery/resource responses come from actual RBAC. Only the owned cluster's
default discovery grant is removed. This does not claim the pinned apiserver
lacks Tables or aggregated discovery. `artifacts/cluster/custom-resources.json`
records those distinctions and deletion/absence verification. No maintainer or
cloud context is used.

## Candidate qualification and limits

Ruff, formatting, strict typing, the whole production/changed-line/critical
coverage gates, clean packaging/native regressions, all four required Linux and
macOS jobs and the required real-cluster verifier remain merge requirements.
The final measured receipt and current-head run are recorded on
[#52](https://github.com/carloshm91/kuberich/issues/52), the live acceptance source.
The new Table domain brings the critical inventory to 40 modules without coverage
exclusions. No dependency, version, release tag, package or website publication
is part of this issue.

Table cells/headers are untrusted bounded data. Generic UI formatting must apply
the existing control-sequence/markup and secret boundaries; this backend does not
render them or evaluate JSONPath. Discovery verbs describe supported operations,
not RBAC grants. Partial discovery cannot prove an omitted resource is absent.
Read-only contracts do not imply compatibility with every aggregated extension
server, custom conversion webhook or later mutation schema. Those actual servers
and final provider/performance qualification remain separate evidence.
