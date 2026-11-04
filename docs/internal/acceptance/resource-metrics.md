# O01 #68: current resource metrics

This implementation uses the existing per-context KubernetesSession and
ResourceReader. It selects the actual served `metrics.k8s.io` version from
existing discovery; metrics records can omit UID/resourceVersion. It performs
serialized bounded collection reads, never a subprocess or request per row.
One current batch is retained, with no historical cache. Expired samples become
stale without displaying usage; failures replace old usage with explicit status.

| Acceptance | Actual controls |
| --- | --- |
| Quantities/units and zero | Decimal/binary quantities, nano/micro/millicores, M versus Mi, bounded exponents/length/amounts, NaN/infinity/malformed inputs; measured zero is distinct from absence |
| Denominators | Named usage/request, usage/limit and Node usage/allocatable; zero/absent N/A, absent limits unlimited, values above 100%, partial member percentages suppressed |
| Actual membership | UID controller chains for Deployments/ReplicaSets, StatefulSets, DaemonSets, Jobs and CronJobs/Jobs; foreign same-name UIDs excluded; no desired-replica multiplication or label inference |
| Availability | Discovery missing/forbidden, endpoint 403/404/503/401/500, missing sample, stale HTTP 200, bounded malformed containers/keys and actual HTTP timeout |
| Independent RBAC | Same client with Pod metrics allowed/Node metrics denied and the reverse; cluster Pod-list denial keeps permitted Node usage/capacity available and labels Pod allocation incomplete |
| Scope/identity | Name-only samples bind captured/reverified Pod UIDs; samples preceding actual creation timestamps are rejected; namespace/context/exit drain real HTTP requests with unchanged caller fixture config |
| Poll/cache ownership | Serialized batches, no overlap, one replaceable current observation, 15 seconds after batch completion; 60-second expiry; old generation discarded and parsers drained |
| Terminal UI | Pilot refreshes numeric sort while retaining selected UID; an open container sees valid → zero → forbidden → unavailable → valid, then expires without a new sample |
| Generic resources | Arbitrary extended-resource keys expose declared requests/limits and Node capacity/allocatable, with no GPU utilization invented from CPU/memory samples |

Effective scheduler allocation for init/sidecar/overhead/Pod-level budgets and
observed resize is deliberately marked uncertain. It does not turn an application
container sum into a full Pod reservation; usage remains useful and container
percentages use only declared container budgets. Missing requests and partial
membership do not acquire invented full denominators. Node usage includes node
processes, so it is independent of the sum of Pod usage/requests.

Workload timestamp is the oldest member timestamp; window is the largest member
window. Different members need not have one atomic measurement interval. Ordinary
LIST collection/response/deadline bounds remain intact (10,000 rows, 64 MiB), with
128 containers and 128 resource keys per parsed mapping. No scope installs
metrics-server, and no caller Kubernetes context is selected for tests.

## Primary references and audit traceability

- [Kubernetes resource metrics pipeline](https://kubernetes.io/docs/tasks/debug/debug-cluster/resource-metrics-pipeline/): CPU average, memory working set, timestamp/window, discovery-served Metrics API. Current docs use v1; contracts cover v1 and v1beta1 without assuming either endpoint.
- [Kubernetes resource management](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/): requests/limits, units, Pod-level budgets and resizing.
- [Kubernetes sidecar allocation](https://kubernetes.io/docs/concepts/workloads/pods/sidecar-containers/#resource-sharing-within-containers): effective Pod allocation differs from a naive application-container sum.
- Audit rows RES04, EXT04 and OBS01 remain linked to O01 #68 in [capabilities](../../capabilities.json). The [pinned source inventory](../k9s-source-inventory.json) retains its original K9s v0.51.0 commit/digests and task links; these references are evidence, not copied source or a parity claim.

## Verification record

The focused Linux CPython 3.12.12 command passed **135 tests**:

```sh
uv run pytest tests/unit/test_metrics.py tests/unit/test_metrics_projection.py tests/contract/test_metrics.py tests/ui/test_metrics.py tests/ui/test_pods.py tests/ui/test_interactions.py -q -n 4 --tb=short
```

New pure metrics and quantity modules measured 100% lines and branches in the
first focused coverage campaign. Its four UI assertion failures were retained:
new default columns required updated expectations, and the first live-metrics
Pilot run revealed that persisted default-view preparation still hid the new
columns. The corrected behavior passed the focused command above. Initial
fixture/import/auth-expectation mistakes and their failed logs are retained in
`/tmp/kuberich68-*.log`; none counts as a passing gate.

Full source/static/type/private-access, complete production coverage, changed-line
coverage and applicable owned-cluster results will be appended after the frozen
local campaign. This record currently makes no hosted, macOS, native artifact,
real cloud-provider or public-release qualification claim.

## First frozen source campaign and corrections

The initial frozen source was `1b2af31e5fa52c3786425e87727724bcea07508e`.
The local phase runner passed plan/source import, Ruff/format, private-access,
the actual workflow strict-type target union and startup's hard controls.
Startup retained advisory offline and first-paint timing misses; the import
budget was met. Original limits and 0.x advisory/enforcement flags are unchanged.

The suite printed **28 failed, 7,358 passed, 5 skipped** before the qualification
owner was interrupted to correct the already diagnosed source/fixture faults.
The owner exited 130; `source-qualification-1/report.json` records cancellation,
a failed test stage, reaping and a drained owned process group, without a forced
kill. All recorded owner/worker PIDs and 117 retained `*.pid` witnesses were absent
before editing. These are failed/interrupted results, not qualification. The
five skips are existing actual-macOS/native-Homebrew-only lanes.

The retained 28 failures are classified in `failure-classification.json`:

- 23 native/source/installed/SSH/tmux handoff cases used an injected non-priority
  `h` binding. Wider metrics columns enabled the real table's existing horizontal
  `h` navigation. The fixture binding now explicitly owns priority; production
  navigation, handoff/TTY checks and all deadlines stay intact.
- A genuine feedback race let an empty render overwrite `No contexts`. The
  navigation action now uses the existing persistent notice owner. Empty rows
  also avoid an unnecessary metrics projection worker. A forced later repaint
  verifies that the action feedback persists.
- Unknown-context DOM observation now waits for the exact expected label, rather
  than assuming service state and painting finish simultaneously. The mouse case
  now uses four actual owned-HTTP Pod UIDs; incomplete anonymous rows inserted
  behind the live renderer no longer race its authoritative snapshot. Exact
  labels, click success, focus and up/down selected UIDs remain asserted.
- Compact geometry and horizontal scrolling already passed; its End-key witness
  now asserts the actual final `METRICS` header, while retaining AGE in the schema.
  The disposition-map count includes the new acceptance document.

Separate read-only review found that an uncertain Pod with an extended-resource
key outside application containers could lose that uncertainty during aggregate
zero-defaulting. All init/sidecar/Pod-level/overhead declaration keys now remain
visible, with `N/A` and an uncertain-budget label instead of an invented complete
request total. Mixed normal/complex members and denied/incomplete Node membership
have deterministic regression controls; Node capacity/allocatable remain visible.
Nullable optional container lists and malformed/oversized status lists are also
bounded without an unexpected UI fault.

The corrected focused UI/domain checks passed **164 tests**, followed by
**136 domain/HTTP/Pilot tests** with all three new critical modules at **100%
lines and branches**. The resource/container logs and shell cases additionally
exercise actual horizontal overflow before the unchanged `l`, `x` and `s`
shortcuts, preserving selected UID and both viewports. The initial-sample modal
also expires without any subsequent observation. Complete corrected source and
owned-kind results remain pending until their recorded commands finish.

## Ordinary admitted allocation status

The second frozen campaign at `c39ac6d9ff1689a5a77e4ad51ae45f3cd841e3c0`
was interrupted before editing after version-specific source review identified
that ordinary admission/enactment status had been mistaken for resize evidence.
Its separate report/after archive and cancellation receipt record exit 130,
reaping, a drained group without forced kill, and no remaining process under its
owned source/fixture directories. No result from that interrupted campaign is a
passing qualification claim.

The corrected decision matches unique declared container names, then compares
only explicitly reported bounded quantities numerically. `allocatedResources`
is compute-request telemetry; `resources` provides enacted requests/limits.
Equivalent units match. Missing optional fields, subsets and omitted extended
telemetry do not create false resize flags or replace admitted GPU requests.
Genuine contradictions, malformed/ambiguous identities, invalid values, explicit
resize, and True/Unknown PodResizePending/PodResizeInProgress leave active allocation unconfirmed;
False resize conditions do not trigger uncertainty. Zero, absence and unlimited
limits retain their distinct declaration/display semantics.

Primary references: [Kubernetes v1.36.4 API types](https://github.com/kubernetes/kubernetes/blob/v1.36.4/staging/src/k8s.io/api/core/v1/types.go)
and [the kubelet status producer](https://github.com/kubernetes/kubernetes/blob/v1.36.4/pkg/kubelet/kubelet_pods.go).
These were consulted to separate ordinary admitted/enacted state from resize
evidence and to avoid whole-map equality against optional telemetry.

The real-shaped HTTP positive asserts known numeric budgets and 250%/25% CPU
and 200%/50% memory request/limit percentages with equivalent-unit status fields.
The live Pilot uses ordinary admitted status while refreshing numeric percentages.
A subset/omitted-GPU/unlimited-limit witness preserves declaration values.
Active init/debug containers missing a sample remain partial rather than a full
usage percentage. All new deterministic modules retain 100% focused line and
branch coverage after **165** cases; the expanded container/shell family then
passed **211** cases with the changed container module also at 100% lines/branches.

The owned standard-resource trial now creates two controlled Pods in its own
namespace: an ordinary Pod with explicit 100m/1 CPU and 32Mi/128Mi memory budgets,
and a separate init Pod with an independently established uncertain allocation.
It inspects actual kubelet admission/enactment fields, requires exact known report
and rendered declarations without a Metrics API, and checks actual uncertain
Pod/Node N/A cells. Filtered status/report observations are retained before those
assertions so a real-shape failure cannot disappear during cluster cleanup.
The first owned trial on `c6608c01c5f0275989f5de055709c61ee4a3b980` failed
the exact ordinary-budget uncertainty assertion. The retained ordinary Pod had
matching Pod-level `status.allocatedResources` and `status.resources` even though
`spec.resources` was absent. A separate minimal owned diagnostic captured those
exact resource fields: 100m/1 CPU and 32Mi/128Mi memory at both Pod and container
status. Both disposable clusters were deleted with absence verified; the first
trial's Docker inventory remained unchanged. Evidence is retained in
`artifacts/issue68/kind-qualification-1/`, including the failed terminal receipt,
filtered admitted/report values and the separate Pod-status diagnostic.

The correction reconciles ordinary Pod aggregate telemetry numerically too.
Configured requests/limits and their percentages stay available when only
status telemetry differs; the `METRICS` label says configured budgets and active
allocation unconfirmed. This distinction covers kernel-rounded Pod cgroup
observations without guessing that a resize is active or inventing an epsilon.
Init/sidecar/overhead/Pod-level spec budgets still suppress an unproven effective
Pod total. Node Pod-allocation sums are uncertain when any member's active
allocation is unconfirmed; independent Node usage/allocatable remains useful.
The kubelet's `convertToAPIPodLevelResourcesStatus` and
[CPU cgroup conversion helpers](https://github.com/kubernetes/kubernetes/blob/v1.36.4/pkg/kubelet/cm/helpers_linux.go)
explain why those status fields must remain distinct from configured budgets.
Unit, real HTTP and live-container Pilot witnesses require known configured
numbers for both matching ordinary status and a differing cgroup CPU value.
The expanded corrected focus passed **209 cases** in 34.89 seconds on Linux
CPython 3.12.12, with 100% lines and branches for metrics, quantities,
metrics projection and container rows:

```sh
uv run pytest tests/unit/test_metrics.py tests/unit/test_container_rows.py tests/contract/test_metrics.py tests/ui/test_metrics.py tests/ui/test_shell.py tests/unit/test_metrics_projection.py -q -n 4 --tb=short --cov=kuberich.domain.metrics --cov=kuberich.domain.quantities --cov=kuberich.services.metrics_projection --cov=kuberich.domain.containers --cov-branch --cov-report=json:artifacts/issue68/pod-status-complete-focused-coverage.json
```

## Owned trial and retained full-source results

The corrected owned context/native-resource trial passed in **83.7 seconds** on
clean frozen `a553ab63bb354c76fc3b36a7b280bf1453375f77`:

```sh
uv run python -m scripts.verify_contexts_kind --kind /home/develop/projects/personal/kubetrol/artifacts/qualification-tools-linux-amd64-ewfuxtag/kind --evidence artifacts/issue68/kind-qualification-2/evidence.json
```

The ordinary Pod's real Pod/container allocation fields matched its admitted
100m/1 CPU and 32Mi/128Mi memory budgets. Both report and rendered cells were
numeric with allocation uncertainty false, even without a Metrics API. The
independent init Pod and Node allocation cells were explicitly uncertain.
The same trial exercised all 15 native resource families, UID/watch/inspection
round trips, context changes, container navigation, TLS and log cleanup.
The unique owned cluster was deleted with absence verified; its dedicated
kubeconfig directory and owner/child processes were gone. Docker inventory was
unchanged. Filtered real status, rendered/report assertions and cleanup receipts
are retained under `artifacts/issue68/kind-qualification-2/`.

One complete source campaign then ran against the same clean frozen source:

```sh
uv run python scripts/qualify.py 0.3.0 --output artifacts/issue68/source-qualification-3 --base b1f00706ff3448cded7818633c84ed77e3ca83af --workers 6 --repetitions 1
```

Ruff, formatting, private-access checks, the strict workflow type target union
and startup contracts passed. Offline/UI startup latency targets were missed
and retained as advisory 0.x observations. Full pytest finished with
**7,450 passed, 1 failed and 5 explicit native-only skips** in 1,360.08 seconds.
The failed command is retained as failed; the coordinator stopped before its
remaining gates. Its source was unchanged and every owned process group was
drained/reaped without forced kill. Independent cleanup found no remaining
owned process or live retained PID witness.

The sole failure was the installed-console aggregate-log success-copy fixture.
Its continuously growing three-source JSON payload reached 302 retained records.
The actual ANSI contains the correct **64 KiB OSC52 backend refusal**, followed
by a normal source update, and no clipboard frame. This establishes a fixture
size race rather than a missed copy dispatch. The original failure ANSI/JSON,
terminal restoration and cleanup witnesses remain under
`artifacts/terminal/failure-1793823150790247167.*` and the campaign's after archive.

Numerical checks over that **retained failed-suite measurement**, while its
source was still clean, found **98.709% source lines, 95.733% source branches,
100% of every configured critical module, and 99.29% changed lines** against
`b1f00706ff3448cded7818633c84ed77e3ca83af`, with no exclusions. These are not
current-head qualification or a passing full campaign. The original coordinator,
nonce and source receipts were not rewritten or rebound.

## Deterministic clipboard fixture correction

A fixture-only follow-output gate now holds the three real HTTP readers open
after exactly 80 initial records each. Waiting for the observed 240-record
state establishes a known safely bounded success-copy payload. The gate defaults
open for other fixtures, and the existing stop event still interrupts every
handler. The test requires the actual decoded OSC52 payload, all 240 records,
three container identities, the captured Pod UID, redaction, the unchanged
65,536-byte backend bound, a rendered copy notice, and terminal restoration.

The affected source, freshly installed console/module and clipboard refusal
family passed **54 cases with 1 explicit macOS-only skip** in 26.74 seconds:

```sh
uv run pytest tests/terminal/test_aggregate_logs.py tests/packaging/test_distribution.py::test_installed_aggregate_logs_and_terminal_restore tests/unit/test_clipboard.py tests/ui/test_clipboard.py tests/contract/test_clipboard.py -q -n 4 --no-cov --tb=short --basetemp=/tmp/kuberich68-bounded-aggregate-pytest --junitxml=artifacts/issue68/bounded-aggregate-family.xml
```

All three PTY variants emitted exactly **54,611 bytes / 240 JSON records**,
with three expected container identities, the correct Pod UID, no hidden token,
a rendered success notice, exit 0 and restored terminal/cursor/alternate-screen
state. Ownership cleanup found no remaining process. Evidence is in
`artifacts/issue68/bounded-aggregate-family-evidence.json` and its log/XML.
Ruff, formatting, the strict workflow type target union (238 source files),
private-access checks, plan/generated-reference checks and six documentation
contract cases passed after the fixture correction.
At that checkpoint production runtime remained the tested `a553ab6` source;
the clipboard correction changed only the owned fixture and acceptance/preview
records. No production cap,
deadline or refusal control was weakened, and no full local coordinator or kind
repetition was run solely for this fixture correction. Current-head required
hosted full-suite/runtime/coverage/build gates remain pending integration of the
incoming release-activation base and the next PR push. Real provider and native
platform qualification are not claimed by these Linux results.

## Main-table expiry independent of AGE and pending reads

Independent review found a real gap after that checkpoint: main-table freshness
was only applied during a render. With AGE refresh set to 3,600 seconds, a quiet
resource watch and a pending 300-second metrics read, old numeric usage could
remain displayed beyond its cache lifetime. The container screen's independent
expiry already worked; that did not establish autonomous expiry of the main
Pod, Node or workload tables.

The poller now owns one one-shot expiry task for each usable completed batch.
It computes the earliest still-live sample deadline once, ignoring expired or
no-usage reports, and publishes an O(1) `metrics cache expired` cache flag. The
existing bounded projection/render worker clears usage and percentages once.
It performs no per-row HTTP request, overlapping poll, repeated per-second
table scan or AGE preference change. The cache contract is conservative: newer
members can expire with the batch while their original sample timestamps and
windows remain unchanged. Configured budgets and resource UID/viewport survive.

Batch replacement cancels and awaits the old expiry before publishing fresh
data. Scope/context changes and exit drain it alongside the existing metrics
owner. A batch-identity/current-generation guard rejects late callbacks. The
owned drain shields asynchronous child cleanup and re-raises caller cancellation
after that cleanup, including a repeated cancellation while normal fresh-batch
retirement is held.

The final focused command passed **186 cases in 23.82 seconds**:

```sh
uv run pytest tests/unit/test_metrics.py tests/unit/test_metrics_projection.py tests/contract/test_metrics.py tests/ui/test_metrics.py -q -n 4 --tb=short --cov=kuberich.domain.metrics --cov=kuberich.services.metrics --cov=kuberich.services.metrics_projection --cov-branch --cov-report=json:artifacts/issue68/main-expiry-final-coverage.json --junitxml=artifacts/issue68/main-expiry-final.xml
```

The real HTTP/Pilot witnesses set AGE refresh to 3,600 seconds and request
timeout to 300 seconds. They hold the next API read, advance a controlled clock
and release the owned expiry boundary without input or watch events. Actual
Pod, Node and StatefulSet cells change CPU/memory usage to N/A/stale while exact
configured CPU/memory requests and limits remain numeric. Selection and horizontal
scroll survive; a newer member's original timestamp is retained rather than
being falsely aged. A fresh completed batch restores values, and exit cancels
the next held read and its new expiry. Separate contracts verify namespace/context
changes, obsolete generations, delayed old-timer completion, repeated parent
cancellation and absence of a timer for empty/stale/forbidden batches.

Focused line/branch coverage is **100%/100%** for the deterministic metrics and
projection modules, and **98.204%/92.188%** for the I/O poller. All newly added
expiry/drain lines and branches were exercised. The original full-source
campaigns and their nonces/source receipts remain unchanged; their historical
measurements do not qualify this later production correction. Exact-head hosted
full-suite/runtime/source/changed/critical coverage and build gates remain
pending the incoming activation base and next branch push. No additional full
local phase or kind campaign was run for this correction.
