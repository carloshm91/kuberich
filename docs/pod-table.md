# Live pod table

The development workspace now displays watched pods in the chosen context and
namespace. `:ctx` chooses a context; `:ns NAME` chooses a namespace and `:ns *`
shows all namespaces. Startup flags also work:

```sh
uv sync --locked --group dev
uv run kubetrol --context YOUR_CONTEXT -n YOUR_NAMESPACE
```

This uses your trusted local kubeconfig and credential helpers. The table performs
reads only. Logs, exec, details and other resource tables remain later checkpoints.
The filter input and Tab completion are B03 #27, which follows this checkpoint.

## Columns and controls

| Column | Meaning |
| --- | --- |
| NAMESPACE / NAME | Literal resource identity labels; the Kubernetes UID identifies the row |
| READY | Ready running application containers plus started, ready running restartable init sidecars, divided by declared application containers plus those sidecars |
| STATUS | Pod phase/reason refined by initialization, waiting and termination state; includes crash/image errors, initialization progress, scheduling gates and deletion |
| RESTARTS | Nonnegative integer counts; during initialization includes regular init containers; afterwards counts applications and restartable sidecars |
| AGE | Elapsed seconds/minutes/hours/days/years from creation; unknown is `—`, clock skew clamps display age to zero |

Ephemeral debug containers do not contribute to workload readiness or restarts.
Ordinary completed init containers no longer contribute to the active restart
count. Active sidecar failures remain visible after initialization; completed Jobs
retain their application outcome while sidecars stop. A pod-level reason such as
Evicted is retained. Terminal Succeeded/Failed phases are not changed to
Terminating merely because deletion started; NodeLost during deletion is Unknown.

Use up/down and PageUp/PageDown to navigate rows. Left/right scroll horizontally;
Home/End reach the left/right edge, Ctrl+Home/Ctrl+End reach the first/last row.
`s` cycles the sort column; Shift+S reverses its direction. Clicking a column
header selects it; clicking again reverses it. The border shows the active sort.
Letters typed into either input remain text.

Restart counts sort as integers, readiness as a fraction and ages chronologically,
never by their formatted labels. Unknown ages remain last in either direction.
Equal values have a deterministic namespace/name/UID order. Ages update while
the watch is quiet, without fetching the collection again.

## Updates and scope

Snapshots are projected off the terminal event loop. Unchanged immutable records
reuse their pod summaries; there is one bounded current cache and one owned
decoding job. Cancellation drains that job, including repeated cancellation,
before releasing ownership. A changed scope clears visible rows immediately and
late projections/patches from an older revision are rejected.

The table changes individual cells and adds/removes UID keyed rows. It does not
clear/rebuild the table for each event. At most 128 row patches run before yielding
to input processing. Sorting preserves the selected UID and the top visible row
as a scroll anchor, plus horizontal position. A deleted selection chooses the
row at its previous index, or the last row if that index disappeared. A recreated
name with a new UID is a new row and does not displace a surviving selection.

Loading, a successful empty list and a failed list have different copy. Stale
snapshots retain rows with a visible stale/error status; denied reads are not
presented as empty success. The header yields its row in terminals shorter than
16 lines, leaving data space at the qualified minimum 40×12. Longer resource
labels/reasons are displayed literally with controls escaped and cell width
bounded to 256 terminal cells.

Collection/frame/subscription bounds remain in [resource views](resource-views.md)
and [watches](resource-watches.md). Batched updates are not a maximum-scale or RSS
qualification; Q01 still owns that work. CPU/memory metrics and Kubernetes
quantity ordering remain the metrics/generic-column tickets, rather than invented
zero values in this pod table.

## Verification

```sh
uv run pytest tests/unit/test_pods.py tests/contract/test_pod_projection.py tests/ui/test_pods.py
uv run pytest tests/terminal/test_pods.py tests/packaging/test_distribution.py
```

The domain module is independently required to reach 100% line/branch coverage.
Pilot checks literal Unicode/controls, typed sorting, retained selection/scroll,
deletion/recreation, empty/scope changes and cancelled batches. Owned HTTP watches
drive actual cell changes. A real CLI PTY checks rows, updates, sorting, scope,
resize and terminal restoration. Built wheel/sdist entry points also display rows
outside the checkout. The disposable-kind qualification compares readiness,
status and integer restarts against the API server's Table projection and runs
the actual widget through sorting and namespace changes. Every cluster fixture
belongs to a newly created/deleted cluster, never an ambient context.

Framework and API references: [Textual DataTable](https://textual.textualize.io/widgets/data_table/),
[pod lifecycle](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/),
[sidecar semantics](https://kubernetes.io/docs/concepts/workloads/pods/sidecar-containers/).
