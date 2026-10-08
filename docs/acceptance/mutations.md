# M01 #43 acceptance evidence

The implementation adds centralized guarded mutation services and the usable
`:annotate` action. Review captures context, namespace, API resource, object name,
UID, opaque resourceVersion and intended annotation. Cancel has default focus;
a separate deliberate Confirm sends one conditional JSON Patch. `:writes`
retains up to 32 public outcomes, with at most eight active writes. Read-only
policy applies before preparation, confirmation, revalidation and transport.

Immutable bytes start with server-side UID and resourceVersion tests. Confirmation
binds the exact prepared intent and captured path, is consumed once, and cannot
be transferred, replaced or reused. Changes to context/selection, UID/version,
permissions or write policy prevent submission. Context replacement and exit
retire the client before stopping/draining requests, including late starts and
owned receipt-decoding threads. Client credential/TLS cleanup follows the drain.

The adapter uses the owned SDK connection, captured TLS/proxy/impersonation and
credentials. It sends one request without redirects, HTTP retries or 401 replay.
A missing, malformed, oversized or mismatched response after request start is an
uncertain outcome: inspect the object before another confirmed operation.
Public status/history retains target, structural operation and safe outcome,
without request bodies, annotation values, credentials or raw server errors.

## Frozen verification

Production and tests were frozen at
`5ff1bb7263f39ef9fb669730ff2729726980079e`; production `src` tree:
`f60edb4ee0263eff71f98a55520cef8698af531c`.

| Linux interpreter | Complete suite | Seconds | Production lines | Production branches | Changed lines |
| --- | --- | ---: | --- | --- | --- |
| 3.12.12 | 2730 passed | 1889.30 | 7870/7923 (99.3311%) | 2240/2302 (97.3067%) | 498/511 (97.4560%) |
| 3.13.12 | 2730 passed | 1370.17 | 7870/7923 (99.3311%) | 2240/2302 (97.3067%) | 498/511 (97.4560%) |
| 3.14.3 | 2730 passed | 989.64 | 7721/7774 (99.3182%) | 2240/2302 (97.3067%) | 487/500 (97.4000%) |

All three inventories contain 83 production files. All 32 critical modules
passed 100% line and branch coverage in each interpreter.

The complete production inventory and 32 deterministic critical modules are
checked independently; no production exclusions or gate reductions were added.
Changed-line evidence compares the frozen source with base
`f906b3044e0a63ab34d6c88b68f5a1c6b7cf1559`.

The exact interpreter commands used in each root/detached worktree were:

```sh
uv sync --locked --python 3.12 --group dev
uv run --python 3.12 pytest --cov=kubetrol --cov-branch --cov-report=xml:/tmp/kubetrol-43-evidence/py312.xml --cov-report=json:/tmp/kubetrol-43-evidence/py312.json
uv run --python 3.12 python scripts/check_coverage.py /tmp/kubetrol-43-evidence/py312.json
uv run --python 3.12 diff-cover /tmp/kubetrol-43-evidence/py312.xml --compare-branch f906b3044e0a63ab34d6c88b68f5a1c6b7cf1559 --fail-under 90 --ignore-staged --ignore-unstaged --total-percent-float --format json:/tmp/kubetrol-43-evidence/py312-diff.json
```

Python 3.13/3.14 used the corresponding explicit interpreter and evidence names.
The root `.python-version` remains 3.12, so both sync and run explicitly selected
the detached-worktree interpreters and asserted their actual versions.

Ruff, formatting (327 files), strict mypy (98 files), plan validation, whitespace
and actionlint passed. Optional actionlint shellcheck/pyflakes integration was
disabled; those external tools are not claimed as passed. Wheel/sdist build and
Twine metadata checks passed. Exact-artifact locked and freshly resolved runtime
installations each audited 27 dependencies, found no known advisories and required
no policy exception. Local SBOM/NOTICE/provenance evidence is retained; this is
local verification, not a published or attested artifact.

## Behavioral and terminal qualification

The final focused selection passed 411 cases in 67.38 seconds. Eight UI cases
passed separately after the cleanup refinement, including three new lifecycle
regressions; eight earlier UI/native/package terminal cases qualified display. The full matrix
above is the final suite result, rather than a sum of focused selections.
The pure mutation module exercised all 132 executable lines and 38 branches.

Actual local HTTP/TLS contracts cover token/impersonation, anonymous connections,
401/403/404/409/422/429/5xx, UID/version race tests, successful writes with lost
responses, invalid/oversized/mismatched responses and refused TCP connections.
A real exec helper is invoked once and the actual PATCH is not replayed after
401. Repeated cancellation drains receipt decoding. Tests cover policy/target
changes, exact proof replacement/reuse, active/history bounds and unexpected
failure after a write was applied, retaining a public uncertain result.

Pilot covers 40×12 and 100×30, captured review, default Cancel, deliberate Confirm,
field/scope invalidation, read-only, pending-write Escape and owned exit cleanup.
Three actual PTYs cover source launch and fresh-wheel console/module launches,
rapid Tab/Shift+Tab field entry, exact key/value transport, review/default Cancel,
confirmation, history, 40-column resize and original terminal mode restoration.
SVG frames and local-font PNG inspection previews are retained in the raw evidence.

## Actual disposable Kubernetes

```sh
uv run python -m scripts.verify_mutations_kind --kind /tmp/kubetrol-tools/kind --evidence /tmp/kubetrol-43-evidence/kind-final.json
```

The newly owned Kubernetes 1.36.4 cluster used the pinned node image and verified
Docker-node/API/config ownership before fixture writes. A real ConfigMap
annotation changed while existing data/annotations remained. Actual JSON Patch
rejected stale versions and old UIDs after same-name recreation without applying
the intended value. The service rejected replacement and proof reuse. An explicitly
impersonated get-only user read successfully and received actual patch RBAC denial.
Caller configuration remained unchanged. The cluster was deleted and absence
verified. `kind-final.json` records the eight checks and cleanup; no maintainer
context or cloud cluster was used.

## Corrected trials and remaining limits

An initial `_task` field collided with Textual's message-pump ownership; it was
renamed and the owned trial process was terminated before final verification.
Pilot mount waits now respect DOM lifecycle. Actual rapid PTY input caught Tab
placing text in the preceding field: priority, screen-scoped focus bindings
corrected it. The PTY harness waits for the main view to be visible after Escape
before issuing the next command. This does not claim to resolve every broader
focus/transition issue tracked in #61. Invalid escaped UTF-16 text and unexpected
post-write task failures were also corrected before the frozen source. A later
owned probe found F4 closing the SDK before a pending Review read was drained.
The client-close hook now drains annotation preparation/result waiters, and
concurrent cleanup cancels the reader once. Three actual HTTP/owned-thread Pilot
regressions verify F4, Escape and application shutdown, with thread completion
and waiter termination before SDK credential/TLS cleanup. The initial 3.14
suite (2727 passed) and intentionally interrupted 3.12/3.13 suites are retained
under `before-review-cleanup-fix`; they are not final-source qualification.

Hosted Actions cannot start due to the current account payment/spending-limit
annotation; the DCO check runs separately. DCO succeeded on the frozen implementation head; the final documentation
delivery head is checked again before merging.
The maintainer-authorized local private-development exception applies to this
merge. macOS, real cloud/provider trials and full hosted public-release/platform
qualification remain outstanding. No tag, release or package was published.

Editor, scale/rollout and deletion remain #44/#45/#46. OPS01 remains planned with
partial evidence; these services and annotation behavior do not claim complete
workload-operation or K9s parity.

Raw evidence: `/tmp/kubetrol-43-evidence` (local files, not durable hosted artifacts).
