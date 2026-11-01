# Changelog

User-visible changes are grouped under Added, Changed, Fixed, and Security.
Release entries are written in release PRs and linked to their Git tags.

## Unreleased

### Added

- Retry a failed resource view without closing the workspace. Create a private,
  redacted diagnostic bundle with `kuberich bug-report`; fatal UI errors restore
  the terminal before printing a local crash-report path
  ([#216](https://github.com/carloshm91/kuberich/issues/216),
  [Carlos J. Herrera](https://github.com/carloshm91)).

### Changed

- Replace the README with a concise product introduction, published installation,
  a read-only quick start and a plain feature list
  ([#223](https://github.com/carloshm91/kuberich/issues/223),
  [Carlos J. Herrera](https://github.com/carloshm91)).
- Report runtime heartbeat latency as advisory for 0.x while retaining unchanged
  strict opt-in and stable-release limits, real blocking negative controls and
  every functional, resource, cleanup and coverage requirement
  ([#230](https://github.com/carloshm91/kuberich/issues/230),
  [Carlos J. Herrera](https://github.com/carloshm91)).
- Organize user documentation into 19 pages with tutorial, how-to, reference and
  explanation navigation. Keep the existing guidance and old guide routes while
  introducing a plain-language style and a complete document migration map
  ([#222](https://github.com/carloshm91/kuberich/issues/222),
  [Carlos J. Herrera](https://github.com/carloshm91)).
- Keep oversized resource collections live with explicit incomplete counts,
  bounded retained rows, paginated progress and `:server` label/field selectors;
  offer metadata-only payloads in generic views with full-object recovery
  ([#213](https://github.com/carloshm91/kuberich/issues/213),
  [Carlos J. Herrera](https://github.com/carloshm91)).

- Keep offline diagnostics independent of terminal/SDK imports and defer cluster
  preparation until the first terminal refresh. Report all startup latency targets
  honestly for 0.x, retaining original strict opt-in/stable limits and mandatory
  memory, source, output, import, frame and cleanup requirements
  ([#214](https://github.com/carloshm91/kuberich/issues/214),
  [Carlos J. Herrera](https://github.com/carloshm91)).
- Add parallel development test layers and an early full unit/contract/UI signal
  before the complete platform and coverage checks
  ([#209](https://github.com/carloshm91/kuberich/issues/209),
  [Carlos J. Herrera](https://github.com/carloshm91)).
- Keep the Kubernetes SDK's date parser on the qualified 2.x major version so
  fresh installs use the reviewed runtime dependency range.

### Fixed

- Allow plugin review from qualified custom-resource views while retaining captured
  UID, canonical resource and API-version loading guards
  ([#278](https://github.com/carloshm91/kuberich/issues/278),
  [Carlos J. Herrera](https://github.com/carloshm91)).
- Accept explicit Basic credentials and kubectl's empty optional connection
  fields, retain credential schemes for reads/writes/delegation and print a
  reviewed OIDC exec migration fragment without copying existing tokens or
  changing kubeconfig files. Mask prepared Basic credential values in captured
  plugin stdout and stderr
  ([#215](https://github.com/carloshm91/kuberich/issues/215),
  [Carlos J. Herrera](https://github.com/carloshm91)).

- Keep native macOS builds and installation checks on supported runners
  ([#291](https://github.com/carloshm91/kuberich/issues/291),
  [Carlos J. Herrera](https://github.com/carloshm91)).
- Wait for actual selection receipt in isolated X11 clipboard qualification,
  including delayed owners, absent selections and cancelled readers
  ([#281](https://github.com/carloshm91/kuberich/issues/281),
  [Carlos J. Herrera](https://github.com/carloshm91)).

- Reuse one palette snapshot for each shortcut panel render and avoid layout
  updates for unchanged header text during navigation, resizing and theme changes
  ([#209](https://github.com/carloshm91/kuberich/issues/209),
  [Carlos J. Herrera](https://github.com/carloshm91)).

### Security

- Update the development installer's FileLock, the standalone builder's
  Setuptools, and the deployment tool's Wrangler/Miniflare/Undici graph to
  patched versions. Keep application runtime requirements unchanged
  ([#270](https://github.com/carloshm91/kuberich/issues/270),
  [Carlos J. Herrera](https://github.com/carloshm91)).

## 0.2.0 — 2026-10-21

[Published release](https://github.com/carloshm91/kuberich/releases/tag/v0.2.0).
[Authored release notes](docs/release-notes/0.2.0.md)
describe this phase, installation, upgrades and known limits. The entries below
retain development history.

### Added

- Install from Homebrew with prebuilt bottles on macOS Apple Silicon, macOS Intel
  and Linux x86_64; other systems still build from source
  ([#193](https://github.com/carloshm91/kuberich/issues/193),
  [Carlos J. Herrera](https://github.com/carloshm91)).

- Reload the preference file while KubeRich runs. An invalid file keeps the
  last valid preferences. Add per-context `read_only` and `refresh_seconds`,
  the terminal background as a palette color, full API titles, and notices for
  unknown fields ([#64](https://github.com/carloshm91/kuberich/issues/64),
  [Carlos J. Herrera](https://github.com/carloshm91)).

- Jump from the selected row to a related view with `:jump`, using jumps you
  define in the preference file. Templates only read fields from the row
  ([#64](https://github.com/carloshm91/kuberich/issues/64),
  [Carlos J. Herrera](https://github.com/carloshm91)).

- Rename or delete a kubeconfig context from `:ctx` after a review, with a backup,
  and clean up completed and failed pods with `:cleanup`
  ([#63](https://github.com/carloshm91/kuberich/issues/63),
  [Carlos J. Herrera](https://github.com/carloshm91)).

- Add named/container-qualified TCP forward mappings, local/context presets,
  explicitly trusted annotation shortcuts, kubectl transport selection and
  bounded reconnects with captured-resource and process cleanup checks
  ([#62](https://github.com/carloshm91/kuberich/issues/62),
  [Carlos J. Herrera](https://github.com/carloshm91)).

- Add session command/filter recall, inverse/fuzzy/local metadata filters, namespace
  favorites, wide/errors controls, bounded UID ranges, read-only text navigation,
  nested command bars and live captured-container refresh with owned cleanup.
  Copy names/namespaces/text through bounded native macOS/X11 or OSC52/tmux
  backends; mouse reporting requires explicit opt-in
  ([#61](https://github.com/carloshm91/kuberich/issues/61),
  [Carlos J. Herrera](https://github.com/carloshm91)).

- Document the pinned 50-file/108-command plugin compatibility census, external
  dependencies and alternatives; verify 18 explicit argv adaptations and three
  original capture/interactive/background manifests. Accept valid hyphenated CRD
  plural scopes and identify unsupported boolean inversion accurately
  ([#60](https://github.com/carloshm91/kuberich/issues/60),
  [Carlos J. Herrera](https://github.com/carloshm91)).

- Run explicitly configured local plugins with typed Review/Run forms,
  scope-aware shortcuts, capture/background/native foreground modes, bounded
  sanitized output, visible job controls and captured credential-helper identity
  ([#59](https://github.com/carloshm91/kuberich/issues/59)).

- Validate explicitly configured local plugin files, context/resource scope,
  shortcut overrides, typed inputs and literal captured variables without running
  commands during configuration checks. Explicit execution uses separate review
  ([#58](https://github.com/carloshm91/kuberich/issues/58),
  [Carlos J. Herrera](https://github.com/carloshm91)).

- Configure per-view navigation keys and literal command aliases with effective
  help/completion. Apply or explicitly save resource column order, visibility,
  widths, alignment and typed sort globally/per context; retain working fallbacks
  after invalid overrides or changed server columns
  ([#57](https://github.com/carloshm91/kuberich/issues/57),
  [Carlos J. Herrera](https://github.com/carloshm91)).

- Preview and save built-in/custom themes globally or per context, retain working
  defaults after invalid appearance overrides, and invert session colors with
  contrast repair. Add original About content and an opt-in cached, bounded,
  offline-safe public-release notice ([#56](https://github.com/carloshm91/kuberich/issues/56),
  [Carlos J. Herrera](https://github.com/carloshm91)).

- Inspect ConfigMap and Secret keys with values hidden by default, explicit
  reveal/copy, text/Base64 controls and fresh identity/version-bound reads.
  Edit Secrets through the private-draft, redacted-review and separate
  dry-run/Apply workflow ([#55](https://github.com/carloshm91/kuberich/issues/55),
  [Carlos J. Herrera](https://github.com/carloshm91)).

### Fixed

- Release retired table-render cache entries promptly when views change, retaining
  native LRU behavior and capacity. Size configuration-key columns from their
  captured metadata so initial paints do not truncate names while idle layout is
  pending ([#62](https://github.com/carloshm91/kuberich/issues/62),
  [Carlos J. Herrera](https://github.com/carloshm91)).

- Preserve configured plugin file locations and working directories during
  explicit preference migration. Reuse bounded exact CSS parses when revisiting
  themes, retaining native errors and independent app ownership after a required
  responsiveness check exposed repeated parsing/collection work
  ([#58](https://github.com/carloshm91/kuberich/issues/58),
  [Carlos J. Herrera](https://github.com/carloshm91)).

### Security

- Update the locked aiohttp runtime dependency from 3.14.3 to 3.14.5, which fixes
  CVE-2026-111063, CVE-2026-111064 and GHSA-2g87-pp6c-29x5
  ([Carlos J. Herrera](https://github.com/carloshm91)).

- Update the locked certifi dependency from 2026.7.22 to 2026.10.19, which removes
  the emSign root certificates named in PYSEC-2026-4320
  ([Carlos J. Herrera](https://github.com/carloshm91)).

## 0.1.0 — 2026-10-12

[Published release](https://github.com/carloshm91/kuberich/releases/tag/v0.1.0).
[Authored release notes](docs/release-notes/0.1.0.md)
describe this phase, installation, upgrades and known limits. The entries below
retain development history; dated qualification statements are superseded by
the [completed workload checkpoint](docs/acceptance/workload-checkpoint.md).

### Added

- Add a guided everyday workflow, troubleshooting, installation/upgrade coverage
  and reader-facing capability summaries. Refresh the flat landing page and README;
  tutorial names and screenshot resources are fictional or owned disposable fixtures.
  Clean public guides and generated CLI references of internal tracking codes
  ([#150](https://github.com/carloshm91/kuberich/issues/150),
  [Carlos J. Herrera](https://github.com/carloshm91)).

- Review the last 1,000 normal-screen shell rows inside the terminal, with
  deliberate local paging, literal Unicode search and explicit redacted row
  selection/copy. Keep remote output, cursor and editors live and return with
  Enter or Escape. Report discarded history and release session-owned buffers
  on exit or target invalidation.

### Fixed

- Give reproducible CycloneDX reports a content-derived serial number required
  by GitHub's SBOM attestation parser. Reject missing identifiers before publication
  ([#89](https://github.com/carloshm91/kuberich/issues/89),
  [Carlos J. Herrera](https://github.com/carloshm91)).

- Separate read-only branch-protection access from release publication credentials;
  give qualification reads their explicit Actions/checks/PR/issues permissions.
  Explain missing owner setup before network/publication
  ([#89](https://github.com/carloshm91/kuberich/issues/89),
  [Carlos J. Herrera](https://github.com/carloshm91)).

- Reduce temporary component-style allocations during focus and theme changes,
  preserving native CSS and the existing response-time gate. Pin the qualified
  Textual version used by scoped rendering adaptations
  ([#150](https://github.com/carloshm91/kuberich/issues/150),
  [Carlos J. Herrera](https://github.com/carloshm91)).

- Preserve credential-helper success, size-limit errors and spawn cancellation
  during the macOS process-group teardown race. Reuse the existing bounded group
  signal guard; only confirmed disappearance permits transient teardown denial
  ([#150](https://github.com/carloshm91/kuberich/issues/150),
  [Carlos J. Herrera](https://github.com/carloshm91)).

- Keep shell output cleanup safe while Textual removes its footer controls;
  queued PTY output cannot query a History button that has already left the DOM.

### Changed

- Reuse retained log geometry across append, eviction and wrap changes while
  preserving literal search, marks and navigation. Update fixed-height log
  metadata without repeatedly recalculating the covered workspace layout.

- Retain up to 10,000 log lines within the existing 4 MiB byte limit. Reuse
  bounded wrap layouts, wake display controls promptly and defer covered
  workspace painting while live observations and target validation continue.
  Add a reproducible owned-loopback CLI/PTY load observer; performance
  qualification remains open.

- Give pending input, target changes and cancellation a turn during dense log
  delivery, preserving source order, consumer backpressure and bounded retention.
  Require normal-runtime backend latency controls alongside the original
  branch-covered HTTP workload and final ownership checks.

- Format retained aggregate log views and exports in bounded owned turns,
  preserving captured source identities, arrival order and plain/JSON controls.
  Collect parser outcomes before returning cancellation, including late errors
  on Python 3.14, while preserving ordinary error propagation.

- Decode and validate live resource events in one owned worker, preserving
  bounded framing, pull backpressure, Table fallback and safe error messages.
  Drain JSON read/watch workers through repeated cancellation before cleanup.

- Avoid duplicate workspace label updates and wide equality on reused immutable
  resource rows; repaint safe owned cell edits through native row regions while
  retaining full native geometry and unknown-content handling.

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

- Build standalone Linux x86_64/ARM64 and macOS Intel/ARM64 bundles with an
  included Python runtime, terminal assets, certificates and dependency notices.
  Verify archive-bound CLI, browsing, credential-helper and shell behavior, and
  preserve checksums/provenance for release preparation. Public downloads remain
  pending the first qualified release.

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
