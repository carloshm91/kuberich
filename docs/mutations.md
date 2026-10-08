# Guarded resource changes

M01 #43 supplies shared mutation services and one usable action: select a
patchable resource, run `:annotate`, enter a key/value and choose Review. The
confirmation shows captured context, namespace or cluster scope, resource name,
UID, opaque resourceVersion and the intended annotation value. Enter after Review
focuses Cancel. Only deliberate Confirm sends the patch. Existing annotations
and resource data are preserved; Secret data is not exposed by this action.

`--readonly` blocks this action through the same policy used by initial commands,
interactive commands and effectful services. `:writes` remains available and
shows at most 32 operation records, including in-progress and uncertain outcomes.
History contains target identity, changed paths and fixed result messages;
annotation values, manifests, credentials and raw server errors are omitted.

Preparation uses a fresh individual GET. A one-use confirmation binds the exact
immutable request, captured client and API path. Execution revalidates identity
and version, then sends JSON Patch with UID and resourceVersion tests first.
Server-side tests close the race between reading and applying a change. A new
object with the same name or a concurrent update requires a new review.

| Result | Meaning and next action |
| --- | --- |
| Succeeded | A bounded valid API response confirms the captured object. |
| Blocked / stale | Policy, confirmation or target changed; no write started. |
| Permission denied / authentication failed | Check API permissions or reconnect; no write replay. |
| Conflict | Read the current object and review a new change. |
| Rejected (422) | A precondition or validation failed; inspect the current object. The status alone does not distinguish those causes. |
| Timed out / cancelled before write | Revalidation or credential preparation stopped before sending. |
| Write outcome uncertain | The request may have applied. Inspect the current object before another change. |

PATCH never follows redirects or refreshes-and-replays a 401. Failed, interrupted,
oversized or invalid responses after request start cannot prove nothing changed.
There is no automatic retry, including on throttling or server failure.

Leaving the form retains an already started bounded operation; use `:writes` to
see its outcome. Changing the captured client or exiting cancels and drains owned
requests/decoding before SDK cleanup, including a Review read still in progress.
Concurrent cleanup requests cancel that reader once and await its owned decoding.
This preserves an honest uncertain outcome for a write when
necessary. Eight concurrent operations and 32 recent records bound ownership.
API writes are not a sandbox or a replacement for server RBAC/admission.

Native manifest editing, dry-run, scale/rollout and delete/Job actions remain
#44/#45/#46. No complete operations-parity claim follows from this foundation.
Annotation keys use Kubernetes qualified names; the combined annotations are
bounded to 256 KiB and this form limits a value to 65,536 characters.

Sources: [Kubernetes conditional updates](https://kubernetes.io/docs/reference/using-api/api-concepts/),
[annotation syntax](https://kubernetes.io/docs/concepts/overview/working-with-objects/annotations/).
