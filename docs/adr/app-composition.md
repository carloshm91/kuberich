# Application composition

Status: typed view rendering, commands, navigation, resource operations,
presentation, clipboard and appearance ownership are integrated. Final combined
release qualification remains pending. The remaining App size and private-access
inventory are explicit follow-up work under the approved 0.x delivery scope.

The application shell composes concrete owners through typed service, widget and
callback ports. Tests exercise public state/command boundaries throughout this
migration.

A typed route distinguishes the five view modes while retaining canonical API
selection separately from the existing navigation/display key. Route validation
checks shape; discovery remains authoritative for requested API versions. A
qualified custom resource never becomes a local contexts view or a built-in pod
view merely because its plural has the same spelling.

Each view adapter implements a generic `ViewController[T]`. `ViewDriver[T]` keeps
projection, filtering and guarded row application in one typed pipeline. Its
small non-generic `RenderPort` exposes counts, viewport operations and available
actions to the coordinator without erasing row values with `Any`. Concrete
adapters import on active selection, rather than loading every screen at startup.
Each projected batch carries an additional schema/snapshot guard. The driver
combines it with the live request guard before the table's chunked application;
no mutable last-layout field carries per-request state. Inactive projection
retirement remains an explicit coordinator responsibility.

The five adapters now project into the actual table widgets through narrow typed
ports. Resource filtering reuses the existing metadata service, including local
favorites and error-only policy. Custom rendering retains a bounded context/GVR
layout cache and tracks its decoder schema independently from the table schema;
a public table reconfiguration during an awaited filter invalidates the old
batch, and the next projection rebuilds the decoder even if the table already
has the new layout. `ViewRegistry` constructs an adapter only when selected.
`RenderCoordinator` owns one coalescing task, retires inactive decoded records,
and publishes only an applied result. Repeated cancellation of close cannot
abandon the actual render coroutine while its cleanup is still draining.

The root screen uses Textual's public `get_default_screen` customization point
and its actual suspend/resume lifecycle. Those events do not bubble to App.
An owned foreground gate replaces modal polling while watches continue publishing
and resume paints the latest observation. Guards still recheck during chunked
row application, and close drains the renderer and any owned decoding work.
The real App now uses this gate and the single typed render path. Explicit column
commands still own a fresh decoder, including `columns default`; injected public
projection factories retain their real held-worker and cancellation controls.

Existing command parsing and service access policy remain canonical. A pure
command catalog now declares aliases, semantic handler IDs, capabilities,
read-only classification and help. The parser consumes that catalog, and its
public imports and completion grammar remain compatible. Reserved unsupported
operations retain their fail-closed classification without being advertised;
named plugin execution still reaches manifest classification before preparation.
The App now binds every catalog command exactly once; bound handlers receive
the original scoped argument and recheck the shared policy before lookup. The
actual help and binding availability consume that same catalog. Nested
commands retain captured targets and their dismissal/history ordering. Narrow
operation/navigation ports replace cross-object private access; an App field
facade or class-splitting mixins would retain the original ownership problem.
The standalone resolved-command router sends interaction, named-plugin,
standard-resource and generic-resource variants directly to their typed owners.
Ordinary commands use the declared bound handler and generic-view refusal flag.
Command history, target revalidation and modal dismissal remain at the captured
nested-workspace transition boundary and require their existing regressions
during App integration. `WorkspaceCommands` now owns the actual root submission
and captured-workspace transition task, including cancellation/draining and
history publication after target revalidation. Its resolver is a callable so
reloaded aliases use the replacement command service rather than a startup
snapshot. Captured screens receive a frozen `NestedCommands` port containing suggestions,
the shared command history and the origin-aware route callback. Standalone
screen harnesses without that port retain their bar-free behavior.

`TargetCapture` consumes explicit view, client-identity and typed selection
observations rather than an App object. Its transport-generic captured value
retains the selected immutable record, canonical API resource and UID guard.
The guard always checks client, scope and generation, while caching both UID
presence and absence once per immutable snapshot. Local contexts and qualified
custom resources with the same plural remain distinct routes. No SDK import or
resource operation is required to capture or verify that identity.

`ResourceOperations` receives that capture port, explicit process/mutation/forward
owners and a frozen presentation/process snapshot. It uses the public Textual
host only to open or inspect screens and publish notices. The helper owns retained
aggregate viewers and annotation trust. Batch selection pruning still happens
after policy and the first valid target capture. Forward lifetime uses the real
client and connection ID, so namespace/view changes preserve a forward while
context replacement invalidates it. Local context editing remains outside this
resource-operation owner.

`services.ownership.finish_owned` is the shared public cleanup boundary. Its
existing cancellation/drain behavior is preserved, including retrieving a child
failure. UI components use that API; the former process-module name remains an
internal compatibility alias for existing service callers.

`WorkspaceNavigation` now owns context/namespace parent views, bounded history,
pending generic selection and viewport/schema restoration. Its explicit services,
table owner, widgets, policy and presentation callbacks replace those App state
fields. Initial navigation still runs synchronously after renderer/subscription
startup. WorkspaceService retains ownership of every queued connection/change;
the UI does not keep a second unused task reference.

`ClipboardQueue` owns the latest pending native write and asynchronous cleanup.
The App still assigns its inherited clipboard value and emits terminal sequences
through its real driver. Stopped or superseded writes cannot publish a stale
fallback. Repeated cancellation drains the writer before native closure without
exposing task handles to callers.

The separately scoped framework-compatibility work retains responsibility for
remaining pinned private framework imports/overrides and their removal conditions.
This decomposition does not claim their removal or establish a blanket lint waiver.
Offline CLI, readiness, runtime, coverage, public constructor/state/command
contracts, terminal geometry and existing scenarios retain their required gates.
First-frame timing follows the approved 0.x advisory policy; the original stable
release budget is retained for later qualification. No measured result is relabeled
as a strict-budget pass.

`python -m scripts.check_ui_boundaries` inventories private imports, attributes
and reflection into another KubeRich owner using the same alias/type provenance
as the test boundary check. Own-class internals and zero-argument `super()` stay
within the implementation. Framework namespaces retain their separately tracked
compatibility boundary. The new check currently reports the remaining legacy
App/component seams; its required CI step will be enabled only after those
owners have explicit public ports and the package reaches zero findings.

`WorkspacePresenter` owns observation delivery, current render capture, status,
empty-state messages, sort labels and breadcrumbs. Its public host/widget/service
ports retain generation, foreground and snapshot guards. The native terminal
input dispatcher owns forwarded-input completion and routes shells/plugins before
normal Textual dispatch. Actual error cleanup releases pending input.

Empty-state visibility now uses CSS row-presence classes alongside the existing
short-terminal rule. It no longer overwrites that rule with inline display
assignments during rendering or navigation. Unchanged compact/normal/wide goldens
and actual row/filter and small-to-large resize transitions verify the correction.
`AppearanceController` owns theme registration, previews, validated persistence,
context precedence and the optional release-check task. Preference reload adopts
validated themes through that owner. Public App appearance/update observations
remain available; exit stops queued checks synchronously and closure drains the
actual task through repeated cancellation.

The final appearance checkpoint passes 241 disjoint functional cases on frozen
inputs, including 30 actual startup PTYs, resource identity/history, generated
help, theme persistence, preference reload, optional updates and cleanup. The
previous input/presenter checkpoint also retained all unchanged terminal layout
goldens and actual populated/empty resize transitions. Full combined coverage,
runtime and platform qualification remain separate required evidence. App is
1,243 lines; neither its original 800-line target nor zero cross-owner private
access is claimed. Those remaining targets are deferred rather than relaxed by
changing lint or coverage behavior.

The legacy cross-owner inventory remains concentrated in interaction controls,
plugin/jump/view-preference adapters, live settings and screen error reporting.
The optional UI ownership checker reproduces it and intentionally exits nonzero
until that stable-release work is finished. Pinned Textual compatibility work
includes native style-cache/registration and sanitized exception hooks; preserving
their tested behavior does not certify their removal or a framework upgrade.
