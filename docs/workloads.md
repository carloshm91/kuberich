# Operate a workload

Select a workload in its ordinary resource table, check the context and namespace,
and use a command for the intended action. Changes require write mode and the
corresponding Kubernetes permissions. Progress viewing also works read-only.

## Follow the controller chain

In 0.4.0 and later, select a workload and use `:xray` to inspect its owners,
children, selector matches and declared configuration/storage references.
Template declarations remain visible at zero replicas. Enter/arrows expand or
collapse; `o` or `:open` opens a current readable object in its resource view.
Graph rows are not targets for workload changes.

`:usedby` on a supported configuration, identity or storage target includes
Pod/template declarations without claiming that a process consumed a value.
Read [relationship evidence and incomplete scans](resource-relationships.md)
before treating an empty result as absence. Installed 0.3.0 predates these views.

## Scale replicas

Use `:scale` or `:scale 3` on a Deployment, ReplicaSet, or StatefulSet. Review the
replica count, then choose Confirm separately. Zero replicas stops replicas;
counts range from 0 to 2,147,483,647. StatefulSet scale-down review reports PVC
deletion requested by its actual retention policy.

Scale needs workload GET and `/scale` GET/PATCH. It also checks namespace HPAs;
an HPA targeting the workload blocks manual scale. A denied or invalid HPA check
blocks review. The HPA check and scale request are separate, so an HPA can appear
in between. An owning controller can reconcile a manually scaled ReplicaSet.

## Restart or restore a revision

`:restart` reviews a pod-template timestamp change on a Deployment, StatefulSet,
or DaemonSet. `:rollback` or `:rollback 1` restores one explicit available controller
revision's template. Replica counts and update strategy stay current.

Rollback reads revisions belonging to the selected controller UID and checks the
chosen revision again before writing. Missing or ambiguous history is refused.
Paused Deployments and `OnDelete` StatefulSets/DaemonSets refuse automatic
restart/rollback. Rolling partitions remain in effect. Restoring a StatefulSet
can still require deliberate removal of a failed pod; rollback does not force it.

## Watch rollout progress

Use `:rollout` to read generation, controller counters, revisions, partitions,
paused state, and reported Deployment deadline failure. A successful write does
not mean rollout completed. Escape stops this monitor without undoing a change.
The monitor times out after five minutes; reopen it for current progress.

## Delete one or several resources

Use `:delete` for the selected resource or `:deletebatch` for marked rows. Without
marks, batch review offers the displayed filtered rows and selects none initially.
Space toggles an item. Batches contain at most 100 exact targets and send one
DELETE per target, never a collection-wide DELETE.

Choose Review, select propagation and optional grace seconds, type `DELETE 1` or
`DELETE COUNT` matching the review, then Confirm separately. Cancel has default
focus. The review identifies context, resource, namespace, UID, and version.

| Propagation | Consequence |
| --- | --- |
| Foreground | Dependent cleanup precedes completion of owner deletion |
| Background | The owner may disappear before dependents finish |
| Orphan | Dependents remain |

Blank grace uses the server default. Zero grace does not bypass finalizers or
prove remote processes and external storage are gone. Controllers can recreate
deleted pods. Already-terminating resources are refused; finalizers are shown
but never removed automatically. Deletion checks UID and resourceVersion on the
server, so replacement or concurrent changes require a fresh review.

**Accepted; deletion pending** reports API acceptance, not dependent cleanup.
A follow-up read showing absence confirms only removal of that selected object.
Batches run sequentially with independent results; earlier success is not rolled
back when another item fails. Use `:writes` to read every outcome.

## Clean up finished pods

In `:pods`, narrow the view with a filter, then use `:cleanup`. Completed and
failed pods are listed; running, pending, and already-deleting pods are excluded.
Every listed pod starts selected; Space excludes it. Review and confirm with
`DELETE COUNT`. At most 100 pods are handled per cleanup.

If an object was deleted or replaced before confirmation, nothing is deleted;
review again. A version conflict during execution affects that item while other
items can succeed. Read-only mode blocks cleanup.

## Run or suspend Jobs

Use `:trigger` on a CronJob to review creating one manual Job from its current
template. The review and result show the exact Job name, including an uncertain
creation outcome. The manual Job is independent of the CronJob's schedule and
concurrency policy and can run while the CronJob is suspended. Template TTL and
suspension settings remain part of the new Job.

`:suspend` and `:resume` change `spec.suspend` on a Job or CronJob. Suspending a
CronJob stops future scheduled runs, not existing Jobs. Resuming can start missed
runs. Suspending a Job terminates active pods; resuming can restart execution
and reset its start time. Check these effects before Confirm.

## Recover from a conflict or uncertain write

Every action binds its review to the selected target and change. Input edits
invalidate it; Confirm can be used once. No automatic retry follows a rejected,
interrupted, or lost write response. Inspect current state before another review.
`:writes` keeps recent results for this application session, not a persistent
audit log. See [edit and change resources](editing.md) for shared result meanings.

## Browse Helm releases in development source

The Helm workspace is new development work for 0.5. It is not included in the
published 0.4.0 packages. Install an optional supported Helm CLI yourself;
KubeRich does not download Helm or invoke it during ordinary startup.
The initial tested versions are **3.22.1** and **4.3.1**. Other versions produce
a feature-specific compatibility message.

Use `:helm` for the selected namespace, `:helm demo-apps` for a fictional
namespace, or `:helm *` for all namespaces. The normal namespace picker, filter,
sort and navigation history work in this view. Press F4 to refresh explicitly;
Helm releases do not use a live Kubernetes resource watch. Enter opens the
selected release, retaining its namespace when names repeat across namespaces.

Helm uses Secret storage by default. `HELM_DRIVER=secret` or `secrets` selects
that backend; `configmap` or `configmaps` selects ConfigMap storage. SQL, memory
and unknown drivers are refused without falling back to another backend.
Only the selected storage backend is listed. Reading Helm storage grants access
to chart contents, including sensitive values; Kubernetes permissions still apply.

The list retains at most 500 releases. **INCOMPLETE** means that more releases
exist: narrow the namespace instead of treating the retained rows as exhaustive.
This limit bounds KubeRich's retained rows, not Helm's internal API reads or
memory. Helm's normal status filters do not include arbitrary unknown stored
states. A failed refresh keeps prior rows visibly stale.

### Inspect one release

Use sections 1–6 for status, notes, supplied values, computed values, manifest
and revision history. Supplied values contain explicit overrides; computed
values also include chart defaults. History retains the newest 200 revisions
and identifies omitted older revisions.

Status and history show metadata. Notes and freeform descriptions start hidden;
value scalars and sensitive manifest fields are redacted. Malformed documents
produce an error instead of falling back to raw text. Press `r` in a document
section, review the release/revision and confirm **Reveal once** to read current
contents. Press `r` again to hide them. Changing sections, opening another
screen or leaving the inspector clears revealed text. Revealed contents have
no export or clipboard action in this workspace.

The inspector reads the selected namespace and exact release revision. Missing
release storage, denied metadata access, a newer revision, or a replaced storage
object requires a fresh selection. Read access to ordinary resources alone does
not grant access to a Helm release.
Identity checks require a complete storage-history scan, bounded to 2,000
revision records, ten pages and 4 MiB of metadata. Exceeding these limits
disables inspection-sensitive actions instead of trusting an incomplete scan.

### Roll back a Helm release

In the history section, select an explicit earlier revision and choose the
local rollback action. The ordinary `:rollback` command still operates on
workloads, and `:history` still opens metric history.

Review the context, namespace, release, current and target revision, timeout,
wait behavior and hooks. **Prepare review**, then confirm separately. Read-only
mode blocks rollback. Editing options invalidates the prepared confirmation;
confirmations are single-use and are invalidated by refresh or scope changes.

Rollback starts with hooks disabled, resource/Job waiting enabled and a
300-second timeout. Timeouts range from 1 to 600 seconds. Enable hooks explicitly
only after reviewing their effect: chart hooks can run arbitrary cluster Jobs.
Helm 3 uses its legacy wait behavior; Helm 4 explicitly uses legacy waiting
when enabled and hook-only waiting otherwise. The timeout applies to Helm's
individual operations; a separate finite process deadline bounds the command.
Rollback does not force replacement, automatically clean up new objects or
prune old release history.

The current release must be deployed or failed, and the chosen prior revision
must be deployed or superseded. Pending, uninstalling, uninstalled or unknown
states refuse rollback. KubeRich rereads actual storage identity immediately
before execution. Helm's name/revision command has no atomic identity condition:
another operator can still change the release after that check.

Successful command exit is followed by a fresh observation of the expected new
deployed revision. Failed hooks, timeouts, interruptions or lost connections can
leave a partially applied or pending release. **Unknown** means that the remote
outcome is unverified; refresh status/history and inspect the cluster before
another review. No automatic retry or compensating rollback runs. Closing the
screen stops owned work without undoing changes already accepted by Kubernetes.

Installing, upgrading, uninstalling and repository/OCI management remain planned.

## Local manifests and Kustomize in development source

Development source for 0.5 adds `:manifests`. Open it after connecting to the
intended context, or start with `kuberich --command manifests` for offline local
inspection. Browsing does not execute a helper or connect to a cluster.
After offline inspection, use Back, select the intended connection with `:ctx`,
then reopen `:manifests` to review cluster changes.

1. Choose a local root containing your manifests and any shared bases. Enter a
   directory to navigate; parent navigation stops at that root. Symlinks and
   special files are unavailable. Changing the root discards old source reviews.
2. Inspect a resource YAML/JSON file with Enter. Sensitive values start redacted.
   Multi-document files and ordinary Kubernetes `List` wrappers are supported.
   Inspecting a Kustomization shows structure only and never runs its build.
   Other non-resource YAML can be edited locally; this browser cannot inspect it.
3. Enter a file to capture it; open a directory before choosing Preview directory
   or Render Kustomize. Both buttons use the currently opened directory.
   Directory previews include immediate manifest files in sorted order. Local
   rendering requires `kubectl`; missing or failed rendering blocks it.
4. Configure [your editor](editing.md#edit-a-manifest), acknowledge disclosure and
   choose Open editor. Review the returned diff and choose Save local; this does not apply.
   Changed source requires a new capture and validation. Hard-linked files
   cannot be replaced through this workflow.
5. Review every resolved resource, context and destination namespace. Explicit
   manifest namespaces remain intact; missing namespaces use the reviewed
   fallback. All-namespaces mode requires a fallback when a document lacks one.
6. Validate against the server, inspect the redacted diff and confirm Apply or
   Delete. A failed dry-run blocks the batch. Delete reviews cluster resources
   and leaves local files in place. Back is focused when the review opens.

Read-only mode permits browsing, inspection and local rendering; editing, saving
and cluster mutation are blocked. Fixed resource names are required; generated
names, automatic namespace/CRD installation, force and pruning are unsupported.
Create prerequisite Namespaces or CRDs separately before validating dependants.

Kustomize supports bounded local bases/components, patches, generators, images
and namespace/name transforms. Remote/Git/URL dependencies, executable plugins,
Helm inflation, absolute references and root escapes are refused before build.
Choose a common root for `overlays/dev` and `base`; the renderer retains its
normal root-only loading rules and never retries with unrestricted loading.
Sources are limited to 256 files/8 MiB and 100 resources; editable files and
individual resource requests are limited to 1 MiB. Split larger inputs.

Existing objects use declarative merge previews followed by exact UID/version
conditional writes. New names use atomic creation; concurrent creation becomes
a conflict. Execution is sequential and stops at the first failure: earlier
changes remain, and later items are explicitly unsent. There is no batch
transaction, automatic rollback or blind replay. A lost response after write
admission is uncertain and requires inspection before another reviewed attempt.
Accepted deletion can remain pending because of finalizers. Errors show safe
categories, codes and limited known field paths; freeform server details and
arbitrary mapping keys are withheld because they can contain submitted values.
