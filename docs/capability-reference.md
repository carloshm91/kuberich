# Feature availability

Generated from the maintained feature inventory for source version `SOURCE_VERSION`.

Available describes implemented behavior within its stated limits. Partial means
only the described portion is usable. Planned features are unavailable.
Real cloud accounts, terminals, and provider policies can need additional setup.

## Current inventory

### All 26 explicitly registered launch flags; help/version/info and completion
**partial** — Launch flags provide help, version, local diagnostics, read-only policy, presentation
controls, session color inversion, startup views and connection overrides. Development source adds
an export-directory option and local artifact browser startup. Splash and shell completion are
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
impersonation are supported. Development source adds current-identity permission reviews and
observed RBAC browsing; SOCKS5 streaming limits remain explicit.
### Context rename/delete and persisted per-context view/namespace preferences
**partial** — Selecting a context leaves kubeconfig unchanged. Renaming or deleting a context uses
explicit review and a backup. Local per-context display preferences can be saved.
### API discovery, resource aliases and dynamic/CRD server columns
**partial** — Discovery chooses served API versions and unambiguous aliases. Generic tables provide
server columns, metadata fallback and saved layouts. Development source follows discovered owners;
generic mutations and arbitrary custom-resource reference scanning remain unavailable.
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
**partial** — Development source adds reviewed redacted resource, log, diagnostic, screen and
support exports, an explicit directory option and a local saved-artifact browser. Sensitive resource
YAML and overwrite/deletion need separate confirmation. Installed 0.3.0 predates the browser.
### About/branding and optional update notification
**partial** — About shows the installed version and license. Stable-release notices are opt-in and
can use a cached result; they never install an update.
### Pods/containers including init and ephemeral containers, events and namespaces
**partial** — Pods and namespaces have live tables. Pod Enter opens regular, init, sidecar, and
existing ephemeral container rows. State updates from the pod watch; Enter on a container opens its
logs.
### Deployments, StatefulSets, DaemonSets, ReplicaSets, replication controllers, workloads
**partial** — Standard workload tables support reviewed scaling, restart and explicit revision
rollback. Development source adds native controller and Pod relationships; selector matches remain
separate from ownership.
### Services, Endpoints, EndpointSlices, Ingresses and NetworkPolicies
**partial** — Service, EndpointSlice, Ingress and NetworkPolicy views are available. Development
source adds reported service backends and separate selector matches, preserving unknown endpoint
identity and incomplete reads.
### Nodes, PV/PVC, StorageClasses, priority/scheduling, HPA/PDB/quota/limits
**partial** — Node, PV, PVC, StorageClass and HPA tables are available. Development source adds Node
CPU/memory usage, allocatable percentages and vendor-neutral extended-resource capacity; the
development cluster overview adds known pressure/unscheduled states, while broader quota/disruption
diagnostics remain planned. Development relationships distinguish declared placement, PV/PVC
bindings and static PriorityClass references.
### ConfigMaps, Secrets, service accounts and RBAC resource families
**partial** — ConfigMap and Secret values stay hidden until deliberate reveal or copy. Development
source includes static configuration/ServiceAccount relationships, observed RBAC browsing and
current-identity permission reviews with explicit scope and uncertainty.
### Custom resources, unknown APIs and custom columns/jump chains
**partial** — Discovered APIs provide served-version selection, typed printer columns, inspection
and saved schema-pinned layouts. Development source follows discovered owners in native graphs;
configured jumps share navigation history. Generic mutation and arbitrary custom-resource reference
scanning remain unavailable.
### Current/previous logs, container selection and all-container/workload logs
**available** — Read current or previous container output and aggregate supported workload logs.
Readers follow controller membership and identify each source independently.
### Head/tail/time windows, timestamps, wrap, follow/pause and column lock
**available** — Logs support head, tail, and time windows, timestamps, wrapping, pause, and
independent viewport following. History has line and byte limits; rotated server output may be
unavailable.
### Log search, marks, copy, save, and history limits
**partial** — Search, filters, marks, clear, fullscreen and explicit redacted copy work on bounded
retained output. Development source adds reviewed log saving and saved-artifact browsing; its frozen
source keeps actual container/window provenance and discard notices.
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
controllers. Development source adds owner/ReplicaSet navigation; open an ordinary resource view
before changing a resource.
### Delete/force-delete/bulk actions and pod completed/error cleanup
**available** — Single/batch deletion reviews identity, grace and propagation, then reports each
result separately. It never silently removes finalizers. :cleanup reviews deleting the completed and
failed pods in the current view.
### Trigger/suspend jobs and CronJobs
**available** — Review Job/CronJob suspension and resume, or create an independent manual Job from
the selected CronJob template. The schedule and concurrency policy do not govern a manual run.
### Configuration data and environment sources
**partial** — ConfigMap and Secret keys have explicit reveal/copy and editing. Development source
also traces container environment sources and image facts; values require fresh disclosure.
### Local manifest directories, YAML edit, apply/delete and Kustomize
**planned** — Local manifest directories, apply/delete workflows and Kustomize integration are
planned.
### Helm list/status/notes/values/all-values/manifest/history
**planned** — Helm release browsing, status, notes, values, manifests and history are planned.
### Helm rollback and uninstall with history options
**planned** — Helm rollback and uninstall workflows are planned.
### Global/per-context themes, transparent colors, light/dark inversion, icon settings
**partial** — Themes support global/context palettes, terminal-default background, preview, explicit
save, live reload, and session inversion. Icon preferences are unavailable.
### Aliases, hotkeys, columns, alignment/width/order, context/resource view overrides
**partial** — Configure additional navigation keys, literal aliases, and global/context resource
columns and sort. Inputs keep normal text editing; invalid overrides leave working defaults.
### Custom GVR relationship jumps with selectors/templates/namespace
**partial** — Define preference-file jumps and use :jump to open related views with a local filter.
Development source adds native discovered-owner graphs using the same history; arbitrary custom-
resource reference discovery is unavailable.
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
**partial** — Development source adds current CPU/memory usage, declared requests/limits, labelled
percentages and Node/extended-resource capacity. Missing, forbidden, stale, partial and measured-
zero values remain distinct. Complex Pod allocations are explicitly uncertain; GPU utilization and
broader per-resource history are unavailable; development overview history is separately configured.
Installed 0.3.0 predates these metrics columns.
### Pulse cluster overview and CPU/memory drill-downs
**partial** — Development source adds a native cluster overview with Node/Pod/workload health,
capacity, current usage and exact resource drill-downs. Configured Prometheus Service-proxy
CPU/memory history shows numeric values, gaps and explicit backend scope. Broader per-
resource/network/filesystem history remains unavailable; installed 0.3.0 predates the overview.
### XRay relationships, jump-to-owner/node, service endpoints and UsedBy
**partial** — Development source provides native :xray and :usedby views for owners, selector
matches, reported endpoints, placement and supported static configuration/storage/identity
declarations. Replacement UIDs and incomplete scans remain explicit; installed 0.3.0 predates these
views.
### RBAC can/user/group/service-account policies and rule inspection
**partial** — Development source includes role and subject browsing, namespace rules, current-
identity access reviews and RBAC who-can evidence. Partial reads, unknown group membership and
external-authorizer limits remain visible.
### Popeye/cluster diagnostic reports and actionable failure evidence
**partial** — Development source adds native :diagnostics and captured-workload :diagnose evidence,
plus explicit optional :popeye report ingestion. Source gaps, stale evidence and name-only report
identity remain visible; installed 0.3.0 predates these views.
### Opt-in image vulnerability scans, severity/package/fix views and advisory links
**planned** — Opt-in image vulnerability scanning and advisory/package/fix views are planned.
### Node shell helper pods, configurable image/namespace/limits/host mounts
**planned** — Node helper-pod shells and configurable host-mount/image/namespace controls are
planned.
### Cordon/uncordon/drain, disruption constraints and explicit overrides
**planned** — Reviewed cordon, uncordon and drain with disruption constraints and explicit overrides
are planned.
### Ephemeral debug containers and diagnostic sessions
**planned** — Creating ephemeral debug containers and their managed sessions is planned.
### HTTP benchmarks, per-context options, results browser and cancellation
**planned** — HTTP benchmarking, results browsing and benchmark cancellation are planned.
### Policy/quota/admission/scheduling views and removed-API handling
**partial** — Expanded policy, quota, admission and scheduling diagnostics are planned. Discovery
already reports removed APIs without fabricating a table.
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
