# Delete resources and operate Jobs

Select a resource in a connected table, then use a command below. These commands
require write mode; `--readonly` blocks both the UI and service paths. Local
contexts are configuration entries and cannot be deleted through Kubernetes.

| Command | Captured effect |
| --- | --- |
| `:delete` | Delete the selected resource UID/version. |
| `:deletebatch` | Choose exact targets from the currently displayed, filtered rows. |
| `:trigger` | Create one manual Job from the selected batch/v1 CronJob template. |
| `:suspend` | Set the selected batch/v1 Job or CronJob's `spec.suspend` to true. |
| `:resume` | Set its `spec.suspend` to false. |
| `:writes` | Read retained outcomes, including every item in a batch. |

## Review and confirmation

The form shows context, API/resource, namespace or cluster scope and UID. Review
reads current versions and captures immutable request bytes. Cancel receives
focus after review; Enter there cancels. A separate Confirm submits the reviewed
operation once. Changing selection or options invalidates review.

For deletion, choose a propagation policy and optional grace seconds. Blank uses
the server default. Type `DELETE 1` for a single resource, or `DELETE <count>`
matching the reviewed batch count, before Confirm. Batch mode selects nothing
automatically: Space toggles individual rows. Filter a large table first; a batch
is limited to 100 exact targets, which can include explicitly reviewed namespaces
from an all-namespaces view. It never sends collection-wide DELETE.

| Propagation | Consequence |
| --- | --- |
| Foreground (default) | Dependents are cleaned before the owner finishes deletion. |
| Background | The owner may disappear while dependent cleanup continues. |
| Orphan | Dependents remain; their owner references are handled by Kubernetes. |

Zero grace requests immediate termination where supported. It does not bypass
finalizers, guarantee an underlying process has stopped, or establish cleanup of
external storage. Deleting pods may cause controllers to recreate them; deleting
namespaces, workloads or storage can affect other resources. Review the scope.
Already terminating resources are refused; inspect their finalizers instead.

Each DELETE includes server-enforced UID and resourceVersion preconditions.
Same-name replacement or concurrent modification is refused. Existing finalizers
are disclosed in review and observed afterward; this tool never removes them.

## Results and batch behavior

**Accepted; deletion pending** means the API accepted the request while completion
remains pending or could not be observed. A successful follow-up read showing
absence establishes removal of the captured object, not dependent cleanup. If a
replacement is observed, it is reported and left untouched. Permission denial,
conflicts, stale captures and uncertain writes remain distinct.

Batches execute sequentially with one request per target and independent results.
A denied or stale item does not conceal successful earlier items. There is no
transactional rollback. Leaving the form keeps the confirmed operation owned by
the write manager; `:writes` retains every target's result. Context replacement
or app exit drains the operation; an interrupted request can be uncertain while
remaining unsent items are marked cancelled. Up to 32 operation records are
retained in the application session; they are not a persistent audit log.

No write follows redirects, refreshes/replays a 401, or retries transport/server
failures. In particular, DELETE connection replay is suppressed through the HTTP
client's public middleware. If the response is lost, inspect actual cluster state
before making a new deliberate change.

## Manual Jobs and suspension

Run now uses a fresh CronJob template snapshot and reports the exact Job name,
namespace and returned UID. It copies template labels, annotations and Job spec;
it does not copy managed metadata or owner references. The manual Job is
independent and remains discoverable through `:job`. The name carries a one-use
request identity. Repeating the same captured request uses that same name and
gets a conflict rather than creating a second Job. No automatic replay occurs;
opening another form for a new explicit run creates a new request identity.

The preview and retained result include the name even when creation is uncertain.
Manual runs can occur while a CronJob is suspended and do not enforce its schedule
or concurrency policy. Template settings such as Job suspension/TTL remain part
of the copied spec. Source revalidation and creation are separate API requests:
there is no atomic cross-resource transaction if the CronJob changes afterward.

Suspension uses a guarded JSON Patch of one boolean. Suspending a CronJob stops
future scheduled runs, not its existing Jobs. Resuming can cause missed runs to
start immediately. Suspending a Job terminates its active pods; resuming restarts
execution and can reset its start time. Review these consequences before Confirm.
The API's RBAC and admission policies remain authoritative.

## Verification

M04 #46 has pure decision tests, actual HTTP/TLS fault contracts, Textual Pilot,
native source/fresh-wheel terminals and an owned-kind verifier:

```sh
uv run pytest tests/unit/test_operations.py tests/contract/test_operations.py tests/ui/test_operations.py tests/terminal/test_operations.py
uv run python -m scripts.verify_operations_kind --kind /absolute/path/to/verified/kind --evidence artifacts/cluster/operations.json
```

The verifier creates its own explicit cluster and removes it afterward. It never
uses the developer's active context. See [acceptance evidence](acceptance/resource-operations.md)
for measured qualification and remaining platform/cloud limits.

Sources: [Kubernetes DeleteOptions](https://kubernetes.io/docs/reference/kubernetes-api/definitions/delete-options-v1-meta/),
[finalizers](https://kubernetes.io/docs/concepts/overview/working-with-objects/finalizers/),
[CronJob suspension](https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/#schedule-suspension),
[Job suspension](https://kubernetes.io/docs/concepts/workloads/controllers/job/#suspending-a-job).
