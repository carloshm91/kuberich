# Architecture decisions

## Offline startup and first-frame readiness

The CLI parses help/version without importing the terminal application. A small
bootstrap seam keeps the existing installed-metadata, configuration, logging and
launch ports while importing their implementations only when used. Offline
configuration validation shares a pure catalog of the pinned framework's theme
names; a parity test checks that catalog against Textual's public definitions.
Every configured navigation, appearance, forwarding, jump, context and plugin
validation remains in its original order. An absent extension can avoid its
unused parser imports; explicit empty or invalid values still validate normally.
The selected theme is always checked. An entirely empty set of resource views
can additionally avoid unused command/registry imports.

The Kubernetes adapter imports the actual SDK inside its owned preparation
worker, after the session is allowed to connect. Constructing a client or importing
an adapter does not import SDK models. Once a connection is prepared, the normal
SDK initializes its model catalog; this does not introduce an upstream model
loader or change Kubernetes serialization.

HTTP/proxy libraries are likewise deferred to actual transport calls. Optional
release checks load their HTTP module through the existing owned file worker,
so cancellation drains preparation before the owner exits. Unused modal screen
families load in their requesting actions, while root events and root-only view
observations do not import terminal/log/editor screens. The existing public
`HelpScreen` import remains a literal lazy compatibility export; constructor
injection ports such as `PodProjection` and `CustomProjection` remain eager.
No generic facade, screen proxy or upstream loader is introduced.

`SessionService.before_connect` is an optional asynchronous readiness port,
independent of Textual. Its wait is inside the existing connection ownership and
cancellation boundary, before client construction, credential helpers or network
work. The terminal's public `call_after_refresh` callback starts an owned
registration task, yielding before registering inactive DOM nodes even with
Python's eager task factory. The actual selected initial table is eagerly
composed, while the original eager column-model setup remains unchanged for all
tables. On-demand routes register their real target synchronously before
configure/focus; background registration yields between the remaining tables.
Readiness requires the actual first refresh and complete registration. A public
`App.exit` override stops new registrations immediately and preserves the
framework's result, message and return code. Shutdown drains every native
completion. This adapter covers the existing nonblocking resource tables, not
arbitrary third-party handlers that can block Textual's queued teardown.
Initial command/history ordering remains synchronous, while quit and context
replacement drain or supersede the pending connection normally. Optional release
checks are also queued after refresh and remain disabled by default.

The startup qualifier observes the actual CLI in fresh interpreters and the real
application on an owned 120×36 PTY. It retains both the public refresh callback and
visible PTY delivery times, rejects SDK/helper/network work before that refresh,
and verifies the mounted selected table's columns and bounded geometry. It
requires normal client cleanup and alternate-screen restoration. It never
loads a maintainer kubeconfig or connects to a real provider. See the
[startup acceptance record](acceptance/startup-budget.md).

## Native table-cache retirement and metadata geometry: prerequisite for S08 #62

`FrameTable` uses a small native LRU subclass for its six rendering/ordering
caches. It leaves lookup, insertion, eviction, counters and original capacities
with Textual, but unlinks discarded rings on clear/discard/owner retirement.
This releases retired rendering values without waiting for a later cyclic
collection. The adapter applies only to KubeRich-owned tables; no framework
global or garbage-collection policy changes. Pinned native-control tests cover
the ownership boundary and ordinary cache semantics.

Configuration-key metadata supplies explicit cell widths before its first paint.
Reload reconstructs those columns from the new captured index and restores the
selected key identity. Values remain hidden; a deferred native auto-width scan
cannot leave key names clipped to their shorter header labels.

## Captured forwarding presets and bounded reconnects: S08 #62

`domain/forward_presets.py` resolves literal names/container-qualified mappings
against one captured resource and keeps transport selection independent from
Textual. `config/forwarding.py` validates explicit, versioned local opt-in and
exact-context replacement. Cluster annotations cannot grant permission, select
an address or initiate listeners during list/watch updates. The existing action
captures resolved numeric intent before asynchronous preparation.

Only a previously ready, disconnected child can enter the optional, bounded
reconnect loop. Startup failures terminate the controller without retrying helper
or configuration errors, including a failed replacement during reconnect.
The previous ownership stack drains its process and private files first;
each new attempt refreshes delegation, rechecks UID/scope and probes ports.
No implicit client replacement or mutation retry occurs. A Service restart lets
kubectl select its current backend, with observed readiness kept distinct from
requested Service ports. Transport overrides affect only the owned child, and
WebSocket preference does not imply measured negotiation.

## Audited plugin adaptations: U05 #60

Compatibility is a reviewed documentation/fixture boundary, not a second parser
or implicit importer. The 50 pinned records retain original Git blob/SHA-256
identities; each of the 108 command names has an explicit classification. Only
18 original argument-vector adaptations claim their tested literal contracts.
Three standalone original manifests use the same explicit loader, captured
connection and process owner as user definitions. No downloaded script executes.

Plugin scopes now accept valid hyphenated DNS resource plurals; Kubernetes
[CRD validation](https://github.com/kubernetes/apiextensions-apiserver/blob/v0.36.4/pkg/apis/apiextensions/validation/validation.go)
uses DNS1035 labels for the plural. Boolean inversion syntax is rejected with
its actual meaning, after protecting literal dollars. Explicit desired-state
boolean inputs replace toggles in fixtures. Plugin-form Tab/Shift+Tab bindings
resolve before queued printable keys, preserving exact unpaced input and review.
See [compatibility acceptance](acceptance/plugin-compatibility.md).

## Owned plugin execution: U04 #59

`PluginSource` freezes a client/scope/UID/column selection before asynchronous
manifest loading. Reviews are bounded, one-use object identities. Explicit trust
is checked before preparation/lookup and again by the shared ProcessRunner; only
PLUGIN commands may carry the trusted-read-only classification. Preflight GET
verifies the selected UID without replaying an external write.

`PluginManager` owns up to four active groups and 32 job records. Per-job runners
keep cumulative capture limits; cancellation closes groups before staged files.
Background waiters cannot abandon ownership. Session replacement and application
exit drain preparation, readers, groups and private file cleanup before SDK close.
The form owns its preparation/capture waiter; background ownership transfers to
the manager. Foreground reuses the native terminal lease and restoration path.

Plugin cwd/environment are independent of credential helper identity. The private
stdlib-only credential child reads owned regular mode-0600 bounded JSON, rejects
links/foreign owners and executes absolute captured argv/cwd/environment. Only
client-go supplied KUBERNETES_EXEC_INFO crosses from the caller. Source uses its
installed interpreter with -I; frozen entry dispatch occurs before UI/CLI import.
Secrets stay in private files rather than launcher arguments. Captured output is
masked/escaped in an owned worker; foreground local output goes directly to TTY.
See [execution evidence](acceptance/plugin-execution.md).

## Bounded native CSS parse reuse: prerequisite for U03 #58

Required Python 3.13 run 39096419046 measured a 152.010-ms runtime heartbeat
while changing themes. A genuine generation-two collection occupied 97.881 ms
inside native CSS parsing; total main-thread CPU was 149.939 ms. The pinned
framework reparses every source in a new stylesheet even when returning to an
already used variable snapshot. This is a retained failed original, not a pass.

The app-owned ComponentStylesheet now keeps three exact, complete variable
snapshots, each with the native 64-entry source parse cache. Source content,
location, default status, priority and scope remain native keys. Reparse still
uses a fresh transactional stylesheet, publishes only after successful parsing
and preserves invalid-CSS error propagation. Copies/apps have separate caches;
rule data carries no widget reference. No global Textual patch, GC change,
budget increase, dataset reduction or unchanged retry is introduced.
Native-control tests compare rules, variable changes, error recovery, source
replacement/removal, bounds and independent ownership. Existing focus/theme/
component/remount controls remain required; fresh full hosted/native checks must
qualify the changed source. See [measured evidence](acceptance/plugin-contract.md).

## Explicit plugin definitions and capture: U03 #58

`config/plugins.py` parses independently versioned global/context layers without
filesystem discovery. `adapters/plugin_files.py` reads only configured bounded
regular YAML files, with no recursive locations, ambient current-directory search
or cluster registration. Context definitions replace complete global definitions;
within-layer name collisions fail. Shortcut validation evaluates each declared
resource scope against effective navigation and fixed safety keys.

Critical `domain/plugins.py` owns immutable definitions, typed inputs, scope,
read-only classification and one-pass literal variable expansion. Captured
session/resource/columns and input values form one argv/environment request;
substituted values never become templates or shell syntax. Cancellation yields
no request. This contract checkpoint is wired into offline config validation;
interactive review/execution/process ownership remain U04 #59.
Explicit preference migration rebases configured files and every inline working
directory against the original source without reading plugin files or executing
commands. It preserves trust roots and refuses invalid schema before a new write.

## Per-owner navigation and captured views: U02 #57

The additive navigation extension owns an independent schema version, immutable
key/alias/view models and pure applicability validation. Public Textual Binding
IDs and `App.set_keymap` apply validated keys to the focused owner; native
fallbacks remain independent bindings and ordinary input handlers own letters.
Aliases expand literal command text before the shared access policy, without
shell parsing, and discovered-name collisions retain an explicit resource path.

The UI view controller retains a bounded context/GVR cache of display preferences,
never clients or resource values. Server-printer views use a separate `server:`
namespace and ordered header fingerprint. Captured scope/schema checks reject
late edits. Tables project selected display cells from complete typed row models;
column revisions invalidate older yielded row patches and viewport callbacks.
Saves use the original ConfigDocument and owned file workers, preserving unrelated
extensions and runtime override separation. Metadata reload ownership is distinct
from value-disclosure navigation generations, so scrolling cannot discard a
valid reload or permit a late reveal.

## Appearance and optional release reads: U01 #56

Preference schema v1 recognizes an additive raw `appearance` extension without
mixing it into effective runtime Settings or diagnostic values. A pure bounded
model validates palettes, contrast and context references; UI conversion uses
Textual's public Theme API. Invalid appearance data leaves the file intact and
uses working defaults; the strict config check explains errors. Explicit saves
use the original document rather than CLI/environment settings, reject competing
content/legacy-path writes and run through owned file workers. Preview/cancel
and session RGB inversion do not write preferences.

The opt-in release service owns an unauthenticated, proxy-independent public
HTTP session, a three-second/64-KiB request and a private bounded atomic cache.
Pure PEP 440 decisions reject malformed, nonstable and foreign-URL records.
Cleanup drains repeated cancellation before HTTP closure; disabled checks create
no request. The App owns its task, checks mounted child ownership before updates,
and exposes verified/cached results in About without downloading executable code.

## Deliberate configuration disclosure: M05 #55

`domain/configuration_data.py` validates bounded text/Base64 payloads and produces
immutable key metadata without retaining values. A captured per-context service
performs a fresh GET for each disclosure, checks UID and resourceVersion and
revalidates scope after its owned parser. The Textual screen owns and drains its
reads before client closure; key/encoding/scope changes invalidate late results
and clear displayed values. Explicit disclosure bypasses ordinary value redaction
only in this dedicated screen; terminal controls remain escaped. SVG exports are
blocked while it is mounted. Trusted editor disclosure retains the common private
draft, conditional identity/version patch, strict dry-run and separate Apply.
No raw payload enters a public mutation receipt or the key index.

## Owned CrashLoop status synchronization: Refs #89

The aggregate owned-kind fixture explicitly uses a one-second kubelet
`syncFrequency` alongside its existing twenty-second restart cap. The default
one-minute synchronization period can publish a genuine waiting snapshot near
the next restart; observing that snapshot does not reserve its log availability.
This is an owned test-node setting, not a client retry or a production-cluster
change. Both options remain absent by default in the shared cluster owner, and
their configured values are read back from the verified owned node before use.
See [KubeletConfiguration](https://kubernetes.io/docs/reference/config-api/kubelet-config.v1beta1/).

The actual required-check failure retained one ended previous-log line without
the expected synthetic output. The revised fixture retains the existing genuine
LIST/UID/last-instance assertions, first-output and one-line checks, no replay,
120-second scenario deadlines and owned cleanup. Faster owned status publication
does not manufacture API records or log responses. Evidence and limitations are
recorded in [first-channel acceptance](acceptance/first-channel-activation.md).

## Shell controls during teardown: D06 #51

The shell owns its footer widgets directly. Before updating them for arriving PTY
output, it checks their public `is_attached` state. Textual can remove children
before the screen's Unmount handler cancels its owned session; `is_mounted` alone
does not establish current DOM attachment in the pinned implementation. The
PTY owner still cancels, drains and clears its endpoint/history normally. Real
PTY regressions reproduce this children-before-parent interval independently
for the toolbar and each control. See
[Textual MessagePump](https://textual.textualize.io/api/message_pump/#textual.message_pump.MessagePump.is_attached).

## Widget rendering-cache ownership: Refs D05 #49 / D04 #40

KubeRich substitutes a native StylesCache subclass only when its own App
registers a widget, after normal registration validation and before first paint.
The bounded background-style memoization uses immutable colors as keys, retaining
native alpha composition without retaining renderer instances and their lines.
This addresses the instance-key retention described in
[Textual #6665](https://github.com/Textualize/textual/issues/6665). It does not
patch Textual globally or change GC policy. The pinned private registration
boundary is covered by native-control ownership, theme/resize/color and
before/after remount regressions; dependency upgrades must retain that behavior.
This removes an avoidable retained heap root. Complete runtime and native checks
are still required; it does not alone prove the original heartbeat failure fixed.

The application also owns a scoped stylesheet that reuses each widget's virtual
component nodes. Native CSS evaluation recreates these cyclic DOM graphs during
focus and theme changes. Reuse bounds that allocation to the live components;
selectors are still evaluated by Textual, previous base/inline rules are reset,
and changed styles still refresh their widget. Stylesheet copies preserve this
behavior during CSS reload. Native comparisons cover focus, themes, resize,
inline changes and removed declarations. Textual is pinned to the qualified
8.2.8 release because these adaptations depend on private framework boundaries;
upgrades require the same behavior and runtime checks. GC remains enabled with
the interpreter's default thresholds; no global stylesheet or cache is patched.

## Frozen runtime and external processes: Refs D05 #49

The frozen entry dispatches its reserved PTY child before importing the CLI/UI.
The ordinary source/wheel path retains the isolated stdlib launcher; a frozen
application re-executes its own binary, then claims the child controlling terminal
and replaces that child with the captured absolute executable and literal argv.
It does not rely on an external Python interpreter for this launcher.

The internal frozen child inherits its application's loader state until it has
started. Only the subsequent external command receives a copied environment with
the application's library paths removed and the original Linux library path
restored where PyInstaller injected its bundle. Explicit external overrides and
paths outside the bundle remain captured. External credential helpers, executable
discovery and managed subprocesses use the same boundary; the application and
session environments are never rewritten globally. Runtime decisions join the
100% critical-module coverage policy. Actual frozen artifact and clean-target
qualification belong to D05; source tests alone do not qualify a binary.

## Incremental log geometry and fixed-height status: Refs Q03 #50

LogBody retains at most two published wrap geometries for the current width,
timestamp mode, literal query and marks. An update reuses only an exactly equal
overlapping entry prefix, rebases its starts after eviction and appends new
layouts in the existing cooperative turns. Both geometry forms and line caches
are pruned to current retained identities. Search matches belong to the reused
prefix itself; reordered histories cannot keep matches from rows prepared later.
Context changes and invalidation discard geometry. Published arrays are copied
before an update, and generation checks still prevent obsolete publication.

A cancelled first wrap can leave a partially warmed line cache. Returning to
unwrapped history prepares missing previously requested wrapped layouts before
that history may use the prefix fast path. Rich-reference tests cover both entry
forms, append/eviction, gaps, reorder, query/mark/timestamp changes, resize and
generation/task cancellation.

Log titles and status labels have fixed one-row CSS geometry. Their native
Static updates use `layout=False`, so changing counters does not relayout the
covered workspace. Unchanged title/frame content is not refreshed. Native
terminal resize and log virtual-size changes retain their layout behavior.
The first unprofiled short observation measured 91.190 ms p95. A subsequent
frozen 30-minute observation measured 99.077 ms p95 across 6,533 public painted
controls; independent review verified the predeclared memory plateau and all
163 original Git inputs. The 0.923-ms margin belongs to the recorded reference
machine, not every machine or every input. Full native and context-churn,
slow-consumer/cancelled-forward qualification remain required. The complete
owned log UI cohort passed 36 cases; the exact workflow lint/format and strict
types passed over 492 files and 133 source files respectively. See the
[original sustained evidence](acceptance/combined-workload-progress.md#frozen-incremental-candidate-sustained-observation).

## Owned CrashLoop qualification observation: Refs Q03 #50

The working correction selects one complete genuine LIST response in which the
exact owned UID/name/namespace has CrashLoopBackOff and a terminated instance.
It returns the response's records and resource version unchanged to the normal
aggregate membership pipeline. Later LIST/WATCH calls and every log request
remain ordinary real-cluster requests. This is an explicit fixture control at
the membership observation boundary; its receipt labels it. It does not claim
the server stays waiting through later requests. The first last-instance
assertion, one-line output, no-replay and cleanup checks remain enforced.
The selector owns a 120-second deadline; denial, cancellation or missing
membership fails instead of manufacturing a snapshot. All 11 new local real-kind
scenarios and 81 focused contracts passed; frozen native checks remain required.

Subsequent real-kind evidence invalidated the assumption that a fresh waiting
observation establishes a usable remaining backoff window. One owned 120-second
diagnostic observed waiting-to-running at restart count three within about
117 ms. The `321e9ca` required native candidate and two later local fixture
revisions remain unqualified. The original setup below is retained as the
attempt being corrected; production logs and replay contracts are unchanged.

The actual-kind scenario observes a terminated container then its same identity
in CrashLoopBackOff, admitting within three monotonic seconds of that transition
after at least three restarts. Status receipt time avoids assuming `finishedAt`
is published immediately. Current/previous output and initial last-instance
assertions, scenario deadline and cleanup remain unchanged. This changes only
owned test setup, not production admission, restart handling or replay semantics.
See [qualification evidence](acceptance/owned-crashloop-window.md).

## Bounded formatting and collected parser outcomes: Refs Q03 #50

Aggregate view/export formatting captures immutable records, mode, timestamps
and the exact source filter before awaiting. Each owned worker formats at most
32 records and 8 KiB of reserved output; one larger retained record gets its own
turn without splitting or dropping it. Turns run sequentially, preserving arrival
order and allowing the event loop to run between them. Layout generation and
export target checks still reject obsolete results. No formatting queue is added.

JSON and domain parser owners shield a collector created with
`gather(return_exceptions=True)`, drain it through repeated caller cancellation,
and then return the task's original result or exception when uncancelled. This
keeps Python 3.14's late shield error callback from reporting an error that the
owner deliberately consumes during cancellation. See
[measured limits and original failures](acceptance/owned-log-formatting.md).

## Single owned watch parser: Refs Q03 #50

The session exposes bounded complete raw watch frames through `watch_bytes`;
`watch_json` remains a decoded compatibility consumer of that same transport.
ListWatch decodes JSON and normalizes the event in one `parse_owned` worker,
instead of transferring each event between two workers. The public shared JSON
decoder retains object/nonfinite validation for reads and write receipts.
The consumer still pulls one event at a time, so a slow sink cannot start a
background parse queue. Table negotiation/fallback, opaque checkpoints, retries,
scope validation and generation guards stay with their existing owners.
Both combined and compatibility JSON workers drain through repeated cancellation;
HTTP ownership closes only after parsing has finished. See
[watch pipeline evidence](acceptance/watch-pipeline-performance.md).

## Owned workspace repaint: Refs Q03 #50

WorkspaceLabel projects all public rendering attributes of exact strings/Rich
Text and compares current content to its bounded last projection. Its explicit
owned update method leaves the native update/property contract intact. Resource
tables distinguish reused immutable rows from merely equal values. Pod/standard
tables opt into native public row-region repaint only for immutable header-bound
edits without fixed cells; FrameTable defaults to full native repaint. The
temporary public refresh guard resets in finally and never changes native
geometry/cache counters. Unknown renderables and layout/width changes retain
native behavior. See [acceptance limits](acceptance/live-render-performance.md).

## Phased immutable release decisions: Refs #89

Release readiness validates the entire reviewed task graph and canonical issue
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
S08 #62 extends this controller with named ports, locally authorized annotation
presets, child transport selection and bounded reconnects. Loopback remains the
default; remote binds require separate opt-in. See [port forwarding](port-forwards.md).

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

Development CI policy #109 uses a standard-library event/ref planner outside the
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
and closes its generator on cancellation/failure. An immediately completing
consumer receives at most 32 lines before an explicit cooperative turn, so pending
input, cancellation and other readers are not deferred through an entire 8-KiB
chunk. Every subsequent line rechecks the current captured target. Delivery stays
sequential without a producer queue or dropping lines. Logs have no watch checkpoints
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
500 lines/256 KiB and aggregate history at 10,000 lines/4 MiB, accounting for both
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

For #123, `domain/terminal_history.py` owns immutable rows, the 1,000-row ring
and a bounded frozen local review with literal search, row selection and redacted
64-KiB copy decisions. Only full-viewport upward scrolling and rows displaced by
normal-screen shrink enter history; alternate screens and partial scroll regions
remain independent. The Pyte adapter converts cells through a session-owned,
1,024-entry bounded value cache. No cache retains an application/widget globally.
Review references one immutable capture, never accumulating incoming output.
The real PTY continues feeding the live emulator, receiving resizes and answering
cursor reports. ShellScreen intercepts keys/paste locally only during deliberate
review; return restores the latest active normal/alternate screen. Explicit copy
revalidates the captured target and uses the application clipboard; remote OSC52
stays discarded. Session close/cancellation releases history, capture and cache.

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

## Terminal interactions and captured read workspaces

B07 #61 keeps bounded command/filter entry and UID ranges in
`domain/interactions.py`, local metadata/known-health decisions in
`domain/selectors.py`, and write-only backend/OSC52 decisions in
`domain/clipboard.py`. `services/metadata_filtering.py` owns its decoding worker,
separate metadata budget and one-snapshot cache. Cache hits reuse match identity,
not stale cell projections after a column change. `ui/interactions.py` coordinates
session preferences and marks without moving Kubernetes operations into widgets.

`ProcessCommand.input_data` is immutable, bounded and restricted to noninteractive
clipboard-purpose commands. `ProcessRunner` registers ownership before writing
stdin. Native clipboard data never enters argv/code/logs; X11 retains one owned
foreground selection process, macOS uses a constant AppKit plaintext program,
and OSC52/tmux emit only bounded base64 in trusted framing. No production backend
reads a clipboard. Headless runs stay memory-only and ordinary PTYs force OSC52.

Read-only `CommandWorkspace` screens share the command provider/history. Invalid
or forbidden commands retain the view; accepted scope transitions await covered
read owners before dispatch. Resource commands revalidate the originating target
and restore that UID rather than using a changed hidden cursor. The embedded
shell's earlier event route remains authoritative for remote keystrokes.

A container screen coalesces owned Pod-record projections independently of the
covered root renderer, preserves container name/viewport and never steals focus.
UID/session/namespace/context/fatal-permission invalidation is sticky. Closing
clients drains inspection, log, container projection and shell owners in addition
to existing mutation/plugin/forward work. Preference writes serialize and reject
an intervening document, retaining unrelated extensions instead of losing a save.
