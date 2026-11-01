# Bounded large-collection behavior

Recorded on 2026-11-01 for Q12 #213. This is local functional evidence, not
provider certification, release qualification or a throughput claim.

## Delivered behavior

- Initial LIST retains a deterministic prefix bounded by 10,000 records,
  64 MiB of resource/server-cell payloads and 256 pages. Transport responses,
  watch frames and replay identities retain their existing independent bounds.
  A response that ignores `limit` cannot create another unbounded record tuple.
- Paged progress and limit snapshots explicitly carry incomplete membership.
  A healthy WATCH continues from the authoritative collection resourceVersion;
  skipped rows advance its checkpoint without claiming complete membership.
- Retained updates/deletions continue normally. A newer record that cannot fit
  drops its old retained UID instead of presenting stale data as current.
  Deleting retained rows cannot establish that unread initial rows disappeared;
  only a fresh complete list clears incompleteness.
- `:server label EXPR` and `:server field EXPR` narrow API requests explicitly.
  `clear` removes selectors, `compact` requests metadata-only generic Table
  rows, and `full` restores full payloads. Query changes replace the captured
  scope/revision; navigation history retains server and local queries separately.
- The persistent `INCOMPLETE` title survives selection notices. Empty local
  results explicitly refer to retained rows. Event inspection and aggregate-log
  membership also identify incomplete data; source/reader notices retain it.
- Compact objects preserve their actual PartialObjectMetadata type and identity.
  Server cells remain typed. Table refusal falls back to full JSON. Native and
  core Pod/Service views retain full objects. Inspection reads a fresh full
  object, and jumps requiring absent fields offer `:server full` recovery.

## Verification

The final relevant functional cohort passed **957 tests**, with exactly two
performance/runtime controls explicitly deselected, in **244.81 seconds** on
Linux CPython 3.12.12. Two additional owned query-refusal contracts passed in
7.95 seconds against identical production bytes. The latter coverage append
adds only those same-source observations; it does not combine changed source.

The cohort covers domain resources/queries/tables/watches/views/targets, CLI
launch/configuration, real loopback HTTP pagination/watch/workspace/inspection/
aggregate logs, and real Textual command/history/generic/jump/inspection/log
flows. No maintainer kubeconfig or active context was used.

A 50,000-object owned source fixture uses the unchanged production limits:
twenty 500-object pages retain 10,000 rows and stop following continuation.
One hundred subsequent state events keep the row/payload/replay bounds and
advance to the last resourceVersion. This is a functional source-size/control
test; it does not schedule or measure 100 events per second.

Coverage of the issue diff, including the new module, is **234/238 changed lines
(98.3193%)** against the local exploration base
`563a5610608e73bceacae2b88c2e203a62230363`. The new deterministic
`domain/resource_queries.py` joins the enforced critical inventory and reaches
**43/43 lines and 22/22 branches**. Existing `domain/watches.py` reaches
**174/174 lines and 68/68 branches**. No exclusions were added.

The limited cohort measures **11,468/18,642 production lines (61.5170%)** and
**2,196/5,490 branches (40.0000%)** over the entire package. These are not the
required global 90% gates. Final integrated full-package/platform qualification
remains necessary. Strict typing passes all 189 production files; Ruff,
formatting, the public-test-boundary check and plan validation pass.

## Preserved failures and review

Raw local receipts remain under `artifacts/collections213/`:

- An initial command referenced a nonexistent test path: zero collected, exit 4.
- The corrected core cohort had 340 passes and one real weak-reference failure.
  The new list local held the initial snapshot after deletion; releasing that
  reference immediately after WatchState construction fixed the existing case.
- A new Pilot case had a test-only AppState attribute error, then passed after
  using its actual public `status` field.
- The first broad cohort was interrupted after 272 passes, exit 2. Two existing
  injected ListWatch factories did not forward the new optional public kwargs;
  one waited indefinitely for an event its failed owner could not produce.
  The factories now forward kwargs, preserving the same recovery scenarios;
  the event wait is externally bounded. The interrupted run is not a pass.
- The corrected focused set passed 272 tests in 8.24 seconds before the final
  complete relevant cohort above.

An answer-only Argon review returned no findings in 68.96 seconds. Consumption
of the 82,811-byte source/diff packet was verified by a unique nonce and an exact
source quote. The review is supporting evidence, not a replacement for the
owned HTTP, cancellation, memory-retention or Pilot tests.

## Owned Kubernetes wire checks

The owned context verifier creates three ConfigMaps with controlled payloads in
a generated namespace. A unique owner-label selector isolates these fixtures
from controller-created objects. Full JSON and compact Table lists use one-item
pages and must preserve the same UIDs and namespace. Compact rows must contain
actual PartialObjectMetadata, omit ConfigMap data and retain fewer payload bytes.
Intermediate snapshots must report incomplete progress with a consistent
resourceVersion; the three-page final snapshots must report complete membership.

A role-label query excludes a deliberately nonmatching fixture. Adding a name
field selector further excludes the other matching fixture. A fresh GET through
the same Table reader must recover the original full data and UID. One actual
MODIFIED event must retain the UID and changed annotation while omitting data;
the compact watch is then cancelled and awaited. Namespace
deletion is requested in `finally`; the existing owned-cluster boundary verifies
node deletion and absence. The context receipt records the observed full and
compact retained bytes alongside each assertion's result.

These checks exercise real Kubernetes negotiation and pagination with small
fixtures. They do not measure oversized-cluster throughput or replace the
existing deterministic cap, watch, cancellation or full-platform qualification.

The initial real probe failed before the compact watch: Kubernetes 1.36.4's
ConfigMap printer declares Data as string but sends its count as an integer.
A separate shape-only observation confirmed a valid Table and
PartialObjectMetadata followed by ordinary JSON fallback. Both failed originals
and the diagnostic source/hash remain retained; no payload values were printed.
The [upstream column definition](https://github.com/kubernetes/kubernetes/blob/v1.36.4/pkg/printers/internalversion/printers.go#L338)
and [printer](https://github.com/kubernetes/kubernetes/blob/v1.36.4/pkg/printers/internalversion/printers.go#L2420)
show that mismatch explicitly.

The decoder normalizes only exact signed-64-bit integers advertised as strings
to decimal text. This preserves visible generic values and homogeneous declared
string sort keys. Booleans, floats, date mismatches, nested values and out-of-range
integers retain their refusal behavior, as do all metadata/scope/payload bounds.
ConfigMap and Secret server-cell redaction remains unchanged. A regression with
the observed printer shape failed before this correction; range, projection and
stable sorting controls accompany it. Raw evidence is retained under
`artifacts/issue213-wire-kind/`.

## Limits and stable certification

The retained 64 MiB bound accounts for resource payloads and printer cells, not
total process RSS or server memory. No exact global count is inferred from the
retained subset or optional remainingItemCount. Reconnects may retain explicitly
stale data until a fresh list succeeds; existing permission/protocol failures
remain real errors.

The maintainer made large-workload latency/margin figures advisory for 0.x on
2026-11-01. This work does not claim a measured 100-events/s rate, p95 below
100 ms with 20% margin, a process-RSS plateau or a completed soak. Stable
certification keeps those goals in Q06 #88. No threshold was raised and no new
benchmark/provenance subsystem was introduced.
