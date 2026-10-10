# Architecture decisions

## Phased immutable release decisions: Refs #89

Release readiness validates the entire pinned 79-task graph and canonical issue
index before any issue request, then selects an explicitly reviewed major/minor
phase and cumulative gates. Early-delivered mapped extras retain their own
prerequisites. D10 follows D06 for initial 0.1 activation; unknown phase lines
fail closed. This changes release preparation, not runtime module/contracts.
Public candidates freeze regular committed authored-note blobs and an optional
source/version/tag-bound reviewed preview before approval. The read-only validator
never generates notes; publisher retries compare the complete frozen body and
immutable assets. The planned Homebrew destination validates the actual project
Organization owner and repository, while source provenance stays personal.
See [release policy](releases.md) and [notes](release-notes/README.md).

## KubeRich identity migration: #149

The maintainer selected KubeRich and confirmed acquiring kuberich.com. The
canonical distribution/import/CLI is `kuberich`; one `kubetrol` console alias
delegates to the same CLI without duplicating production code. Existing default
preferences are read only as a fallback when the new default location is absent.
Canonical application environment variables take precedence over legacy aliases.
Explicit `config migrate` reuses the bounded loader and atomic non-overwriting
writer, preserves unknown fields/source bytes and rebases relative log paths.
Known legacy diagnostic headers remain accepted without broadening arbitrary
file/symlink acceptance. This startup/local-command work precedes Textual and
never loads cluster credentials. Historical acceptance evidence retains its
original artifact names and measurements. Public publication is separately gated.

## Preview refinement #129

Contexts are local kubeconfig catalogue entries, not Kubernetes API resources.
The root `ContextTable` uses exact context names as identity and the shared
workspace frame, filtering and history; it makes no selection-time API/helper
call until Enter. It leaves the owned active resource session running while
browsing, and switching context delegates to the existing awaited replacement
and generation guards. Escape restores the preceding resource state.

The dedicated command bar uses a rectangular border; all implemented workspace
views reserve four interaction rows in ordinary terminals and two below 16 rows.
The compact bar keeps side edges to preserve usable 40×12 tables. Input focus
never changes these dimensions. Inline suggestions and embedded shell routing
remain unchanged.

Critical `domain/containers.py` derives regular/init/sidecar rows from captured
pod specification and name-matched status. Missing readiness/restarts remain
unknown; states retain Kubernetes waiting/termination reasons. Columns describe
image, configured probes, CPU/memory requests/limits and bounded declared ports.
These are snapshot values; opening the pod again refreshes them. Live container
refresh, ephemeral containers and metrics remain #61/#78/#68.

Status: accepted planning baseline, 2026-10-04. Changes require an issue and an
updated decision record in this document. The product is a new implementation.

## Product boundary

The #166 required macOS check exposed XNU's empty-process-group exit race:
`killpg` can return EPERM while its remaining members are exiting/zombies. The
process owner probes a denied Darwin group with signal zero after up to five nonblocking 10 ms waits,
without blocking the event loop or sending another termination signal. Only
ESRCH confirms disappearance; a live group or persistent denial still fails
cleanup. Normal descendant termination and cancellation ownership remain intact.

A second required macOS run exposed a workspace repaint overwriting the rejected
`:ns` message during connection setup. The UI retains this notice for the exact
current immutable view; age-only repaints preserve it, and a new connection/view
observation clears it so later progress or failure remains visible.

C05 #52 resolves one preferred group/resource family across served versions,
with explicit group qualification for ambiguous aliases. Opt-in Table reads
keep immutable bounded printer metadata separate from full resource manifests;
one decoder belongs to a paged LIST or one opened watch. Unsupported conversion
disables negotiation for one GVR and restarts a whole collection, while identity,
RBAC and transport errors retain their original classification. Parsing workers
drain even under repeated cancellation before transport ownership ends.
Workspace refresh replaces discovery/watch state on its existing client and
retains pending namespace intent. Client generation changes hide the previous
catalogue. B06 #53 adds discovery-qualified commands and immutable generic layouts
to the shared workspace. One owned background projection preserves each row's
schema; renewed headers do not reinterpret positional cells. Bounded transient
layouts use context/GVR keys and reset on schema replacement. History captures
the requested preferred/explicit version plus printer headers so an old sort
cannot target a different column after restoration. Generic actions remain
read-only until their mutation owner. Initial explicit resource commands wait
for owned discovery; built-in aliases keep their existing routes.

S07 #48 freezes attach/copy targets and connection material on the event loop,
then owns filesystem work in shielded workers that finish before cleanup.
Attachment shares the existing embedded PTY/emulator and keeps its detach
sequence distinct from global quit. Container identity includes already existing
ephemerals; creating debug containers remains separate.

Copy review freezes paths/effect and snapshot input. Upload uses explicit
zero-retry kubectl cp; predicate classification distinguishes a remote false
result from infrastructure/permission errors. Download owns a bounded subprocess
mailbox/disk stream, scans tar headers before materializing metadata and extracts
only validated regular trees into private staging. No-follow parent descriptors,
exclusive new commits, reviewed file identities and cooperative publication
cancellation protect local destinations. Client replacement drains the screen's
work before credentials are removed. Remote copy/UID preflight windows and
server-side processes after disconnect are documented limits, not atomic promises.

C08 #47 preserves source-entry directories while preparing the effective client.
Captured proxy/environment decisions and strict ExecCredential responses live in
pure domain modules. The session owns serialized credential refresh, periodic
token-file reads and revision-aware TLS pool replacement; actual SSL/key loading
and file work finish before cancellation can remove their directory. New helper
certificates use revision-specific exclusive private files, validate before use
and close old connections to require a new handshake. Failed preparation retains
ownership without allowing a request under a stale certificate.

The pinned aiohttp-socks connector supplies SOCKS5 transport. It drops request-level
TLS hostname overrides, so an SSLContext binds the effective name at the public
Python `wrap_bio` boundary. Actual positive/negative TLS, authenticated proxies,
stream errors and cancellation qualify this adapter. HTTP(S)/NO_PROXY settings are
captured explicitly; ambient netrc identity stays disabled. Shared delegation
freezes the complete inherited helper environment, pins the used executable and
stages the same private connection for exec/forward and future Helm ownership.
Generic `:login` reuses the existing native process/terminal lifecycle. Real cloud
exchanges, legacy auth-provider/basic support and Helm operations are not claimed.

M03 #45 extends conditional patches with one whitelisted `/scale` subresource
for apps workloads, restricted to one integer replica effect. Scale receipts use
autoscaling/v1 identity. `WorkloadService` revalidates workload/history and HPA
ownership; retained templates restore without replicas/strategy. Its separate
read-only monitor polls actual generation/replica/revision state. `WorkloadScreen`
owns and drains preparation/result waiters/monitor before captured SDK cleanup;
confirmed writes remain owned by the bounded mutation manager.

B05 #41 uses immutable `domain/registry.py` definitions for 15 standard resource
families and one `ui/standard.py` table. Commands capture the registry's API group;
the existing per-client discovery selects the served version and actual endpoint.
The shared owned projection accepts both group and resource identity. Summaries
carry bounded display strings and typed sort values, excluding configuration and
secret payloads. Inspection reuses captured UID/client/scope checks. Navigation
history carries a column key and restores it within the selected resource's
columns. Mutations and generic CRD/server columns remain later tasks.

S05 #42 captures immutable forward intent, a per-connection client and UID.
`ForwardManager` owns eight live controllers and at most 32 public history records.
Each controller owns private delegation, a ProcessRunner group, readiness parsing
and periodic UID reads. `SessionService.before_close` drains that client's forwards
before SDK/TLS-directory removal; namespace generations keep the same connection.
Shared shell/forward delegation freezes effective config/helper environment and
stages mode-0600 files with awaited cancellation cleanup. ProcessSession output
drain replenishes consumed capacity without clearing an existing overflow.
Numeric TCP, loopback defaults and explicit non-loopback opt-in are current scope;
FastForward/named ports remain #62. See [port forwarding](port-forwards.md).

Q01 #38 shares an explicit local-kind lifecycle between cluster verifiers.
Generated configuration must match the owned Docker node and published API port
before fixture writes. Process deadlines and scoped signals own cleanup; deletion
rechecks identity and never uses the caller's default kubeconfig. This tooling
remains outside the installed application.

### Terminal qualification and shutdown: Q02 #33

The mounted native application owns SIGHUP/SIGTERM handlers and restores previous
handlers on shutdown. Headless/Web test applications do not install them. Native
handoff temporarily owns these signals so cancellation reaps the foreground child
and suspension resumes before the app exit request. The first signal selects the
exit status. A revoked SSH TTY cannot be restored; the adapter recognizes that
specific loss without hiding live-terminal restoration failures. Captured revoked
output is discarded at hangup so buffered finalization retains the selected code.

The application emulator processes bounded complete control frames independently.
A malformed supported CSI cannot discard following text or cursor queries in the
same PTY packet. Private/standard cursor reports use the active buffer and origin
mode. Shrinking rendered buffers preserves the live cursor and trims unused bottom
rows before shifting occupied rows; both buffer cursors remain inside the viewport.
This is a maintained adapter over pinned Pyte, not a claim of full xterm emulation.

Deferred header refresh checks current attachment and message-pump lifetime,
because Textual's mounted flag remains true after a view is detached. A queued
resize refresh cannot query children of an already removed view.
Native resize handling normalizes the public event against the current TTY
dimensions before Textual's base layout handler. Nested signal callbacks can
enqueue an older snapshot after a newer one; it cannot retarget the current
workspace or embedded child geometry. Headless/Web retain their supplied sizes;
unavailable or zero physical dimensions leave the event unchanged.

Qualification uses actual inner and outer PTYs, an owned loopback SSH daemon and
an isolated tmux server. Real lost-SSH tests distinguish revoked-terminal cleanup
from tmux preservation/reattachment. See [terminal compatibility](terminal-compatibility.md).

KubeRich is a local, keyboard-driven Kubernetes terminal application. It also
runs inside a terminal reached over SSH. There is no application server,
database, hosted control plane, telemetry service, or Textual Web deployment.
The later documentation website is separate from the product.

The initial operating systems are Linux and macOS. Python source installations
target CPython 3.12, 3.13, and 3.14. See distribution.md for qualification rules.

## Chosen stack

| Concern | Decision |
| --- | --- |
| Interface | Textual, with its built-in DataTable, screens, workers, themes, and Pilot tests |
| Kubernetes API | kubernetes_asyncio behind a narrow application-owned adapter |
| Interactive exec and editor handoff | Explicit kubectl/editor subprocesses with Textual suspension |
| Port forwarding | Managed kubectl subprocess with an owned lifecycle |
| Python packaging | src layout, Hatchling, pyproject.toml, uv and a committed uv.lock |
| CLI entry point | Standard-library argparse; command and import package named kuberich |
| Configuration | Versioned YAML schema, validated dataclasses, platformdirs paths |
| Verification | pytest, pytest-asyncio, pytest-cov/coverage.py, Ruff, strict mypy |
| Local regex filters | regex VERSION1 with a total match timeout, owned background work and stale-result guards |
| Cluster integration | Disposable kind clusters and a controllable fake API server |

uv manages development environments, locked dependency resolution, and build
invocation. Hatchling is the configured build backend that produces wheels and
source distributions; `uv build` delegates to it. This retains standard Python
packaging and the Hatchling approach shown in Textual's packaging guide without
requiring contributors to manage two environment tools.

D01 selects runtime modules, TCSS and typing assets explicitly in both artifacts.
The sdist includes the metadata/build inputs, README, changelog, license and
Hatchling-required Git ignore file; development tests/scripts/lock and undeclared
private files remain outside distribution payloads. Required checks verify whole
payloads and rebuild equivalence, then run actual uv tool and pip-backed pipx
installations outside the checkout with owned state and process-group cleanup.

Q04 supply-chain tooling remains under `scripts/`, outside the installed app.
It installs the same wheel in owned locked/fresh environments, inventories metadata
without importing dependencies, and links complete audits/SBOMs/original notices
to candidate artifacts and reviewed inputs. CI verifies that evidence against its
final build. These unsigned sidecars precede D02's publishing/attestation boundary;
they neither access Kubernetes nor publish a package.

D02 release tooling also remains outside the runtime. Pure `release_policy.py`
decisions validate versions, actual checks/protections, source ownership and
immutable retry identities. `release.py` owns bounded HTTP/filesystem operations
and exact artifact bundles. A maintainer-dispatched workflow consumes approved
main quality artifacts without rebuilding; OIDC/write/attestation privileges are
confined to the reviewed publication job. Local development candidates cannot
publish. No local merge exception authorizes a release.

D03 source formula generation stays outside the installed application. It verifies
audited bundles, pins recursive runtime sources and isolates their installation.
Only the approved production release job can propose a formula update. Cross-repo
write access is limited to the tap; update branches are immutable and require
review rather than automatic merging.

Private CI policy #109 uses a standard-library event/ref planner outside the
runtime. Required PRs select all Linux minors and one macOS baseline; main pushes
select Linux; manual main qualification selects all six supported combinations.
The aggregate independently checks the planned matrix and both dependency results.
Release decisions require that exact commit's latest full manual qualification,
retaining the six-job and immutable-artifact requirements. See [quality policy](quality.md).

Runner policy #168 pins all Linux workflow hosts and their setup/owned-cluster
conditions to Ubuntu 24.04. The same planner supplies release job identities;
qualification checks completed status, success and each job's requested host
labels before selecting the pinned Linux artifact. This pins the OS release,
not the hosted image revision or installed system package versions. Historical
receipts stay unchanged; Ubuntu 26.04 qualification remains separate future work.

B03 adds `regex` for local filtering because matching supports an actual timeout
and releases the GIL for immutable strings. A thread alone cannot stop an
unbounded standard-library regex match. Queries remain bounded and matching uses
a total 50 ms budget per snapshot; cancellation drains the worker before exit.
This does not establish the separate maximum-workload performance gate.
See [filter semantics](command-navigation.md) and the
[engine's timeout/threading documentation](https://pypi.org/project/regex/).

The generated async client is selected for explicit API coverage and control
over watches and cancellation. Do not mix clients throughout the UI or rely on
the development branch of an unreleased client. Pin a released compatible
dependency set during bootstrap; uv.lock is the development/test resolution.
An alternative client requires a demonstrated gap and a decision update.

## Why Python and Textual

This is a product decision, not a promise that every upstream behavior is supplied
by the UI framework. Textual supplies widgets, layout, reactive UI, workers and
test tooling; KubeRich must implement Kubernetes semantics, streaming, permissions,
plugins and release engineering. An owned PTY and terminal emulator support the
embedded shell design. Pilot tests are complemented by real PTY tests.

| Option | Fit and tradeoff |
| --- | --- |
| Python + Textual | Chosen: strong fit for Python contributors and a rich terminal UI; requires careful async lifecycle, bounded rendering and platform packaging |
| Python + prompt_toolkit | Strong for interactive command editing; more application-specific work for a full resource browser |
| Python + curses/urwid | Viable, but more layout/state/test infrastructure to assemble for this product |
| Go + tview or Bubble Tea | Strong alternative if native distribution and direct client-go behavior become dominant; changes the project's Python contribution model |
| Rust + Ratatui | Strong performance/control option; higher implementation effort for this team's stated Python preference |

The early delivery gates must demonstrate credential compatibility, real-terminal
exec, and watch correctness before the UI expands. Performance measurements and
clean-machine installations determine whether the implementation is viable. If a
concrete gap cannot be solved in the adapter, record evidence and revisit the
client or language decision rather than hiding the limitation.

## Authentication and delegated tools

F05 #19 captures a frozen `ConnectionOverrides` in the invocation request. CLI
credential paths become absolute against the launch directory without reading
them. Catalogue selection resolves explicit cluster/auth-info aliases and derives
owned mappings while retaining the selected entries' file provenance. Explicit
token or client-certificate overrides replace other credential mechanisms;
helpers belonging to the replaced mechanism never execute.

The owned HTTP transport preserves repeated impersonation headers for JSON reads,
watches and logs. Delegated kubectl receives the same validated subject/groups,
UID/extras and prepared TLS/token configuration in its private connection snapshot.
The workspace header shows effective aliases and impersonated identity; the
context catalogue table continues to describe stored entries.

An app-owned Textual timer uses the effective refresh interval for table ages
and local projection repaint. Watch observations remain immediate and retain
their independent server renewal deadlines; refresh never starts periodic API
polling or credential renewal. App shutdown owns timer and task cancellation.

Treat kubeconfig as trusted local configuration: its exec credential helpers can
run local code. Never fetch and execute a kubeconfig from a cluster resource.
EKS uses the configured AWS exec helper; AKS uses the configured Azure kubelogin
helper. Honor expiration and interactive behavior, and distinguish authentication
failure from API authorization. Qualification tasks cover the Python SDK's gaps
relative to client-go; using the SDK alone is not proof of compatibility.

Build an effective per-session connection specification from file/environment/CLI
precedence. Both SDK calls and delegated kubectl/Helm commands must use it,
including impersonation, proxy and TLS overrides. When a temporary kubeconfig is
needed, use restrictive permissions, do not log it, and clean it up. Never fall
back silently to another context or user. See [CLI contract](k9s-cli.md).

## Dependency direction

```text
CLI -> Textual UI -> application services -> Kubernetes/process adapters
                         |                          |
                         v                          v
                  domain state/models       API and process events
                         ^                          |
                         +--------------------------+
```

Use src/kuberich/{ui,services,domain,adapters,config}, with tests grouped into
unit, contract, ui, integration, terminal, and packaging. Keep this structure
small initially; create modules when real behavior needs them.

Domain code imports neither Textual nor generated SDK models. Normalize SDK
responses to application-owned resource snapshots. Preserve Kubernetes field
names when retaining raw manifests, and use separate derived display values.

## Cluster sessions and watches

Each context has an explicit client configuration, session generation, task
owner, resource store, and cleanup path. Do not mutate process-global client
configuration or the user's current kubeconfig context.

LIST returns an initial snapshot and collection resourceVersion. WATCH starts
from that version. Handle ADDED, MODIFIED, DELETED, BOOKMARK, timeout, EOF,
expired versions (410 with relist), retryable failures with bounded exponential
backoff/jitter, and non-retryable permission failures. Follow pagination without
losing the collection's consistent snapshot. Resource versions are opaque.

Switching context or scope cancels and awaits old tasks, closes streams, and
rejects late results using the captured session generation. Show stale or
disconnected state explicitly. Do not turn permission or transport failures into
empty resource lists. Watch only resources needed for active views and bounded
background features.

## Terminal behavior

B01 implements `ui/app.py` as the disconnected Textual workspace and
`ui/launch.py` as its synchronous CLI/TTY boundary. Settings and an owned
diagnostic logger are injected; no Kubernetes configuration or client is loaded.
Packaged TCSS styles resolve relative to the application module, including in
installed wheels. Shortcut focus changes use the public `App.set_focus` API
immediately, with priority bindings disabled inside inputs, so the next queued
key reaches the selected input even when the terminal batches keystrokes.

Textual 8.x's default fatal-error display includes exception values, source and
locals. Two narrowly scoped private overrides preserve its exception handling,
test propagation and terminal cleanup while routing errors to the sanitized
logger and suppressing raw console tracebacks. The launcher reports an owned
message/exit code. Pilot and real PTY failure tests qualify this boundary; each
Textual upgrade must recheck those hooks against the pinned implementation.
There are no custom background tasks or blocking I/O in B01 event handlers.

Use stable resource identity (context, group/resource, namespace, UID); derive
row order separately. Preserve selection and scroll position while applying
batched incremental updates. Sort quantities and timestamps by typed values.
Respect focus, terminal resize, narrow screens, Unicode width, and plain-color
fallbacks. Key hints must reflect actions actually available in the current view.

Keep normal UI event handlers free of blocking I/O. Capture the target context,
namespace, resource, and container before starting an action. Each stream or
process has a lifecycle owner. Log storage and render queues have bounded
capacity; implement explicit overflow and backpressure behavior.

Container shells use an owned nonblocking PTY and an embedded terminal screen.
Textual retains the host terminal and draws a persistent target frame. Capture
argv, prepared kubeconfig/context, namespace, pod UID and container before awaits;
resize the child PTY to the widget, route shell keys deliberately and reap owned
processes before dismissing. Generic native handoff remains available for other
effectful tools. The maintainer's clarified feedback #121 supersedes the earlier
initial-scope decision that excluded terminal emulation.

## Actions, configuration, and trust

M04 #46 adds immutable DELETE/create intents in critical `domain/operations.py`.
Deletion captures explicit propagation/grace and UID/version preconditions;
Job suspension reuses conditional JSON Patch. Manual Job creation freezes a
template and unique request name, reports identity and never retries. Source GET
and Job POST are separate requests, with that race disclosed. Public HTTP
middleware translates retryable disconnects so aiohttp cannot silently replay
DELETE. Receipts are bounded and decoded through an owned awaited thread.
`ResourceOperationService` binds one-use proofs to action/client/target/version;
post-delete observation distinguishes acceptance, finalizers, absence and
replacement. `BatchDeleteService` owns at most 100 explicitly captured targets,
executes sequentially and preserves per-item partial/unsent/uncertain outcomes
through the existing bounded mutation manager. Its UI defaults to Cancel,
requires the exact reviewed delete count, and drains readers/result waiters before
client cleanup. No collection DELETE or finalizer removal is supported.
See [resource operations](resource-operations.md).

M01 #43 implements conditional JSON Patch through the owned per-context transport.
Immutable request bytes carry UID/version tests; one-use confirmation binds their
exact identity and captured API path. Services enforce the shared write policy
before reads and before sending, revalidate the object and return typed outcomes.
The adapter sends one PATCH without redirect, 401 refresh/replay or blind retry.
Requests and decoding are drained before client cleanup; bounded public history
retains uncertain results without manifests/values/credentials. `:annotate` is the
first concrete action, with Review/Cancel as the default and separate Confirm.
See [guarded changes](mutations.md).

M02 #44 keeps bounded YAML parsing, identity checks and structural differences in
critical `domain/editing.py`. The filesystem adapter owns private drafts and
drains creation/read/cleanup threads under repeated cancellation. EditingService
retains the original snapshot/version, captures trusted editor argv, invalidates
old proofs and requires the exact intent to pass strict server dry-run before
confirmation. The form discloses local full-manifest access, shows a separately
redacted diff and defaults to Cancel. Native handoff reuses the shared process
owner. Preparation/file cleanup completes before form return or captured client
close; already confirmed requests retain mutation-manager ownership. Secret
manifest access remains C04 #55. Scale and deletion use their separate reviewed
forms in #45/#46. See [editing](editing.md).

Mutations go through services that capture identity, enforce read-only mode,
present the target and consequences, handle permissions/conflicts, and return a
typed outcome. Never retry an uncertain non-idempotent mutation blindly.

Configuration has a schema version, validated defaults, atomic writes, unknown
field handling, and migration tests. Secrets are hidden in ordinary views and
redacted from exports and diagnostics. Escaping resource markup and terminal
controls is separate from Kubernetes authorization.

F03 implements a flat schema-v1 dataclass for theme, refresh, read-only and
diagnostic settings. Its bounded safe YAML loader rejects duplicate/nonstring
keys and aliases, retains unknown fields, and migrates v0 names in memory.
Global file/environment/CLI precedence is explicit; context-specific overrides
arrive with the context implementation. Atomic writes never happen on load.
The owned rotating logger uses private files, a process lock, credential
redaction and bounded records; debug traceback values/source/locals are omitted.
CLI diagnostics use an allowlist and never load Kubernetes credentials or run auth helpers.
See [configuration](configuration.md) for the implemented contract and exit codes.
Startup filesystem work runs before Textual; future UI reads/writes must use
an owned worker rather than blocking a normal event handler.

Plugins are trusted local executables declared by users. Resolve bindings and
resource scope before invocation, pass selected-resource context deliberately,
and own foreground/background process cleanup. Never auto-discover executable
plugins from a cluster response or the current working directory.

F04 adds literal bounded Rich text, shared control escaping, immutable argv and
client/UID target snapshots. Diagnostic redaction uses the shared control helper.
Per-client UUIDs distinguish even reopened contexts with the same name/generation.
These helpers do not authorize writes or make a local staleness check atomic:
future services must enforce read-only policy, bind the captured client and use
appropriate API preconditions. Tests trap ambient SDK loaders and permit only a
qualified owned loopback fixture. See [security integration contracts](security-primitives.md)
and the [focused threat model](kuberich-threat-model.md).

The maintainer validated the K9s-style local execution model for F04 on
2026-10-04: configured authentication helpers may run automatically for login
and credential renewal; ordinary plugins require operator invocation. Both
run with the launching user's privileges, without an application sandbox.
Provider interaction, process ownership and read-only enforcement remain
separate implementation/qualification requirements in their existing issues.

F05 stage 1 registers the audited CLI contract while retaining explicit
unavailable gates in `config/launch.py` for absent transport/export/theme behavior.
Gates run before filesystem work or authentication. A frozen `AccessPolicy` and
`CommandService` in `services/` are shared by initial CLI and interactive command
resolution; unknown typed actions fail closed. Future effectful services must use
this guard before their adapters. This stage does not prove API/RBAC enforcement
for operations that do not exist yet, and F05 remains open pending integrations.
Session-only `ui/presentation.py` controls widget visibility, independent of
settings/policy. Read-only status survives hidden headers and input updates.
Refresh can be validated by local diagnostics but explicit UI use fails until
live synchronization exists. See the [current CLI contract](k9s-cli.md).

## C01 session adapter decision

`config/catalog.py` owns bounded read-only kubeconfig merge/provenance.
`domain/connections.py` defines validated requests and safe state observations.
`services/sessions.py` owns client replacement, generations and namespace scope;
`adapters/kubernetes.py` owns explicit SDK configurations/private TLS material;
`adapters/credentials.py` owns noninteractive bounded exec-token processes/cache.
`ui/scopes.py` and the app render these contracts without SDK models.

The pinned SDK's default loader can run helpers with unbounded sequential pipe
reads, log raw helper errors, refresh/persist provider configuration and use
process-global defaults. C01 constructs explicit configurations without those
loaders. Its namespace adapter uses the SDK-created TLS connector and API-owned
pool with bounded streaming reads, disabled redirects/decompression and explicit
proxy configuration. It replaces the pool before requests to disable ambient
netrc/proxy identity, using a narrow SDK `rest_client.pool_manager` boundary.
Transport tests qualify this boundary and must be rerun on SDK upgrades.
Generic exec tokens are implemented. C07 adds explicit native Azure helper login;
generic interactive providers and exec certificate rotation remain C08 qualification.

C06 #21 captures inherited helper environment per session, preserves declared
AWS args/env and pins delegated AWS variables/HOME, helper executable and working
directory to the same session. Credential cache revisions prevent delayed 401s
from invalidating a newer refresh, even for identical token bytes. Pure fixed
provider diagnostics remain independent of process/UI glue. The optional EKS
smoke requires an explicit authorized test kubeconfig/context/namespace; actual
cloud qualification remains pending. See [EKS contracts](eks-authentication.md).

C07 #22 separates exec invocation and private response acceptance so explicit
Azure login uses the same adapter/session configuration. `:login` is carried as
an owned connection operation through workspace/session services; replacement and
exit cancel/drain it before another context. The existing process runner captures
stdout for authentication while the native terminal receives provider stderr;
stdin follows the declared exec mode. UI suspension is explicit and bounded.
A cancelled current login publishes a retryable auth state; replacement discards
that result. SPN certificate inputs remain native bearer exchange; generic exec
TLS credential rotation remains C08. See [AKS contracts](aks-authentication.md).

The UI owns its connection task chain. Context replacement cancels/awaits the
previous task before opening the next client, rejects late observations and
awaits final session cleanup on unmount. File preparation runs in an owned
shielded thread task: cancellation waits for it before deleting TLS files.
See [supported behavior and bounds](context-sessions.md).

## C02 discovery and snapshot decision

`domain/resources.py` contains validated discovery descriptors, scoped endpoint
construction, alias resolution and immutable typed metadata/raw manifest records.
`services/resources.py` negotiates modern/legacy discovery and reads complete
atomic, version-consistent collections using an existing explicit session.
`adapters/kubernetes.py` shares its authenticated, bounded read-only JSON transport
between namespace and resource discovery. Owned JSON-decoding tasks are awaited
even on cancellation; HTTP failures expose safe status codes without server bodies.

Partial discovery is explicit, list errors never become successful empty rows,
and expired pagination restarts the entire snapshot once. Optional UID/version
values on non-watch aggregate APIs remain absent rather than fabricated. This
backend does not start UI workers or live watches; C03/C04/B02 integrate those
behaviors. See [resource discovery](resource-discovery.md) for the contract and limits.

## C03 synchronization decision

`domain/watches.py` owns event/Status normalization, UID-indexed state, bounded
replay memory and pure retry decisions. `services/watches.py` owns an awaited
list/watch loop and its explicit sink, response closure, cancellation and retry
timing. The adapter shares authentication/TLS requests between bounded JSON reads
and watches. It yields complete JSON lines without a producer queue; owned
decoding and normalization workers are awaited on cancellation.

EOF/transient failures resume the last fully applied opaque version. Expiration
invalidates the cache and relists; permission/protocol failures stop. Slow sinks
apply backpressure and consumer failures propagate. Context-generation routing,
UI subscriptions and batched presentation remain C04/B02. See the implemented
[resource synchronization contract](resource-watches.md).

Preview correction #107 separates ordinary request/header deadlines from watch
body lifetime. Server expiry happens before the bounded client lifetime; no
bookmark traffic is assumed. Clean EOF after a healthy established interval
renews the checkpoint while keeping LIVE. Immediate EOF/transport failures keep
stale/retry behavior; only an established healthy stream resets prior failures.
The interval starts after headers, so failed slow establishment cannot mask outages.

## C04 active-view ownership decision

`domain/views.py` owns immutable view observations and pure generation/freshness
decisions. `services/workspace.py` connects explicit sessions, per-client discovery,
one active watch and bounded latest-state subscriptions. Selection invalidates
snapshots immediately, coalesces intent, cancels once and awaits obsolete work.
Captured client/session/scope and revision reject late results/errors. Published
problems copy safe fields without transport traceback/client references.

The Textual app subscribes on mount, checks current revisions and updates status
on the event loop. Unmount awaits watch/transition/client/subscription cleanup.
Pod counts and stale/failed states are visible; rendering rows, sort/cursor
preservation and commands remain B02/B03. See [active resource views](resource-views.md).

## Sources

- [Textual workers](https://textual.textualize.io/guide/workers/)
- [Textual focus API](https://textual.textualize.io/api/app/#textual.app.App.set_focus)
- [Textual app suspension](https://textual.textualize.io/api/app/#textual.app.App.suspend)
- [Textual packaging with Hatch](https://textual.textualize.io/how-to/package-with-hatch/)
- [uv build backends](https://docs.astral.sh/uv/concepts/build-backend/)
- [Kubernetes API concepts](https://kubernetes.io/docs/reference/using-api/api-concepts/)
- [kubernetes_asyncio](https://github.com/tomplus/kubernetes_asyncio)

- [AWS EKS kubeconfig and authentication](https://docs.aws.amazon.com/eks/latest/userguide/create-kubeconfig.html)
- [AKS kubelogin authentication](https://learn.microsoft.com/en-us/azure/aks/kubelogin-authentication)
- [Bubble Tea](https://github.com/charmbracelet/bubbletea)
- [Ratatui](https://ratatui.rs/)

## B04 resource inspection

`domain/inspection.py` produces bounded redacted plain-text documents and literal
search coordinates without SDK or Textual types. `services/inspection.py` captures
an explicit client/API descriptor/target, verifies the individual GET's UID and
name, reads bounded UID-associated core/v1 events, and drains owned serialization
work on cancellation. `ui/inspection.py` owns the read task and read-only TextArea
modal, preserving the underlying table while rejecting invalidated targets.
See [ordinary-view policy and controls](resource-inspection.md).

## S01 log transport

`domain/logs.py` validates query options and frames/redacts bounded UTF-8 lines
with consumer-owned retention. The adapter opens a scoped `text/plain` stream
with bounded headers and an explicit indefinite quiet-follow body. `services/logs.py`
verifies captured pod UID/container before and after opening, awaits each consumer
and closes its generator on cancellation/failure. Logs have no watch checkpoints
and are never automatically replayed. S02 owns the UI presentation and lifetime.
See [the transport contract](container-log-transport.md).

## S02 log viewer

`domain/log_view.py` owns retained line identities, marks, read windows and
clipboard bounds. `ui/log_body.py` virtualizes retained line layouts, yields
layout work, preserves viewport identity and separates navigation follow from
reception pause. Primitive immutable text/cell-width/highlight descriptions retain
the full bounded layout;
actual Textual Strips use a 128-entry visible cache keyed by line/subline and
checked against the current descriptor identity. Rich wrapped highlight ranges
survive folding; style construction occurs only for viewed rows. Theme changes
invalidate visible styles even without a new layout or incoming data.
Invalidation clears both caches. The aggregate formatter hands the widget
sanitized `(number, text)` pairs, avoiding another LogEntry/LogLine object pair.
`ui/logs.py` owns one serialized read controller, batched render
task and optional save task. Changing options cancels and awaits the old read;
dismissal cancels tasks before widgets are removed and unmount drains them.

The pinned Textual 8 ScrollView needs its scrollbar bounds synchronized when
virtual content grows without changing outer geometry. The body's public
`watch_virtual_size` uses the framework's `_scroll_update` boundary before
restoring the viewport. Qualify initial follow, mouse/keyboard scrolling,
eviction and resize on framework upgrades; changing content size alone must
not leave scrolling disabled.

`services/log_export.py` saves sanitized retained text outside the event loop to
an exclusive mode-0600 file, never replacing an existing file/symlink. Explicitly
requested file work is drained even if the viewer closes. Captured pod/client
invalidation clears the viewer and prevents later display/copy/save, including
while a child prompt is open. See [the viewer contract](log-viewer.md).

## S06 aggregate log ownership

`domain/aggregate_logs.py` owns controller-chain membership, per-container start
evidence, stable source identity and independently bounded source/aggregate
retention. Controller UID indexes avoid Pod×intermediate scans. Spec/Pod phase
alone does not open a reader: each regular/init/ephemeral container requires
running/terminated log evidence, with valid last-terminated fallback for waiting
containers and independently selected Previous history. `domain/log_json.py` bounds JSON decode and
post-decode redaction at the shared decoder boundary, preserving useful safe
fields and scalar types before any emitted line.

`services/aggregate_logs.py` owns one captured client/GVR/parent UID, Pod
LIST/WATCH, optional ReplicaSet/Job LIST/WATCH, admission controller and at most
eight `LogStream` readers. Each reader validates Pod UID/container and source
generation. Shared decoder chunk/final framing runs through the existing owned
parser worker and drains before cancellation returns. A pre-open current-log 400 can retry only after changed start
evidence; opened/ended streams do not auto-replay. Explicit picker admission is
independent of display filtering. Current metadata caps at 256 sources and
refuses excess; recent removed status caps at 64. Per-source history caps at
500 lines/256 KiB and aggregate history at 5,000 lines/4 MiB, accounting for both
plain/JSON presentation. Arrival IDs establish order; timestamps do not.

`ui/aggregate_logs.py` reuses the log viewer controls and owns serialized worker
formatting/export. It patches source rows by identity, retains an expired selected
row safely and invalidates layout caches when mode/timestamps change. The app
retains at most one aggregate screen in an ownership registry until cleanup
finishes, even after dismissal removes it from the visible stack.
`SessionService.before_close` drains this registry before client/TLS cleanup.
All watches/readers/render/copy/save work is cancelled and awaited on leave or
context replacement. See [aggregate controls and limits](log-viewer.md#all-container-and-workload-logs-s06-54).

## Enter navigation feedback: #115

Command arrow selection is deliberate completion intent. The Input key action
refreshes current candidates and accepts the selected value before posting the
submitted message or moving focus. Query/focus/candidate changes and a workspace
revision reset that intent; plain literal submissions remain independent.

Pod Enter captures the same owned client/session/namespace/UID/current predicate
as direct logs, then opens a container DataTable screen. Rows are bounded regular
and init names from that captured manifest, with app/init/sidecar type labels.
Enter captures the row before opening LogScreen with an explicit initial container;
the log screen retains all names for its existing container-switch action. The
parent screen stays on the stack, preserving its cursor/viewport. Esc cancels
and awaits log ownership before returning to containers, then pods.

The workspace observer validates both visible and covered container/log screens.
Stale targets disable container selection; the log service still verifies the
captured pod UID and declared container before and after opening the API stream.
The container list is a snapshot; reopening refreshes it. Live container status
and broader resource drill-down remain #61; ephemeral containers remain #78.

`ui/presentation.FrameTable` captures the inherited Rich style once for a
synchronous `render_lines` call in Pod, standard/custom and aggregate source-picker
tables. Nested renders share that immutable frame style; `finally` restores the
enclosing value, so failures or later theme, visibility and layout changes cannot
retain stale colors. It retains DataTable's rows, cursor, events and rendering.

Q03 #50 keeps header-determined width updates bounded in that same table. A
bounded per-table trust flag permits the shortcut while row contents remain owned
immutable `TableCell` values. Mutable/custom row or column-default renderables
and explicitly unsized edits retain native rescans until public `clear` resets
all rows. Exact plain single-line headers and unchanged automatic-width bounds
are also required. `ui.pods.PodCell` retains the shared cell's constructor alias;
unknown renderables retain native evaluation order. The public update still
performs ordinary repaint. This removes one measured full-column hot path and
does not establish the Q03 performance gate.

This uses public [Textual DataTable](https://textual.textualize.io/widgets/data_table/)
row events/actions and [Input](https://textual.textualize.io/widgets/input/) submissions.

## S03 process and terminal ownership

`domain/processes.py` captures command/environment/cwd/mode/purpose and explicit
kubectl/editor arguments before awaits. `services/processes.py` owns an injected
per-app runner, shielded startup/resolution, typed sessions and bounded
asyncio SubprocessProtocol transports. Read-only policy runs before lookup and
cannot be bypassed through a raw service call. The app closes its runner on
unmount. Background handles retain ownership when an individual waiter cancels.

`adapters/terminal.py` leases actual POSIX foreground-group ownership and TTY
attributes. `ui/handoff.py` composes it with public Textual suspension, refuses
concurrent/native-incompatible handoffs and resumes before propagating any
error/cancellation. The pinned context manager's post-yield resumption makes
that ordering necessary. Parent SIGTERM during handoff requests cancellation;
app exit follows terminal restoration, avoiding a driver restart/shutdown race.
The low-level protocol bounds captured bytes without StreamReader pipe-drain
deadlocks when an exited leader leaves descendants holding descriptors.

S03 requires F05's merged stage-1 shared policy/argument contract; advanced
connection overrides remain in the open F05 issue. The native pod/container
exec route and actual Kubernetes exec qualification remain S04. See the
[service contract and limits](process-handoff.md).


## S04 captured shell and prepared connection

`services/shell.py` captures the selected container, pod UID, session and literal
shell argv before awaits. It GETs that exact pod, rejects mismatched/replaced or
finished/deleting targets, and rechecks the current view before terminal handoff.
Read-only policy precedes capture, file work and executable lookup. The server
authorizes pods/exec; KubeRich never retries an exec automatically.

`KubernetesSession.delegated_config()` snapshots the already prepared endpoint,
TLS material and credential mechanism. Kubectl receives only that session via an
explicit mode-0600 kubeconfig in the owned mode-0700 SDK directory, plus explicit
context/namespace/pod/container flags. This avoids rereading a changed source
kubeconfig and delegating to another server/user. Relative helper executable
paths are resolved against their original kubeconfig directory. Helper arguments
remain literal; configured helpers are trusted local programs. Advanced connection
overrides remain F05/C08. The staged file is removed after return, failure or
cancellation; owned file threads are drained before session cleanup.

S04 and feedback #119 originally used S03's native controlling-terminal handoff.
Feedback #121 replaces the default shell route with `ui/terminal.py` and keeps the
container/pod screens mounted. The shell screen owns preparation, PTY reading,
cleanup and the return result; covered-screen target validation cancels stale
sessions. App key routing sends input to the remote process before global
bindings; Ctrl+] returns locally and Ctrl+Q quits. The normal UI never suspends.

`adapters/pty.py` uses nonblocking master descriptors and event-loop readers/writers
with bounded queues. `ProcessRunner.terminal` retains the shared policy, startup
race guards and process-group cleanup. A stdlib-only child launcher, executed by
the current interpreter with `-I`, acquires its new session's controlling slave
before exec; no preexec hook runs Python after a threaded fork. Explicit argv,
captured environment/cwd and staged authentication remain unchanged.

`adapters/emulator.py` wraps pinned, unmodified Pyte 0.8.2 using its documented
screen/event-listener API. A dynamic listener routes cached callbacks to normal
and alternate buffers. Only supported terminal modes are accepted; geometry,
control-sequence memory, saved cursors and combining cells are bounded. Remote
control strings never reach the host driver. `domain/terminal.py` supplies critical
size/keyboard/paste decisions. Rendering builds literal styled segments and
coalesces equal styles; color values are validated before Rich sees them.

See [shell behavior, dependency license and limits](container-shell.md) and
[embedded-shell evidence](acceptance/embedded-shell.md). Native handoff's earlier
qualification remains in [S03](acceptance/S03.md), [S04](acceptance/S04.md) and
[the clean native transition](acceptance/shell-transition.md); it does not prove
embedded-terminal behavior.

## Shared resource workspace: #125

`ui/chrome.py` supplies an original built-in `k9s` theme, injected identity/shortcut
headers and literal Escape trails. It owns no network requests. Context/cluster/
user aliases pass through redacted literal text; installed version is local
metadata, without inferred release/metric state.

Namespaces use the existing active-resource LIST/WATCH service. The root switches
pod/namespace tables and retains resource kind in bounded navigation history.
Critical `domain/namespaces.py` derives UID/lifecycle/age values. Shared typed
projection/filter services retain owned thread drain and stale-result guards.
Tables patch at most 128 rows per turn and preserve UID cursor/viewport; inactive
projection caches are cleared. All-namespaces is an explicit scope action.
Container/log screens retain existing lifetime/target services with shared headers
and trails. Embedded shells keep independent remote-key routing and target frame.
See [workspace controls and limits](resource-workspace.md).

Preview refinement #132 replaced the boxed brand with an original literal ASCII
logo. Identity migration #149 updates it to KubeRich while the shared header
reserves 22×5 cells from 120 columns and uses the
existing 10×3 reservation for a compact wordmark below that width. The breakpoint
preserves two shortcut columns where the full logo first appears. Narrow/short
and launch-presentation visibility rules are retained, without a new dependency
or external lookup. The identity migration retains the same workspace geometry.
`ViewActions` reflows its hints on its own non-bubbling
[Resize event](https://textual.textualize.io/events/resize/), including late logo
width changes after the outer header has settled. Root view changes still replace
the current shortcuts through the shared header.

## Stable workspace and inline input: #127

`WorkspaceBars` reserves two interaction rows and `WorkspaceFrame` owns the same
resource margins/minimum height across root, container and log screens. Header
shortcut columns use the available fixed header rows, independent of action
count. Breadcrumbs and the footer status row stay outside the frame. Log search
is above the frame and stream/target ownership is unchanged.

`CommandInput` retains the bounded synchronous session-local completion provider.
It projects the selected suffix into pinned Textual 8.2's `_suggestion` field only
when rendering, using the native Input renderer for styling, literal Rich text,
cursor/selection and Unicode horizontal scrolling. This single private field is
a qualified framework boundary: recheck it on Textual upgrades. No asynchronous
suggester worker/cache can outlive a workspace generation. Right retains editing
semantics; Tab or deliberate cycling+Enter accepts actual candidate text.
The resource overlay widget is removed. See [controls](command-navigation.md) and
[geometry/terminal evidence](acceptance/stable-workspace.md).

Q03 #50 also retains one table-owned ordering marker for the selected column,
direction and public row-order revision. Immutable model edits invalidate it when
the actual typed ordering value or stable namespace/name/UID tie changes; public
membership/clear/native sort changes invalidate the revision. Pod ordering shares
its typed value with the domain's canonical order function. Standard and discovered
columns use their own typed value. Interrupted batches retain invalidation until
an accepted view finishes ordering; schema/context replacement clears row ownership.
Selection/scroll restoration and generation rejection remain independent.
