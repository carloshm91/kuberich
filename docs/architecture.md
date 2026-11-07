# Architecture

KubeRich is a local Python/Textual terminal client for Kubernetes. This overview
shows the implemented dependency and ownership boundaries. Use the
[decision records](adr/README.md) for individual choices and the
[quality policy](quality.md) for their verification requirements.

## Product boundary

The application talks to selected Kubernetes APIs and explicitly configured local
programs. It has no hosted backend or Textual Web interface. It does not provision
cloud clusters or replace provider login tools. K9s inspires familiar workflows;
KubeRich is an independent implementation.

The UI, pure decisions, transport adapters, and development/release tooling have
separate responsibilities. Installation does not bundle the contributor toolchain
or grant additional Kubernetes permissions.

## Chosen stack

| Responsibility | Implementation |
| --- | --- |
| Runtime | CPython 3.12–3.14 for the current package |
| Terminal UI | Pinned Textual, Rich, application-owned TCSS |
| Kubernetes transport | kubernetes-asyncio with explicit session configuration |
| Local state | Versioned YAML, validated models, platformdirs paths |
| Embedded terminal | Owned POSIX PTY and pinned, unmodified Pyte |
| Packaging | uv development resolution and Hatchling wheel/sdist backend |
| Verification | pytest, fake APIs, Pilot, real PTYs, disposable kind, installed artifacts |

See [the stack decision](adr/0001-python-terminal-stack.md) and
[packaging](adr/0031-standard-python-packaging.md). Native archives and Homebrew
have additional channel-specific build and installation contracts.

## Layers and main modules

### Domain

[Resources](../src/kuberich/domain/resources.py),
[watches](../src/kuberich/domain/watches.py),
[views](../src/kuberich/domain/views.py), and
[targets](../src/kuberich/domain/targets.py) define application records, identity,
recovery, and generation rules. Other domain modules define commands, resource
changes, logging, navigation, and validation. Domain code imports neither Textual
nor generated SDK models. Raw Kubernetes field names remain intact in records;
display and sorting use separate derived values.

[Curated families](../src/kuberich/domain/curated.py) bind allowlisted facts to
actual group/version/plural/kind/scope descriptors. Scaling, policy and access
extractors share bounded values and literal destinations. [Events](../src/kuberich/domain/events.py)
keep individual API objects separate from aggregate occurrence groups, without
retaining freeform notes in their derived facts.

[Pulse](../src/kuberich/domain/pulse.py) defines scoped overview sources,
health summaries and exact resource predicates. [History](../src/kuberich/domain/history.py)
defines bounded aggregate series, backend-scope declarations and explicit gaps.
Neither model presents an aggregate row as a Kubernetes object.

[Relationships](../src/kuberich/domain/relationships.py) publish immutable graph
identity, provenance and source completeness. [Reference fields](../src/kuberich/domain/reference_fields.py)
extract explicit Pod/template, ServiceAccount and storage declarations without
configuration values. Discovery resolves owner kinds; UID and owner-scope checks
keep replacements separate from valid controller chains.

### Services

[Exports](../src/kuberich/services/exports.py) binds immutable source captures to
one-use disclosure and destination reviews. Its filesystem adapter owns physical
directory traversal, private staged writes and reviewed local entry operations.
The local browser does not use artifact context metadata to connect to a cluster.
See [reviewed local artifacts](adr/0037-reviewed-local-artifacts.md).

[Container inspection](../src/kuberich/services/container_inspection.py) owns
finite Pod/configuration reads and separate fresh disclosure intents. Its
[pure model](../src/kuberich/domain/container_inspection.py) and
[resolver](../src/kuberich/domain/container_environment.py) publish metadata
without retained values. The nested viewer reuses existing captured-target,
clipboard and metadata-export boundaries; connection teardown drains even
detached inspectors. See [container configuration provenance](adr/0038-container-configuration-provenance.md).

[Sessions](../src/kuberich/services/sessions.py),
[workspace](../src/kuberich/services/workspace.py), and
[watches](../src/kuberich/services/watches.py) own connections and active reads.
[Projection](../src/kuberich/services/pods.py) and
[filtering](../src/kuberich/services/filtering.py) prepare rows away from the UI
loop. Commands, access policy, logs, resource changes, transfers, plugins, and
forwards use their own service owners. Services return observations/results,
not widgets, and enforce policy independently of a button or shortcut.

[Log-read identity](../src/kuberich/domain/log_reads.py) distinguishes a known
missing Pod from temporarily unknown membership during a list resynchronization.
The [owned handle](../src/kuberich/services/log_reads.py) observes accepted
workspace publications before UI coalescing and retains no expired collection.
It is specific to an admitted log read; shell, transfer, configuration and write
operations keep their strict captured-selection guards. Direct log viewers own
their handle, while a container chooser owns the shared handle across its child
log viewers. Client teardown and viewer cleanup release that registration.

[Curated navigation](../src/kuberich/services/curated_navigation.py) owns finite
source/target reads, UID and opaque version checks. Inspectors retain both their
fresh GET version and the parent table's observed version anchor. The
[Event projection](../src/kuberich/services/events.py) applies membership and
presentation options inside one owned worker, without another watch or client.
See [curated resource observations](adr/0040-curated-resource-observations.md).

[PulseService](../src/kuberich/services/pulse.py) owns serial overview collection
within the selected workspace session. It publishes per-source progress and
shares a combined retained-payload budget across resource families and samples.
[HistoryWorkspace](../src/kuberich/services/history_workspace.py) owns finite
historical queries, target/configuration generations and a limited cache per
connection. Its detail claim pauses overview history while Pulse health continues.
[HistoryReader](../src/kuberich/services/history.py) verifies the selected Service
proxy; [external HTTP](../src/kuberich/adapters/history_http.py) has separate TLS
and credential state. Fixed queries and membership evidence remain independent
of rendering. [ADR 0039](adr/0039-context-owned-metric-history.md) records limits,
identity gaps, credential boundaries and review-screen lifetime.

[RelationshipService](../src/kuberich/services/relationships.py) owns one graph's
compact facts, expansion and cumulative [read budget](../src/kuberich/domain/read_budget.py).
It preserves denied/partial sources, uses worker-side extraction and matching,
and rejects obsolete client/root/request generations. Refresh starts a new
collection; collapse and expansion reuse the graph's remaining shared budget.

### Adapters

[Kubernetes](../src/kuberich/adapters/kubernetes.py) and
[credentials](../src/kuberich/adapters/credentials.py) own HTTP/TLS and helper
boundaries. [PTY](../src/kuberich/adapters/pty.py),
[terminal](../src/kuberich/adapters/terminal.py), and
[emulator](../src/kuberich/adapters/emulator.py) adapt POSIX and remote terminal
behavior. Adapters validate external data and close their resources. They do not
select another context or mutate process-global SDK defaults.

### UI

[App](../src/kuberich/ui/app.py) composes typed owners and routes root events.
[View controllers](../src/kuberich/ui/controllers/base.py) project/filter/apply
rows through one [render coordinator](../src/kuberich/ui/controllers/rendering.py).
A lazy registry creates the selected adapter; the foreground gate uses actual
root-screen suspend/resume events. [WorkspacePresenter](../src/kuberich/ui/workspace_presenter.py)
owns observation/header delivery; [WorkspaceNavigation](../src/kuberich/ui/workspace_navigation.py)
owns view history and scope restoration. [ResourceOperations](../src/kuberich/ui/resource_operations.py)
uses immutable target capture and explicit process/mutation/forward owners.
[Chrome](../src/kuberich/ui/chrome.py) and screens manage layout, focus, and selection.
Nested inspection/log/container screens retain their selected target and command
ports. [WorkspaceCommands](../src/kuberich/ui/workspace_commands.py) shares service
parsing/policy and the [canonical command catalog](../src/kuberich/services/command_catalog.py).
The App still contains substantial composition and coordination; complete
private-boundary removal and the smaller-App target remain stable-release goals.
See the implemented [application composition record](adr/app-composition.md).

The typed Pulse route uses a dedicated native controller in the same frame.
Navigation preserves its aggregate selection and variable-height viewport;
drill-downs carry the actual API/version, namespace, predicate, sort and UID.
The [overview decision](adr/0033-cluster-overview-and-history.md) records ownership,
expiry and configured backend scope; ADR 0039 extends finite resource history.

The [relationship table](../src/kuberich/ui/relationships.py) and
[controller](../src/kuberich/ui/controllers/relationships.py) show visible graph
paths, provenance and source states. Navigation restores expansion and viewport
from minimal bookmarks; opening an object revalidates its identity. Graph/source
rows are not mutation targets. The [relationship decision](adr/0034-native-resource-relationships.md)
keeps root namespace separate from the selected search namespace for cluster roots.

[Authorization records](../src/kuberich/domain/authorization.py) and
[RBAC matching](../src/kuberich/domain/rbac.py) keep current-identity API reviews
separate from observed declaration analysis. The
[authorization service](../src/kuberich/services/authorization.py) uses fixed
self-review transport and owned collection/matching work; its scoped
[workspace collaborator](../src/kuberich/services/authorization_workspace.py)
invalidates and drains previous requests. Informational results never enable
an operation guard. The [authorization decision](adr/0035-authorization-evidence-and-reviews.md)
defines independent header/question scope, atomic history restoration and the
native table/navigation boundary.

Presentation/rendering faults are isolated to their current view and scope.
An inline Retry explicitly restarts that view; watches and unrelated forwards
continue. Target invalidation, capture, retirement, and cleanup failures remain
fatal ownership boundaries. Fatal reports are written after application cleanup
and terminal restoration; they omit exception values, locals, and source lines.

### Bootstrap and local files

[CLI](../src/kuberich/cli.py), [bootstrap](../src/kuberich/bootstrap.py),
[catalogue](../src/kuberich/config/catalog.py),
[preference schema](../src/kuberich/config/schema.py), and
[store](../src/kuberich/config/store.py) select and validate local inputs.
[Diagnostic reports](../src/kuberich/diagnostics/reports.py) contain metadata and a
limited redacted application-log tail, without kubeconfig or preference bodies.
Build, test, release, and site tools live under `scripts/`, outside installed
runtime behavior. Help/version/info/config-check and bug-report stay offline,
without importing Textual or the SDK. Actual client preparation loads the SDK
inside its worker. Startup and runtime/collection latency targets are advisory
for 0.x; strict opt-ins and actual source major 1 enforce the unchanged limits.
RSS/import boundaries, valid output and frames, deadlines, functionality, and
ownership/cleanup remain mandatory. See the current [quality policy](quality.md).

### Cluster diagnostics

[Diagnostic records](../src/kuberich/domain/cluster_diagnostics.py) and
[literal rows](../src/kuberich/domain/diagnostic_rows.py) keep source, severity,
resource identity, observation/server times and uncertainty separate. Native
classification uses explicit conditions, container states and exact UID-matched
Events. Selected workloads use verified controller chains; explicit PVC fields
add storage evidence without reading configuration values.

[DiagnosticService](../src/kuberich/services/cluster_diagnostics.py) owns finite
native reads and workers. Charged attempts are published before transport waits;
partial sources and per-evidence age remain visible. Explicit resource/log actions
have their own fresh identity checks and limits. Table collection never samples
logs or creates synthetic resource records.

[DiagnosticWorkspace](../src/kuberich/services/diagnostic_workspace.py) serializes
native collection and an explicitly injected
[Popeye service](../src/kuberich/services/popeye.py). One combined finding/text
budget keeps native evidence first and constrains external parsing before
normalization. Same-scope Popeye keeps native observation times; native refresh
clears old tool output and never runs a program automatically. Header and root
collection scope are distinct; namespace/history transitions bind the final
session generation before work starts, and cancellation drains before rebinding
retained incomplete results. The
[diagnostics decision](adr/0036-native-and-external-diagnostics.md) records limits,
external trust/version semantics, navigation and cleanup boundaries.

## Dependency direction

```mermaid
flowchart LR
    CLI["CLI / composition"] --> UI["Textual UI"]
    UI --> Services["Application services"]
    Services --> Adapters["HTTP / process / terminal adapters"]
    Services --> Domain["Domain records and decisions"]
    Adapters --> Domain
    UI --> Domain
```

The composition root may construct adapters; domain decisions never depend on
widgets or SDK objects. Transport work stays asynchronous, and a UI callback
must not become a synchronous network/process wait.

## Cluster sessions and watches

Each selected connection has explicit settings, a client identity, generation,
and cleanup path. Namespace/resource changes keep that client and replace its
active view. Context replacement, retry, or interactive reauthentication drains
the previous connection's work before releasing its TLS and credential files.
[The kubeconfig loader decision](adr/0032-kubeconfig-loader-contract.md) records
Basic authentication, explicit secret-free OIDC migration, and why session-owned
preparation remains necessary instead of the pinned SDK loader.

Discovery selects actual served APIs and scope. Lists use paginated snapshots
with an opaque collection resourceVersion. Oversized lists keep a deterministic
10,000-row/64-MiB payload subset while consuming the remaining pages for watch
continuity; **INCOMPLETE** remains visible until a complete list replaces it.
Explicit server selectors narrow LIST/WATCH; local filters do not. Generic compact
mode can keep Table cells plus PartialObjectMetadata; inspection reads a full
object, and missing-field jumps require full mode. These are payload bounds,
not total-process memory guarantees. WatchState applies UID-based
events; retryable interruptions resume an applied checkpoint, expiration relists,
and permission/protocol failures remain errors. A temporary failure preserves
rows marked stale rather than claiming a successful empty collection.

## Resource data flow

```mermaid
flowchart LR
    API["Kubernetes LIST / WATCH"] --> Transport["KubernetesSession transport"]
    Transport --> Read["ResourceReader / ListWatch"]
    Read --> Store["WatchState / ViewStore"]
    Store --> Observation["WorkspaceService observation"]
    Observation --> Projection["Row projection / filter worker"]
    Projection --> Table["Pod / standard / custom table"]
```

The store owns resource identity; projection derives typed row values and ordering.
The table applies incremental patches while preserving UID selection and viewport.
Same-name replacement objects do not inherit an old action. Generic server columns
keep their printer schema so a changed header cannot relabel an old positional
value. Hidden columns can still participate in filtering/sorting.

## Concurrency and cleanup

Every stream, parser/projection worker, subprocess, and background job has an
explicit owner. Async transport and limited cooperative batches keep the normal
UI loop available. Thread work is drained on cancellation: cancelling an await
cannot terminate an already running filesystem or decoding thread.

Subscriptions keep one pending latest observation; readers use backpressure
rather than unbounded producer queues. Display histories, caches, active jobs,
and subprocess output have separate limits. Those limits do not establish a
universal latency or resident-memory guarantee.

```mermaid
flowchart TD
    Request["New context or view intent"] --> Invalidate["Invalidate old generation"]
    Invalidate --> Drain["Cancel and await obsolete work"]
    Drain --> Replace{"Replace connection?"}
    Replace -->|Yes| Close["Close old client and private files"]
    Close --> Open["Prepare explicit new session"]
    Replace -->|No| Reuse["Reuse current client"]
    Open --> View["Start selected active view"]
    Reuse --> View
```

Dismissal is not the end of ownership. Logs, plugin jobs, forwards, transfers,
confirmed writes, and shell processes must finish their cleanup before client
files disappear. Publication checks reject old generations even after a callback
has already been scheduled. An uncertain write remains uncertain after cancel.

## Security boundaries

- Kubeconfig is trusted local configuration. Exec helpers run with user privileges,
  including to authenticate read-only requests. Operator plugins require explicit
  local definitions and invocation; neither model is an application sandbox.
- Capture context, client, resource UID/version, argv, environment, and directory
  before awaiting preparation. Delegated tools receive the prepared connection,
  not a fresh ambient current-context lookup.
- Apply shared access policy before effectful preparation. Confirmations authorize
  one exact change. Server-side UID/version conditions protect supported writes;
  exec/attach and cross-resource checks still have name/time-of-check races.
- Escape markup and terminal controls separately from credential redaction. Ordinary
  views/exports/logs redact recognized credentials and data fields; deliberate
  data reveal and trusted-editor access have their own fresh-read/disclosure rules.
- Private files and validated staging protect local drafts, credentials, and copies.
  A lost remote connection cannot guarantee termination of a server-side process
  or prove that a sent write did not apply.

## Terminal behavior

The embedded pod terminal keeps Textual active, owns a PTY/emulator, and sends
remote input before ordinary workspace bindings. Explicit local controls return
or quit. History review is local; remote control strings never reach the host.
Editors, provider login, and foreground plugins instead lease the native terminal
through explicit suspension and restoration. Those paths have different owners.

The pinned source still contains narrow private framework adapters for rendering,
cache ownership, and error handling. Their native controls and upgrade tests are
required; a pin or local cache bound is not proof of broader responsiveness.

## Decision records

Use [the ADR index](adr/README.md) for context, decisions, consequences, and source
modules. Preserve decision numbers; add or supersede a record when a verified
implementation changes its boundary. The records below also keep historical
architecture links useful.

| Decision | Record |
| --- | --- |
| <a id="why-python-and-textual"></a><a id="sources"></a>Build the terminal application with Python and Textual | [0001](adr/0001-python-terminal-stack.md) |
| <a id="architecture-decisions"></a>Keep domain decisions independent of terminal and SDK types | [0002](adr/0002-dependency-direction.md) |
| <a id="c01-session-adapter-decision"></a>Use a separate explicit connection for each selected context | [0003](adr/0003-explicit-context-sessions.md) |
| <a id="authentication-and-delegated-tools"></a>Preserve the configured credential identity when delegating tools | [0004](adr/0004-credential-helpers-and-delegation.md) |
| <a id="c02-discovery-and-snapshot-decision"></a>Resolve API identity through discovery and version-pinned layouts | [0005](adr/0005-discovery-and-printer-schemas.md) |
| <a id="single-owned-watch-parser-refs-q03-50"></a><a id="c03-synchronization-decision"></a>Keep collection snapshots consistent and watch versions opaque | [0006](adr/0006-list-watch-continuity.md) |
| <a id="c04-active-view-ownership-decision"></a>Publish only observations belonging to the current view | [0007](adr/0007-active-view-generations.md) |
| <a id="s03-process-and-terminal-ownership"></a>Own external commands through one explicit process service | [0008](adr/0008-external-process-ownership.md) |
| <a id="terminal-qualification-and-shutdown-q02-33"></a>Lease and restore the native terminal for explicit foreground tools | [0009](adr/0009-native-terminal-handoff.md) |
| <a id="shell-controls-during-teardown-d06-51"></a><a id="s04-captured-shell-and-prepared-connection"></a>Keep pod shells inside an owned embedded terminal | [0010](adr/0010-embedded-container-terminal.md) |
| <a id="s01-log-transport"></a><a id="s02-log-viewer"></a>Separate log delivery, retained history, and viewport following | [0011](adr/0011-single-container-log-streams.md) |
| <a id="s06-aggregate-log-ownership"></a>Admit aggregate log sources through controller identity | [0012](adr/0012-controller-owned-aggregate-logs.md) |
| <a id="actions-configuration-and-trust"></a>Bind each resource change to one reviewed conditional request | [0013](adr/0013-reviewed-conditional-writes.md) |
| Validate copied trees privately before destination publication | [0014](adr/0014-reviewed-file-transfers.md) |
| <a id="captured-forwarding-presets-and-bounded-reconnects-s08-62"></a>Manage forwards as connection-owned TCP sessions | [0015](adr/0015-managed-tcp-forwards.md) |
| <a id="audited-plugin-adaptations-u05-60"></a><a id="owned-plugin-execution-u04-59"></a><a id="explicit-plugin-definitions-and-capture-u03-58"></a>Load and execute only explicitly configured local plugins | [0016](adr/0016-explicit-local-plugins.md) |
| Keep local preferences versioned and explicit to save | [0017](adr/0017-versioned-local-preferences.md) |
| <a id="preview-refinement-129"></a><a id="enter-navigation-feedback-115"></a><a id="shared-resource-workspace-125"></a><a id="stable-workspace-and-inline-input-127"></a><a id="terminal-interactions-and-captured-read-workspaces"></a>Keep keyboard ownership and frame geometry predictable | [0018](adr/0018-focused-input-and-workspace-geometry.md) |
| <a id="per-owner-navigation-and-captured-views-u02-57"></a>Pin saved navigation to actual resource and input contracts | [0019](adr/0019-saved-resource-view-contracts.md) |
| <a id="appearance-and-optional-release-reads-u01-56"></a>Treat theme configuration as validated color data | [0020](adr/0020-data-only-theme-palettes.md) |
| Make release discovery optional and non-executable | [0021](adr/0021-opt-in-release-notices.md) |
| <a id="deliberate-configuration-disclosure-m05-55"></a><a id="b04-resource-inspection"></a>Redact ordinary views and require deliberate value disclosure | [0022](adr/0022-default-redaction-and-explicit-disclosure.md) |
| <a id="widget-rendering-cache-ownership-refs-d05-49-d04-40"></a>Scope rendering caches to their application and widget owners | [0023](adr/0023-widget-style-cache-ownership.md) |
| <a id="bounded-native-css-parse-reuse-prerequisite-for-u03-58"></a>Reuse complete stylesheet parses without partial publication | [0024](adr/0024-transactional-css-parse-reuse.md) |
| <a id="native-table-cache-retirement-and-metadata-geometry-prerequisite-for-s08-62"></a>Release discarded native table cache rings promptly | [0025](adr/0025-native-table-cache-retirement.md) |
| <a id="incremental-log-geometry-and-fixed-height-status-refs-q03-50"></a><a id="bounded-formatting-and-collected-parser-outcomes-refs-q03-50"></a><a id="owned-workspace-repaint-refs-q03-50"></a>Bound projection and rendering work without changing its meaning | [0026](adr/0026-incremental-rendering-and-cooperative-work.md) |
| <a id="frozen-runtime-and-external-processes-refs-d05-49"></a>Separate frozen loader state from external program environments | [0027](adr/0027-frozen-runtime-delegation.md) |
| <a id="kuberich-identity-migration-149"></a>Migrate application identity without duplicating runtime packages | [0028](adr/0028-identity-and-preference-migration.md) |
| <a id="phased-immutable-release-decisions-refs-89"></a>Separate tested release preparation from artifact publication | [0029](adr/0029-immutable-release-activation.md) |
| <a id="owned-crashloop-status-synchronization-refs-89"></a><a id="owned-crashloop-qualification-observation-refs-q03-50"></a>Use explicit disposable fixtures and preserve original failures | [0030](adr/0030-owned-verification-fixtures.md) |
| Build standard Python artifacts with one explicit backend | [0031](adr/0031-standard-python-packaging.md) |
| Own kubeconfig preparation and make migration explicit | [0032](adr/0032-kubeconfig-loader-contract.md) |
| Preserve graph identity, evidence and per-root collection ownership | [0034](adr/0034-native-resource-relationships.md) |
| Compose typed views, commands, navigation, and operation owners | [Application composition](adr/app-composition.md) |

## Historical source

The [previous log](internal/architecture-history/README.md) is preserved
exactly with a source commit, checksum, and per-section destination map. It contains
superseded planning and measured history, so it is not the current overview.
[Internal records](internal/README.md) keep engineering acceptance history separate
from current instructions. Historical results do not qualify a new candidate,
platform, or performance result.
