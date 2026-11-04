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
