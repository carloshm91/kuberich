# Changelog

User-visible changes are grouped under Added, Changed, Fixed, and Security.
Release entries are written in release PRs and linked to their Git tags.

## Unreleased

### Changed

- Keep established Pod, standard and discovered resource order through unrelated
  live edits. Reorder changed typed sort values, identity ties and membership while
  retaining selection/scroll and generation-safe recovery.

- Avoid scanning every retained row when a single-line resource cell changes
  within a column whose header determines its width. Preserve native sizing,
  rendering and selection across ordinary and discovered resource tables.

- Pin every Linux CI host to Ubuntu 24.04 while retaining all interpreter/native,
  coverage and owned-cluster checks. Reject stale runner/job/artifact identities
  during release qualification and candidate retries.

- Refine the landing and initial docs with a shared flat presentation and mobile
  guide navigation. Generate CLI/resource/capability references from maintained
  contracts, reject stale source receipts, and rebuild both unpublished surfaces
  on each PR. Keep unavailable features and release/provider limits explicit.

- Prepare first public 0.1.0 and cumulative reviewed 0.x phases, superseding
  the earlier first-public-1.0-only policy without changing development metadata.
  Require selected/prior gates and all traced dependencies, immutable authored
  notes with optional reviewed previews, actual upgrade evidence and the planned
  organization-owned `kuberich/tap/kuberich` channel. Current public packages remain
  unavailable; full qualification and activation stay under #89.

- License KubeRich under Apache-2.0 and include contributor attribution NOTICE
  in Python artifacts. Align source Homebrew metadata and contribution guidance;
  earlier MIT grants and third-party licenses remain unchanged.

- Rename the private product/package/import/CLI to KubeRich / `kuberich`.
  Retain the `kubetrol` console alias and legacy preference environment variables;
  read existing preferences in place and provide explicit non-overwriting migration.
  Update UI identity and installation/release tooling without a version bump.

### Added

- Aggregate regular/init/ephemeral container and workload-Pod logs with stable
  source/UID prefixes, verified controller membership, bounded reader admission,
  per-source/aggregate retention, source picker/filter and plain/JSON exports.
  Enroll newly started containers without replaying ended streams; drain even
  dismissed export work before context-client cleanup.
- Preserve useful JSON log fields and scalar types while redacting decoded
  credential keys/strings within strict depth/expansion/control bounds.

- Prepare a protected main-only Cloudflare Pages publication of both development
  website surfaces, preserving checked artifact bytes and verifying live HTTPS
  digests, response headers and 404s. Retain source/deployment and partial-failure
  receipts. Application packages and custom-domain/DNS setup remain separate.
- Browse dynamically discovered resource families and explicit served versions
  through qualified commands and completion. Show typed server columns with
  metadata fallback, session-local column selection, captured YAML/details,
  stable history and discovery refresh/removal recovery. Keep generic mutation
  and persistent view preferences under their later owners.

- Resolve preferred custom-resource versions and ambiguous aliases from live
  discovery. Read arbitrary discovered types through bounded LIST/WATCH/GET,
  retaining server Table columns and full manifests with scoped JSON fallback.
  Refresh installed/removed APIs without replacing the context client.

- Attach to a captured running regular/init/ephemeral container inside the terminal
  workspace, with detach, faithful return status and retained selection.
- Review explicit bidirectional file/directory copies with frozen upload snapshots,
  bounded streaming downloads, inspected private tar extraction, no-follow local
  destinations, default Cancel, explicit overwrite and honest interrupted-upload
  outcomes. Keep uploads/attach gated in read-only mode and downloads explicit.

- Refresh token-file and exec certificate credentials with captured helper identity,
  private TLS pool replacement and generic explicit native login. Qualify HTTP
  CONNECT/SOCKS5 proxies, original/overridden TLS names and delegated Kubernetes
  logs, exec and port-forward connections; document GKE/OIDC migration and limits.
  Reject encrypted private keys before OpenSSL can request a terminal password.
  Drain credential file preparation through repeated cancellation before cleanup.

- Delete captured resources and explicitly selected batches with UID/version,
  propagation/grace and count confirmation; retain independent and pending outcomes.
  Trigger manual Jobs and suspend/resume Jobs/CronJobs with guarded review.

- Prepare a responsive private landing and source-generated initial user guides,
  actual local UI captures, browser/accessibility checks and reviewed hosting steps.
  Website/DNS and package publication remain separate approved launch actions.

- Review and confirm workload scale/restart/explicit revision rollback; monitor
  actual rollout progress with HPA, paused/OnDelete, narrow RBAC and UID/version guards.

- Edit selected manifests with a trusted native editor, private owned drafts,
  redacted preview, strict server dry-run, separate Apply and version/UID refusal.

- Guarded annotation changes with captured one-use confirmation, atomic UID/version
  conditions, common read-only policy and bounded public write-outcome history.

- Managed pod/Service TCP forwards with dynamic or explicit local ports,
  observed readiness, IPv4/IPv6 bind intent, session listing/stop and owned cleanup.

- Live discovered workload, batch, network, configuration, node and storage
  tables with typed sorting, scoped commands, retained navigation and redacted details.

- Verify disposable kind node/API identity before fixture writes and clean owned
  clusters on SIGINT/SIGTERM, including setup cancellation and repeated signals.

- Verified Homebrew source formula generation, isolated candidate installation
  and immutable reviewed update-PR automation.

- Prepare exact local release candidates and a maintainer-reviewed OIDC pipeline
  that consumes tested artifacts without rebuilding, enforces real main/matrix/
  milestone qualification, and recovers partial uploads without replacing bytes.

- Audit locked and freshly installed runtimes, validate artifact-linked CycloneDX
  SBOMs and original license notices, and reject incomplete security evidence,
  floating CI actions and undocumented or expired vulnerability exceptions.

### Changed

- Reduce repeated private macOS CI work while retaining full selected-job suites,
  independent coverage gates and mandatory six-environment release qualification.

- Describe embedded shells accurately in CLI help and provide one current
  installation/trial guide with a reproducible installed-wheel kind rehearsal.

- Restrict wheel/source artifacts to runtime/build assets, metadata, license and
  release notes. Development tests/scripts/lock, caches and undeclared private
  configuration/credential files stay outside the distribution.
- Use an original `ktrol` ASCII logo in the upper-right shared workspace header,
  with a compact wordmark below 120 columns and the existing hidden-header options.

### Fixed

- Verify disappearance after macOS reports a permission error for an exiting
  subprocess group. Preserve real permission failures and owned child cleanup.
- Preserve rejected namespace-command feedback through repaints of the same
  connecting view; show new connection progress or errors when its state changes.

- Preserve SSH hangup status on macOS when terminal attributes remain readable
  after the driver has stopped accepting output; probe without emitting bytes.
- Restore owned terminal sessions after external SIGHUP/SIGTERM, reap native and
  embedded children on SSH loss, and preserve hangup status when the remote TTY
  is revoked. tmux sessions remain available for reattachment.
- Recover following text and private cursor queries after malformed CSI in the
  same shell packet; retain rendered normal/alternate text and bounded cursors
  while shrinking the terminal.
- Ignore deferred shortcut rendering after its header view has been removed,
  avoiding a terminal failure when resize and view return overlap.
- Resolve native resize events against the current physical TTY so a delayed
  older event cannot leave the interface and embedded child at the wrong size.
- Distinguish recognized AWS helper login/role failures from API 401/403 without
  exposing provider output; share expiring-token refreshes and ignore delayed
  401 invalidation of newer cache revisions, including identical token bytes.
- Preserve a session's captured AWS environment, working directory and helper
  executable in delegated shells. Actual EKS qualification remains deferred to Q05 #87.
- Reflow header shortcuts when the logo changes width during terminal resizing.
- Keep frame margins, header columns and interaction/footer rows stable across
  pod, namespace, container and log navigation, focus changes and mouse clicks.
- Render the selected command completion inline in the dedicated `:` bar,
  without a dropdown; retain Tab/cycling acceptance and literal Enter behavior.

- Open container shells inside a full-screen Textual terminal with a persistent
  context/pod/container frame. Ctrl+C reaches the remote program; Ctrl+] returns
  to the retained container view, and Ctrl+Q closes the owned session and quits.

- Preserve exit 143 after SIGTERM during a native shell instead of reporting a
  terminal failure after successful cleanup and restoration.

- Enter after arrow navigation submits the highlighted command/namespace/context
  suggestion once; editing or changing scope discards the old selection.

- Keep quiet resource watches live through normal renewal without false timeout
  warnings or growing retries; still expose genuine outages with bounded recovery.
- Replace “Session connected” with “Resource data ready”, distinguish loading
  from a successful empty collection, and spell out context/namespace shortcut hints.

- Accept null optional exec credential args/env lists, including doctl's `env: null`,
  with regression tests for authentication and switching away from an auth error.
- Reach context/namespace pickers with `c`/`n` outside text inputs and connection
  status/retry with `i`/`r` or `:status`/`:retry` when a terminal intercepts function keys.

### Added

- Required isolated SSH/tmux terminal and fresh-wheel trials for resize, Unicode,
  color fallback, log navigation, native handoff, embedded protocols, cancellation
  during shell preparation, signal restoration and real connection loss.
- Native Azure kubelogin contracts and explicit `:login`, with mode-aware terminal
  stdin, private credential stdout, safe provider hints, captured delegated Azure
  identity and retry after cancellation. Actual Entra/AKS certification remains
  opt-in Q05 #87; generic exec TLS certificate rotation remains C08 #47.
- Exec token validation independent of argument length, allowing bounded large
  JWTs without accepting header controls or whitespace.
- Invocation-scoped cluster/user aliases, token and CA/client certificate overrides,
  repeated impersonation groups and the same captured identity in API streams and
  delegated container shells. Effective identity is visible in the header.
- Effective `--refresh`/`-r` table repaint interval, retaining live watches and
  cursor/filter state without periodic API polling.
- Rectangular dedicated command bar, with compact side borders in short terminals.
- Local context table through `:ctx`/`c`/F2 with cluster, auth-info and namespace;
  filtering and browsing preserve the resource workspace and kubeconfig.
- Container image, readiness, state/reason, restart count, configured probes,
  CPU/memory requests/limits and ports from the captured pod snapshot.

- K9s-inspired black/cyan/yellow workspace and a default `k9s` theme, with
  context/cluster/user/version header, top inputs, view shortcuts and Escape trails.
- Live namespace NAME/STATUS/AGE table via `:ns` / `n`, Enter-to-pods and `0` for
  all namespaces; returning retains namespace filtering, UID cursor and viewport.
- Common full-workspace container/log layouts with top log search, retaining the
  embedded shell, captured targets and existing stream cleanup.

- Embedded selected-container shells via kubectl exec, with `x`/`:shell` on pods,
  `s`/`x` on containers and a configurable literal shell argument list.
- Private connection snapshots pinned to the prepared session, pod-UID checks,
  read-only enforcement and return to the retained table after exit or failure.

- Shared bounded local-process runner and native terminal handoff foundation,
  with captured scope/arguments, enforced read-only policy and owned cleanup.
  The embedded shell reuses process policy, captured arguments and cleanup.

- Enter on a pod opens its regular/init container table, including single-container
  pods; Enter on a container opens its logs. Esc returns through both views, while
  `d` keeps resource details and `l` keeps the direct log shortcut.

- Container log viewer with regular/init selection, current/previous output,
  head/tail/time windows, timestamps, wrapping, literal search and Vim navigation.
- Separate reception pause and viewport follow, bounded virtualized history,
  clear/marks/column lock/fullscreen, redacted copy/save and awaited cleanup.

- Backend current/previous regular/init container logs with captured UID/context,
  tail/since/timestamp options, incremental UTF-8 framing and explicit errors.
- Owned cancellation, quiet-follow semantics, bounded redacted lines/retention
  and consumer backpressure, integrated into the S02 terminal log viewer.

- Read-only captured-UID pod YAML, details and related events, with managedFields
  visibility, literal search, redacted copying and return to the live table.
- Clear denied/missing reads, same-name recreation rejection, viewer invalidation
  and awaited request/serializer cleanup, with API, Pilot, PTY and install checks.

- Shared initial/interactive pod/context/namespace commands, bounded literal
  suggestions with Tab acceptance, and local Unicode text/regex filtering.
- Navigation back/forward preserving scope, filter, typed sorting, UID selection
  and viewport; stale-result rejection and awaited worker cleanup.

- Live UID keyed pod rows with readiness, init/sidecar/waiting/termination reasons,
  restarts, continuously updating age, typed sorting and stable selection/scroll.
- Incremental cell/row patches, cancellation-safe background projection, distinct
  loading/empty/error states and visible data at 40×12, with real API/PTY/install evidence.

- Active pod synchronization with live counts and loading/stale/error status,
  generation-bound snapshots, coalesced scope changes and bounded UI subscriptions.
- Awaited cleanup and late-result rejection, with rapid-switch, real-API, Pilot
  and PTY recovery/exit tests. Pod table rows are delivered in B02.

- Backend list/watch synchronization with stable UID state, idempotent events,
  bookmarks, opaque checkpoints, bounded retries and full relists after expiry.
- Real streaming/backpressure/cancellation tests and disposable-kind create,
  modify, delete and same-name recreation qualification. UI pod rows are delivered in B02.

- Backend API discovery with core/named groups, modern/legacy negotiation,
  aliases and explicit partial results, plus scoped atomic paginated snapshots,
  collection versions and one full restart for expired continuation tokens.
- Resource normalization/HTTP cancellation tests and real disposable-kind
  paginated resource qualification. Terminal pod rows are delivered in B02.

- Isolated kubeconfig/context sessions, namespace discovery and selectors,
  TLS/client-certificate/static-token authentication and bounded noninteractive
  exec-token helpers, with distinct connection states and owned cleanup.
- Real HTTP/TLS/helper, Pilot, terminal and disposable-kind verification for the
  context checkpoint. Live resource views and provider qualification remain upcoming.

- Help/version subcommands and short version output, all audited launch flags
  with explicit unavailable-feature errors, and a diagnostic data-directory path.
- Header/logo/scope visibility, initial terminal help/quit, and read-only/write
  invocation overrides with shared CLI/UI command policy and persistent status.
- Launch-contract/alias/precedence tests, reviewed help snapshot, visibility Pilot
  evidence and real-terminal initial help/quit restoration checks.

- Real terminal workspace with context/namespace/connection indicators, an empty
  resource table, filter/command inputs, keyboard/mouse navigation, scrollable
  help, responsive layouts, built-in themes and packaged styles.
- Pilot/layout tests and real PTY evidence for navigation, resize, Unicode paste,
  rapid command input, normal/error terminal restoration and installed entry points.

- Versioned YAML preferences with typed defaults, explicit environment/CLI
  precedence, legacy migration, retained unknown fields and atomic private writes.
- Safe local `info`, `config init`/`check`, config/log path flags and stable
  errors that do not echo configuration values or rejected arguments.
- Private rotating diagnostic logs, process ownership, bounded records, credential
  redaction and debug locations without exception values or console tracebacks.
- Project roadmap, architecture, quality requirements, and release methodology.
- Contribution and security policies, issue templates, and a structured backlog.
- Installable Python development package with `kuberich --help`, `--version`,
  module invocation and a default terminal launch.
- Locked Textual/Kubernetes dependencies, developer tooling, and clean-artifact
  installation tests for Python 3.12 through 3.14 on Linux and macOS.
- Independent production line/branch coverage gates, 90% changed-line coverage,
  100% critical-module coverage, and regression checks for invalid/missing evidence.
- A Linux/macOS application quality matrix and aggregate status that rejects
  failed, cancelled, or skipped dependencies; private-repository merge checks
  remain manually verified until GitHub branch protection is available.

No public application release has been published. Development installation is
available from a source checkout; PyPI and Homebrew publication come later.

### Security

- Immutable service-level action policy that refuses unknown actions and blocks
  mutation, exec, attach and unclassified plugins in read-only mode; actual
  cluster-service enforcement must be qualified as those operations ship.

- Shared bounded literal display text, credential redaction and control escaping,
  with explicit multiline behavior and preserved actionable error context.
- Immutable argument vectors and client/context/UID target captures with stale
  target rejection; operation enforcement remains part of upcoming services.
- Test-wide ambient Kubernetes credential traps and a qualified owned local
  fixture loader that preserves configuration files and SDK defaults.
- Focused trust-boundary model and documented integration responsibilities
  for authentication helpers, plugins, terminal sinks and release artifacts.
