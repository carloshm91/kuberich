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
invalidate it; Confirm can be used once. A drain can retry an explicitly refused
429 eviction within its deadline. Accepted, interrupted or uncertain writes are
not replayed. Conflicts require a fresh review. Inspect current state before retrying.
`:writes` keeps recent results for this application session, not a persistent
audit log. See [edit and change resources](editing.md) for shared result meanings.

## Maintain a Node in development source

Development source for 0.5 adds `:cordon`, `:drain` and `:uncordon` on one selected
Node. Published 0.4.0 predates these commands. Check the context and Node identity,
prepare the review and choose Confirm separately. Read-only mode blocks them.
Node diagnostics settings are not required for these API operations.

Cordon prevents ordinary new scheduling. Uncordon makes scheduling available;
it always needs a new review. Both use the selected Node UID and version, so a
changed or replaced Node requires another review. An already matching state
needs no write. Cordon does not move existing Pods or prevent manually bound Pods.

Drain first reviews Pods across **all namespaces** on that Node, regardless of
your workspace namespace or filter. Review controller identity, phase/readiness,
matching disruption budgets and declared storage. Incomplete or denied Pod,
controller or PDB safety reads block confirmation. Unavailable PVC/PV metadata
is shown as unknown storage portability. The operation needs Node GET/PATCH,
cluster-wide Pod LIST, Pod/controller GET, relevant namespace PDB LIST and
`pods/eviction` CREATE.

| Separate choice | Effect |
| --- | --- |
| Force | Permit eviction of checked unmanaged/orphaned Pods; recreation is not guaranteed |
| Delete emptyDir data | Accept loss of checked emptyDir data, including memory-backed volumes |
| Leave DaemonSet Pods running | Acknowledge that verified DaemonSet Pods remain |

Choices start unchecked. A Pod with both unmanaged and emptyDir risks needs both
consents. Force never bypasses disruption budgets. Mirror/static Pods remain;
the host need not become empty. Other storage declarations can have unknown
portability; drain does not migrate storage or promise replacement capacity.

Set a finite timeout of 1–3,600 seconds; the default is 300. Kubernetes decides
whether each policy/v1 eviction is allowed. A refused 429 can wait and retry,
while other checked Pods progress. If a Pod version changes, review again.
Acceptance remains **absence pending** until the checked Pod UID is absent;
normal grace periods and finalizers remain in effect. No direct Pod DELETE,
finalizer removal, PDB change or zero-grace fallback is available here.

**Stop drain**, Escape or leaving the context stops new writes and waits
for work to finish. Completed evictions remain. Stopping never uncordons the
Node. Final status reports freshly observed cordoned/schedulable, absent,
replaced or unknown state with an observation time. A lost response can leave
the write uncertain. External uncordon stops further evictions; new Pods on the
Node need a fresh review. Node checks and Pod evictions are separate API calls,
so another actor can change scheduling between them.

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

### Choose a chart and version

Use `:helmcharts` in development source to open the chart catalog. Select a
concrete namespace before installing. **Add repository** accepts a classic
HTTPS chart repository or an `oci://registry.example/charts/demo` chart path.
Review its URL, optional CA certificate, authentication and approved origins,
then confirm. Search filters cached chart/version rows; opening the catalog or
**Reload cache** does not refresh a remote index or probe Helm.

OCI search covers explicitly registered chart paths, including SemVer build
tags. It does not search every registry or Artifact Hub. Denied tag enumeration
stays an error; a separately registered `@sha256:...` reference selects that
exact manifest. **Update repository** fetches the selected entry again;
**Remove repository** removes its local entry, cached versions and private
credentials, leaving the remote repository unchanged.

Repository HTTPS trust is separate from Kubernetes authentication. Basic or
bearer credentials belong only to this application. Additional token origins
approve authentication realms; additional download origins approve package or
blob hosts. These are separate lists of at most eight exact origins each, with
no wildcards or signed query URLs. Repository credentials never accompany a
cross-origin download. Plain HTTP requires an explicit choice of a loopback
development endpoint; TLS failures never trigger an insecure fallback. See
[Helm configuration](configuration.md#configure-optional-helm-tools-and-catalogs).

Select one version and enter the new release name, then choose **Select version**.
KubeRich freezes the checked chart bytes and checksums for that review. A changed
catalog requires another selection; applying never silently fetches a newer tag.
Read-only mode permits cached search and release inspection, but blocks catalog
changes, chart downloads, values editing and release-change preparation.

Supported packages are v2 application charts with already bundled dependencies.
Limits are 16 MiB compressed, 64 MiB expanded across subcharts, 2,000 files, eight
nested chart levels and 1 MiB of values. Each index or OCI metadata set has an 8 MiB limit,
with at most 10,000 versions and 20 pages. Missing dependencies, legacy
`requirements.yaml`/`requirements.lock`, unsafe archives and external schema
references are refused. Supported dependency constraints are a subset of Helm
syntax: write `>=1.0.0`, not `>= 1.0.0`; repeated dependency names with different
aliases are unsupported. Schemas allow local fragments and the supported draft-07,
2019-09 and 2020-12 dialects only. OCI digest checks do not verify chart signatures.

### Install or upgrade after a separate review

For upgrade, open a release with Enter in `:helm`, choose **Upgrade**, then select
the replacement chart version. Choose chart defaults or fresh current supplied
values explicitly; computed values are never silently reused. Upgrades reset
values and apply the complete selected override file.

**Edit values** requires the separate one-use permission to disclose full values,
including credentials, to your trusted local editor. The editor receives a private
file and has your local privileges. Returning malformed values or an editor error
blocks use of that edit. Editing, changing values source or changing options
invalidates the previous review. Previews keep sensitive fields hidden.

Choose **Prepare review** to run native Helm dry-run and compare rendered objects
with current live objects, including removals from the previous manifest. This
desired-state diff is not Helm's final three-way or server-side-apply patch.
For supported absent named resources, separate Kubernetes CREATE requests use
`dryRun=All`; their individual admission results do not reserve whole-release
quota. Update, server-side-apply and deletion admission are not simulated.
Unreadable destinations, live collisions, incomplete identity checks or missing
served CRD prerequisites block confirmation. The live comparison allows at most
256 unique ordinary destinations and 8 MiB of bodies across old and new objects.

Review context, namespace, version, values source, hooks, timeout and effects;
then choose **Confirm install** or **Confirm upgrade** separately. Hooks start
disabled, waiting starts enabled, and timeout is 300 seconds (1–600 allowed).
Helm 4 installs use explicit client-side apply; upgrades preserve the release's
observed apply method. KubeRich skips chart CRD files and never downloads missing
dependencies, adopts existing objects or forces conflicts.

Each confirmation works once. Namespace, release, catalog, input or live-identity
changes require a new review. Helm renders again and writes several objects, so
another actor or admission can still intervene after the final checks. A timeout,
Stop or lost response can leave partial effects. **Unknown** requires refreshing
status and inspecting the cluster before another review. KubeRich never replays
an uncertain write or automatically rolls back or cleans up a failed operation.

### Uninstall with explicit history and retention choices

Open the release and choose **Uninstall**. **Keep release history** starts enabled;
disable it deliberately to purge history. Choose background, foreground or orphan
cascade, prepare the review and choose **Confirm uninstall** separately. Review
ordinary live objects, cluster scope, hooks, kept resources, PVCs and finalizers.
Hooks can execute cluster code when explicitly enabled. Kept resources, hook
effects, CRDs, PVC data and finalizers can outlive release removal; KubeRich does
not remove finalizers. Stored release JSON cannot provide a complete bundled
subchart CRD inventory. Helm 3 deletion remains name-based; Helm 4 ownership
checks can skip unverifiable resources. A successful history removal does not
prove that every resource or dependent has disappeared. Purged names are never
automatically reused; a later install requires a fresh review.

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

## Create resources in development source

Use `:create` or **Create** in the local manifest browser. Published
0.4.0 predates this workflow. Choose a built-in template, user template, file or
explicit clipboard capture. Source inspection stays offline; importing never
connects to a context or creates a resource.

The six built-ins are Deployment, Service, ConfigMap, Opaque Secret, Job and
Namespace. Supply an explicit name; workload images have no implicit default.
Deployment replicas default to one and accept zero. Service uses ClusterIP/TCP,
an explicit selector and ports from 1 to 65,535. Templates are starting points,
not policy-compliance or workload-readiness guarantees. Edit advanced fields
through the explicitly disclosed trusted editor. A returned edit replaces only
the in-memory draft; it does not save over the imported file.

Choose **Read clipboard** only when you intend to import its current text.
Native reads need the selected macOS, Wayland or X11 helper/session. SSH, tmux,
OSC52 or unavailable native reads offer an explicit focused **Paste** capture.
It accepts a public terminal paste event without echoing the payload. Clipboard
and paste retention is limited to 1 MiB UTF-8; invalid, truncated, excessive or
unsafe-control input is refused. KubeRich never queries terminal clipboard
contents or rereads a captured clipboard at Confirm.

After capture, choose **Review Create** for an existing connection. When started
offline, check the displayed selected context and choose **Connect & Review**;
this explicit transition retains the same draft through connection setup.
Import/render never connects automatically. Back closes and discards the local
draft, so use the explicit action to continue an offline capture.
Review the exact GVK, endpoint, name and every namespace or cluster-scoped effect.
All-namespaces view supplies no implicit destination. **Validate** resolves
captured discovery and requests an exact named POST with strict server validation
and server-side dry-run. Local syntax and typed parameters are separate from
that server's acceptance; there is no complete offline Kubernetes schema check.
Served CRD schemas, CEL, defaults and admission apply as supported by that server.
Preserved-unknown regions and permissive/aggregated APIs do not establish complete
field validation.

Inspect submitted/server changes, then choose **Confirm Create** separately.
Creation refuses an existing name; use the existing Apply/Edit workflow for an
update. It never adds a last-applied annotation, overwrites, adopts or retries a
possibly committed request. Dry-run reserves no name and guarantees no later
admission/default equality. The actual result retains verified persistent UID
and version metadata; interrupted completion can retain known created metadata
while the batch remains uncertain. Inspect before a fresh review.

Read-only mode allows local capture/inspection and blocks editor, validation and
creation at the service/transport boundaries. Every item must validate before
confirmation. Execution is sequential; completed resources remain if a later
item conflicts or fails, and later items are unsent. Namespace/CRD prerequisites
require separate batches. Namespaced POST binds a namespace name, without an
atomic namespace-UID precondition; replacement between requests remains possible.

### Add a user template

Place ordinary `.yaml`, `.yml` or `.json` files in `templates/` beside the selected
[preference file](configuration.md#create-and-check-preferences), including an
explicit `--config` selection. A missing directory is empty; browsing never
creates it. Built-ins and users have separate catalog identities. Duplicate user
ID/revision pairs are disabled. Symlinks, special files, changed captures and
ambiguous identities are refused. The catalog accepts at most 256 files, 1 MiB
per file and 8 MiB combined.

```yaml
schema_version: 1
kind: ResourceTemplate
id: team-config
revision: 1
title: Team ConfigMap
parameters:
  name:
    type: string
    required: true
    paths: ["/0/metadata/name"]
objects:
  - apiVersion: v1
    kind: ConfigMap
    metadata: {name: ""}
    data: {}
```

Parameters use `string`, `integer`, `boolean` or `string_map`, a required flag,
literal paths and optional default, finite enum and sensitive flag. Required
means present, so permitted false, zero and empty values keep their type.
RFC 6901 paths begin with an existing object index and replace a complete
existing value of that type. Paths cannot overlap, generate keys or alter
apiVersion/kind, status or server-owned metadata. There is no interpolation,
expression engine, include, hook, environment lookup or code execution.

Any parameter declared sensitive or supplying data/stringData makes the whole
draft's ordinary content preview opaque, including keys and server/editor copies.
Sensitivity remains after editing or reordering objects. Name/namespace routing
values must remain visible, so a sensitive parameter cannot supply them. A fresh
trusted-editor disclosure permits deliberate inspection; it does not enable
ordinary export or history disclosure. Private-template edits preserve the captured
GVK, name and namespace of every object; object order may change. Use the template's
public parameter controls and capture a fresh draft to change those identities.
Changing source, parameters, destination
or connection requires fresh validation and confirmation.
