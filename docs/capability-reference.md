# Feature availability

Generated from the maintained feature inventory for source version `SOURCE_VERSION`.

Available describes implemented behavior within its stated limits. Partial means
only the described portion is usable. Planned features are unavailable.
Real cloud accounts, terminals, and provider policies can need additional setup.

## Current inventory

### All 26 explicitly registered launch flags; help/version/info and completion
**partial** — Launch flags provide help, version, local diagnostics, read-only policy, presentation
controls, session color inversion, startup views and connection overrides. Version 0.4 adds an
export-directory option and local artifact browser startup. Splash and shell completion are
unavailable. Create redacted diagnostic bundles and retry recoverable resource-view errors.
### Context/kubeconfig/cluster/user/namespace selection and connection overrides
**partial** — Select kubeconfig files, context, namespace, connection overrides, and user settings
explicitly. Each context uses its own connection and passes that identity to delegated tools.
### AWS EKS, Azure AKS, GKE and generic exec/OIDC/cert/token credentials
**partial** — Exec bearer/certificate helpers, token files and explicit native helper login are
available. Local provider-shaped tests do not certify real cloud accounts or identity providers.
Legacy auth-provider/basic entries require migration.
### TLS/CA/client certificates, proxy, request timeout and impersonation
**partial** — CA and client certificates, TLS names, timeouts, proxy settings and repeated
impersonation are supported. Version 0.4 adds current-identity permission reviews and observed RBAC
browsing; SOCKS5 streaming limits remain explicit.
### Context rename/delete and persisted per-context view/namespace preferences
**partial** — Selecting a context leaves kubeconfig unchanged. Renaming or deleting a context uses
explicit review and a backup. Local per-context display preferences can be saved.
### API discovery, resource aliases and dynamic/CRD server columns
**partial** — Discovery and generic browsing remain available. Version 0.4 adds 18 curated read-only
families and an identity-safe Events workspace.
### Live resource updates, manual refresh, retry/reconnect and errors
**partial** — Live lists and watches keep a last snapshot during temporary failures and reconnect or
relist as needed. Refresh renews discovery and the selected resource stream. A stale snapshot does
not establish current server state.
### Resource command mode, aliases, autocomplete, namespace/context arguments
**partial** — Nested resource, container, and log views share inline command bars. Invalid commands
keep the current view; scope changes close old reads before switching. Actions keep the selected
resource identity.
### Regex/inverse/fuzzy filtering, label/field selectors and filter history
**partial** — Local filters support literal text, regular expressions, inverse regex, fuzzy
subsequences, and supported label/field terms. Queries have size and time limits. Command and filter
recall lasts for this session.
### Breadcrumbs, back/forward/last-command navigation, namespace favorites
**partial** — Commands and filters have separate histories with unfinished-draft restoration.
Repeating a command uses its normal checks. Namespace favorites can be saved per context; view
history stays memory-only.
### Keyboard/mouse, horizontal/vertical scrolling, paging, resize and Unicode
**partial** — Text/help and log navigation have independent key profiles. Mouse reporting requires
opt-in. Container state refreshes from the pod watch while preserving selection. Clipboard behavior
depends on the outer terminal.
### Typed sorting, movable/custom/wide columns, errors-only and selection ranges
**partial** — Wide mode adds available columns. Error filtering distinguishes known failures from
unknown health. Up to 100 resource UIDs can be marked for a separate batch review.
### Help, key hints, header/logo/breadcrumb visibility, fullscreen and quit behavior
**partial** — Inspection and help share the workspace frame. Session controls hide headers, trails,
or frame borders without saving preferences. Escape and navigation depend on the focused view.
### YAML/describe/details, managedFields toggle, text search and auto-refresh
**partial** — Selected resources provide details, redacted YAML, and related events with local
search. Inspection is a read snapshot; reopen it to refresh.
### Copy resource/namespace/text with native clipboard and OSC52 over SSH/tmux
**partial** — Explicit copy uses local macOS native text, Wayland wl-copy, X Window System xclip, or
terminal OSC52 with tmux framing. Wayland takes precedence locally; automatic SSH mode selects
OSC52. Native text accepts up to 1 MiB and terminal copy 64 KiB. Text stays on stdin for native
helpers. A sent request does not prove a compositor or outer terminal accepted it.
### Save resources/logs, screen-dump browser and export path settings
**partial** — Version 0.4 adds reviewed redacted resource, log, diagnostic, screen and support
exports, an explicit directory option and a local saved-artifact browser. Sensitive resource YAML
and overwrite/deletion need separate confirmation.
### About/branding and optional update notification
**partial** — About shows the installed version and license. Stable-release notices are opt-in and
can use a cached result; they never install an update.
### Pods/containers including init and ephemeral containers, events and namespaces
**partial** — Browse live Pods, containers and namespaces. Version 0.4 adds Events warning
filtering, occurrence groups and individual member inspection.
### Deployments, StatefulSets, DaemonSets, ReplicaSets, replication controllers, workloads
**partial** — Standard workload tables support reviewed scaling, restart and explicit revision
rollback. Version 0.4 adds native controller and Pod relationships; selector matches remain separate
from ownership.
### Services, Endpoints, EndpointSlices, Ingresses and NetworkPolicies
**partial** — Service and Ingress tables are available. Version 0.4 adds curated EndpointSlice,
NetworkPolicy and IngressClass tables and reported service backends with separate selector matches,
preserving unknown endpoint identity and incomplete reads. Development source clarifies peer
selectors and rule scope without testing network enforcement.
### Nodes, PV/PVC, StorageClasses, priority/scheduling, HPA/PDB/quota/limits
**partial** — Node, PV, PVC and StorageClass tables are available. Version 0.4 adds curated HPA/VPA,
PDB, scheduling-class, quota and limit tables, Node CPU/memory usage, allocatable percentages and
vendor-neutral extended-resource capacity. The cluster overview adds known pressure/unscheduled
states; broader quota/disruption diagnostics remain planned. Relationships distinguish declared
placement, PV/PVC bindings and static PriorityClass references. Development source separates
scheduling declarations and generation-qualified scaling observations from placement or enforcement
outcomes.
### ConfigMaps, Secrets, service accounts and RBAC resource families
**partial** — ConfigMap/Secret payload views remain deliberate. Version 0.4 adds read-only
ServiceAccount and RBAC summaries with declared links and authorization evidence.
### Custom resources, unknown APIs and custom columns/jump chains
**partial** — Discovered APIs provide served-version selection, typed printer columns, inspection
and saved schema-pinned layouts. Version 0.4 follows discovered owners in native graphs; configured
jumps share navigation history. Generic mutation and arbitrary custom-resource reference scanning
remain unavailable.
### Current/previous logs, container selection and all-container/workload logs
**available** — Read current or previous container output and aggregate supported workload logs.
Readers follow controller membership and identify each source independently.
### Head/tail/time windows, timestamps, wrap, follow/pause and column lock
**available** — Logs support head, tail, and time windows, timestamps, wrapping, pause, and
independent viewport following. History has line and byte limits; rotated server output may be
unavailable.
### Log search, marks, copy, save, and history limits
**partial** — Search, filters, marks, clear, fullscreen and explicit redacted copy work on bounded
retained output. Version 0.4 adds reviewed log saving and saved-artifact browsing; its frozen source
keeps actual container/window provenance and discard notices.
### Shell exec with chosen container and configurable shell command
**partial** — A selected container opens an embedded kubectl shell with local history, search, and
copy. Write mode, kubectl, and exec permission are required. Advanced terminal protocols are
unsupported.
### Attach to running containers and bidirectional file transfer
**partial** — Attach to supported running containers and review bidirectional file/tree transfers.
Uploads and attach require write mode; downloads use explicit local destinations and guarded
extraction. Interrupted uploads can leave remote files.
### Pod/container/service port forwarding, listing, deletion and bind address
**partial** — Manage Pod and Service TCP forwards with explicit bind addresses, readiness, listing,
and Stop. Context changes and exit close local sessions. Other terminals' forwards are not
discovered.
### FastForward annotations, named ports, multiple presets and WebSocket transport
**partial** — TCP mappings support declared names and container qualification, local presets,
explicit annotation shortcuts, transport selection, and up to three reconnect attempts.
### Read-only mode, permissions, target validation and dangerous-action gates
**partial** — Read-only policy, selected target identity, permission checks, and one-use
confirmations guard changes. Kubernetes RBAC and admission remain authoritative; application read-
only mode is not a sandbox.
### Edit manifests with external editor and conflict/diff validation
**partial** — Edit supported manifests using a trusted editor after explicit local disclosure, then
inspect a redacted diff, validate with a strict server dry-run, and choose Apply separately. This
includes deliberate Secret editing.
### Scale, restart and rollback workloads; deployment ReplicaSet drill-down
**partial** — Review scale, restart or one explicit available revision rollback for supported
controllers. Version 0.4 adds owner/ReplicaSet navigation; open an ordinary resource view before
changing a resource.
### Delete/force-delete/bulk actions and pod completed/error cleanup
**available** — Single/batch deletion reviews identity, grace and propagation, then reports each
result separately. It never silently removes finalizers. :cleanup reviews deleting the completed and
failed pods in the current view.
### Trigger/suspend jobs and CronJobs
**available** — Review Job/CronJob suspension and resume, or create an independent manual Job from
the selected CronJob template. The schedule and concurrency policy do not govern a manual run.
### Configuration data and environment sources
**partial** — ConfigMap and Secret keys have explicit reveal/copy and editing. Version 0.4 also
traces container environment sources and image facts; values require fresh disclosure.
### Local manifests, reviewed apply/delete, Kustomize and create-only resource templates
**partial** — Development source for 0.5 adds local manifests/Kustomize and separate create-only
templates, file or explicit clipboard imports, with strict server review and per-resource outcomes.
Published 0.4.0 predates these workflows.
### Helm list/status/notes/values/all-values/manifest/history
**partial** — Development source for 0.5 adds Helm release browsing and a private
classic/registered-OCI chart catalog with exact version selection. Public 0.4.0 predates these
controls; final development qualification remains in progress.
### Helm rollback and uninstall with history options
**partial** — Development source for 0.5 adds reviewed Helm install, upgrade, rollback and uninstall
with private values, dry-run/live comparison and explicit history choices. Final qualification is
pending; published 0.4.0 predates Helm management.
### Global/per-context themes, transparent colors, light/dark inversion, icon settings
**partial** — Themes support global/context palettes, terminal-default background, preview, explicit
save, live reload, and session inversion. Icon preferences are unavailable.
### Aliases, hotkeys, columns, alignment/width/order, context/resource view overrides
**partial** — Configure additional navigation keys, literal aliases, and global/context resource
columns and sort. Inputs keep normal text editing; invalid overrides leave working defaults.
### Custom GVR relationship jumps with selectors/templates/namespace
**partial** — Define preference-file jumps and use :jump to open related views with a local filter.
Version 0.4 adds native discovered-owner graphs using the same history; arbitrary custom-resource
reference discovery is unavailable.
### Reactive settings reload, paths, feature gates, connection/log/metric thresholds
**partial** — Valid saved preferences reload while the application runs; an invalid file leaves the
last working settings active. Contexts can add read-only mode or a refresh interval.
Connection/log/metric threshold controls are unavailable.
### Plugin search paths, scopes, shortcut overrides, confirmation and dangerous flag
**partial** — Load explicitly configured local plugin definitions with context/resource scopes and
optional shortcuts. Typed review defaults to Cancel; Run is separate. No automatic plugin
installation occurs.
### Plugin environment/column/resource expansion and foreground/background execution
**partial** — Plugins receive literal arguments and environment in capture, background, or native
foreground mode, using a private per-context connection. K9s plugin YAML is not a drop-in format.
### Typed plugin inputs, defaults, validation, cancellation and output options
**partial** — Plugins provide typed input, defaults, choices, one-use review, cancellation, size-
limited sanitized output, result states, and job Stop. Foreground output goes directly to the native
terminal.
### Every bundled community plugin workflow and external-tool dependency
**partial** — Translate plugin fields and variables explicitly and install required external tools
separately. External services and tool features do not become native application capabilities.
### CPU/memory usage, requests/limits/percentages, extended/GPU resources
**partial** — Version 0.4 adds current CPU/memory usage, declared budgets and Node/extended-resource
capacity. Configured entity history includes CPU, memory, network and filesystem source states;
missing sources and uncertain historical identity remain explicit. GPU utilization is unavailable.
### Pulse cluster overview and CPU/memory drill-downs
**partial** — Version 0.4 adds cluster health and capacity summaries with resource drill-downs.
Shift+M or :history opens configured entity history with numeric charts, 15m–24h ranges, separate
devices, explicit source gaps and historical-identity limits. Backend components must already exist.
### XRay relationships, jump-to-owner/node, service endpoints and UsedBy
**partial** — Version 0.4 provides native :xray and :usedby views for owners, selector matches,
reported endpoints, placement and supported static configuration/storage/identity declarations.
Replacement UIDs and incomplete scans remain explicit.
### RBAC can/user/group/service-account policies and rule inspection
**partial** — Version 0.4 includes role and subject browsing, namespace rules, current-identity
access reviews and RBAC who-can evidence. Partial reads, unknown group membership and external-
authorizer limits remain visible.
### Popeye/cluster diagnostic reports and actionable failure evidence
**partial** — Version 0.4 adds native :diagnostics and captured-workload :diagnose evidence, plus
explicit optional :popeye report ingestion. Source gaps, stale evidence and name-only report
identity remain visible.
### Opt-in image vulnerability scans, severity/package/fix views and advisory links
**planned** — Opt-in image vulnerability scanning and advisory/package/fix views are planned.
### Node shell helper pods, configurable image/namespace/limits/host mounts
**partial** — Development source for 0.5 adds explicitly configured Linux node diagnostic shells
with privilege review, bounded sessions, cleanup by Pod UID and local recovery. Published 0.4.0
predates this action.
### Cordon/uncordon/drain, disruption constraints and explicit overrides
**partial** — Development source for 0.5 adds selected-Node cordon, disruption-aware drain and
separate uncordon with explicit consents and final scheduling observations. Published 0.4.0 predates
these actions.
### Ephemeral debug containers and diagnostic sessions
**partial** — Development work for 0.5 adds reviewed permanent debug-container additions and
separate session inspection/attachment. Published 0.4.0 predates this workflow; compatibility and
qualification limits remain explicit.
### HTTP benchmarks, per-context options, results browser and cancellation
**partial** — Development source adds short explicitly confirmed HTTP tests through one selected
backend, with an optional Vegeta program, conservative limits, cancellation and a private local
results browser. HTTP/1.1 only; whole-Service balancing and exact per-second traffic ceilings are
not claimed.
### Policy/quota/admission/scheduling views and removed-API handling
**partial** — Published 0.4 provides scaling, policy, scheduling, quota and webhook summaries.
Development source adds validating/mutating policy and binding exploration with declared matching
and current-name links. Configured policy and observed status do not prove enforcement; unavailable
APIs and unknown schemas remain explicit.
### Linux/macOS downloads, source installs and Homebrew
**partial** — Install from PyPI, the project Homebrew tap, or GitHub Release archives. Linux/macOS
and Python support depend on the selected channel and its documented platform requirements.
### Windows executables, PowerShell, Winget/Scoop/Chocolatey
**planned** — Windows executables and Windows package-manager channels are planned.
### Linux packages, snap, FreeBSD, MacPorts and community package managers
**planned** — Additional Linux/FreeBSD/MacPorts and community package-manager channels are planned.
### OCI terminal image and shell completion
**planned** — An OCI terminal image and shell completion are planned.
### Unreleased upstream fixes/configuration additions after v0.51.0
**planned** — Unreleased upstream changes are tracked separately from the pinned baseline. They do
not establish delivered KubeRich behavior.
