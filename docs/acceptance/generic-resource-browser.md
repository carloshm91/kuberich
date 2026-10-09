# Generic resource browser: B06 #53

The shared terminal workspace now resolves discovered families and served
versions through qualified commands, literal inline completion and deferred
explicit startup commands. Both resource scopes use the existing per-context
LIST/WATCH owner. Server columns retain immutable schema identity, typed sorting
and stable metadata fallback; transient column errors preserve the previous
layout. Captured-UID YAML/details/events retain unknown manifest fields under
the existing redaction policy. Generic actions remain read-only.

The implementation reuses `domain/custom.py`, `CustomTable` and the existing
incremental table/worker behavior. Navigation stores group, requested version and
printer headers. Schema replacement resets incompatible sorts rather than
reinterpreting previous positional fields. The render predicate also captures
the immutable layout, rejecting a pending projection after `:columns` changes.
Context/GVR replacement rejects prior rows; Escape from the local context
workspace during reconnect preserves the generic route even without an available
captured parent view. Repeated worker cancellation drains before cleanup.

## Local behavior receipts

On actual Linux/CPython 3.12.12, the expanded initial cohort passed **118 cases in
121.31 seconds**:

```sh
uv run pytest tests/unit/test_generic_commands.py tests/unit/test_navigation.py tests/ui/test_custom_resources.py tests/ui/test_resource_workspace.py tests/ui/test_standard_resources.py tests/ui/test_context_workspace.py tests/terminal/test_custom_resources.py -q --tb=short
```

The final race/projection/command cohort passed **23 cases in 35.05 seconds**
with branch coverage enabled:

```sh
uv run pytest tests/ui/test_custom_resources.py tests/contract/test_custom_projection.py tests/unit/test_generic_commands.py -q --tb=short --cov=kuberich --cov-branch --cov-report=json:artifacts/custom-browser-53/final-focused-coverage.json
```

These tests use real owned loopback HTTP and Textual Pilot at 40×12 and 100×30.
They cover both scopes, ambiguous aliases across groups, multiple served versions,
built-in alias precedence, deferred startup, raw GET inspection, typed cells,
schema replacement with retained incompatible old rows, transient configuration,
hidden-field filtering, history, namespace/context routes, 406/malformed Table
fallback, RBAC failures, removal/core recovery, held projection after context/GVR
and column changes, reconnect/context/Escape, and owned repeated cancellation.

The unchanged critical column domain measured **69/69 lines and 20/20 branches**
in the focused pure/table cohort. This focused receipt does not substitute for
whole-production coverage or final-head platform qualification.

The actual native source command was
`uv run pytest tests/terminal/test_custom_resources.py -q --tb=short`:
**one case passed in 3.18 seconds**. It exercises initial explicit v1beta1 discovery,
literal/redacted server fields, Enter/details/YAML, transient selection/errors,
both scopes, all namespaces, small-window resize, discovery refresh and terminal
restoration. The fresh-wheel console and module trials run the same owned
fixture outside the checkout. Sanitized terminal transcripts/geometry/mode
receipts are retained under `artifacts/terminal`; tests assert no synthetic
credentials or confidential printer cells appear in output.

Initial failures included a malformed HTTP fixture that returned a Table even
after JSON fallback, premature assertions before asynchronous rows rendered,
and a real passive-render notice race. Fixtures now honor representation;
command errors remain visible across passive generic renders. A superseded whole
attempts were interrupted after 888 and 931 passing cases while freezing final
source/help and the explicitly bound immutable-layout predicate. Those partial
receipts are not candidate qualification.

## Actual disposable cluster

```sh
uv run python -m scripts.verify_custom_resources_kind --kind artifacts/custom-browser-53/tools/kind --evidence artifacts/custom-browser-53/kind-final.json
```

The expanded required verifier passed all **nine checks** using the pinned
Kubernetes 1.36.4 image and kind v0.33.0. Its new actual-API Pilot clause covers
generic columns, numeric sorting, captured YAML/version identity, ambiguity,
namespaced/cluster/all-namespace scopes, history, same-client refresh, observed
live CRD patch, selected-CRD deletion/failure and core recovery. The existing
checks retain real pagination, full objects, multiple served versions, watch
events, conversion fallback and restricted discovery/resource RBAC.

The receipt explicitly labels ordinary-JSON and legacy-discovery representation
injections through an owned gateway. Denials come from the real owned cluster.
The shared cluster owner uses a unique disposable context and private generated
kubeconfig; caller configuration bytes remain unchanged. Cluster deletion and
absence were verified. No maintainer or cloud context is used.

## Candidate qualification and limits

Ruff, formatting and strict application/verifier types pass. The final source
is undergoing the full suite, independently enforced production line/branch,
changed-line and 41-module critical gates, artifact checks and all four required
Linux/macOS hosted jobs. The final measured receipt belongs to
[#53](https://github.com/carloshm91/kuberich/issues/53), the live status source;
focused receipts alone do not close it.

Generic live browsing requires advertised LIST/WATCH support and stable API UIDs;
individual inspection requires GET. Printer headers/cells are untrusted bounded
values, displayed literally and redacted using the existing credential and
opaque Secret/ConfigMap rules. Arbitrary custom fields are not automatically
confidential. No JSONPath evaluation, schema-generated editor, mutation, permanent
column preference, custom hotkey, reactive jump chain or paid parity is claimed.
M05/U02/U06 retain those owners; real provider/conversion-webhook and final
compatibility/performance qualification remain separate evidence. No dependency,
version/tag, distribution or website publication is part of B06.
