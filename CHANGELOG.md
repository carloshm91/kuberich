# Changelog

User-visible changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
See [release policy](docs/releases.md) for the project's versioning rules.

## [Unreleased]

### Changed

- Find the published version and installation links on a short status page ([#226](https://github.com/carloshm91/kuberich/issues/226)).
- Follow focused task guides with references generated from commands, keys and configuration ([#222](https://github.com/carloshm91/kuberich/issues/222), [#224](https://github.com/carloshm91/kuberich/issues/224)).
- Find installation steps and product features in a shorter README ([#223](https://github.com/carloshm91/kuberich/issues/223)).
- Install with the supported Kubernetes SDK date-parser version.
- Read shorter release notes focused on changes you can use ([#227](https://github.com/carloshm91/kuberich/issues/227)).

### Fixed

- Navigate, resize and change themes without repeatedly updating unchanged headers ([#209](https://github.com/carloshm91/kuberich/issues/209)).

### Security

- Build and deploy with patched FileLock, Setuptools and Cloudflare tooling dependencies ([#270](https://github.com/carloshm91/kuberich/issues/270)).

## [0.2.0] - 2026-10-21

[Release notes](docs/release-notes/0.2.0.md). Changes by [Carlos J. Herrera](https://github.com/carloshm91) and [Dependabot](https://github.com/apps/dependabot).

### Added

- Install prebuilt Homebrew bottles on macOS Apple Silicon, macOS Intel and Linux x86_64 ([#193](https://github.com/carloshm91/kuberich/issues/193)).
- Build from source with Homebrew when a matching bottle is unavailable ([#193](https://github.com/carloshm91/kuberich/issues/193)).
- Reload preferences while KubeRich runs; invalid files keep your last working settings ([#64](https://github.com/carloshm91/kuberich/issues/64)).
- Choose read-only mode and refresh intervals per context ([#64](https://github.com/carloshm91/kuberich/issues/64)).
- Use your terminal background in themes, show full API titles and see unknown-setting notices ([#64](https://github.com/carloshm91/kuberich/issues/64)).
- Open related resources with configured `:jump` commands using fields from the selected row ([#64](https://github.com/carloshm91/kuberich/issues/64)).
- Rename or delete kubeconfig contexts after confirmation, with a backup ([#63](https://github.com/carloshm91/kuberich/issues/63)).
- Review and remove completed or failed pods with `:cleanup` ([#63](https://github.com/carloshm91/kuberich/issues/63)).
- Forward named ports, including ports selected by container name ([#62](https://github.com/carloshm91/kuberich/issues/62)).
- Save global or per-context port-forward presets and explicitly trust annotation shortcuts ([#62](https://github.com/carloshm91/kuberich/issues/62)).
- Select kubectl's forwarding transport and reconnect previously ready forwards within your configured retry limit ([#62](https://github.com/carloshm91/kuberich/issues/62)).
- Recall commands and filters, including inside container and log views ([#61](https://github.com/carloshm91/kuberich/issues/61)).
- Use inverse, fuzzy and metadata filters, plus wide and error-focused resource views ([#61](https://github.com/carloshm91/kuberich/issues/61)).
- Mark favorite namespaces and select resource ranges by UID ([#61](https://github.com/carloshm91/kuberich/issues/61)).
- Copy names, namespaces or selected text through macOS, X11 or OSC52, including tmux ([#61](https://github.com/carloshm91/kuberich/issues/61)).
- Enable terminal mouse reporting explicitly when you want mouse controls ([#61](https://github.com/carloshm91/kuberich/issues/61)).
- Refresh container information while keeping your selection, and navigate text in read-only views ([#61](https://github.com/carloshm91/kuberich/issues/61)).
- Find compatibility notes, dependencies and alternatives for 50 K9s plugin files covering 108 commands ([#60](https://github.com/carloshm91/kuberich/issues/60)).
- Start from 18 command adaptations and three capture, interactive and background plugin examples ([#60](https://github.com/carloshm91/kuberich/issues/60)).
- Use hyphenated custom-resource scopes; reject unsupported plugin fields and boolean inversion before commands run ([#58](https://github.com/carloshm91/kuberich/issues/58), [#60](https://github.com/carloshm91/kuberich/issues/60)).
- Confirm local plugins through typed forms and resource-specific shortcuts ([#59](https://github.com/carloshm91/kuberich/issues/59)).
- Run configured plugins with captured output, background jobs or a full terminal ([#59](https://github.com/carloshm91/kuberich/issues/59)).
- Inspect redacted plugin output, stop jobs and run commands with the credentials from your selected context ([#59](https://github.com/carloshm91/kuberich/issues/59)).
- Load only explicitly configured plugin files, with scoped inputs and literal selected-resource variables ([#58](https://github.com/carloshm91/kuberich/issues/58)).
- Check plugin configuration without executing commands; running a plugin needs separate confirmation ([#58](https://github.com/carloshm91/kuberich/issues/58)).
- Customize per-view navigation keys and command aliases, with matching help and completion ([#57](https://github.com/carloshm91/kuberich/issues/57)).
- Save column order, visibility, widths, alignment and typed sorting globally or per context ([#57](https://github.com/carloshm91/kuberich/issues/57)).
- Keep working column defaults after invalid overrides or changes to server-provided columns ([#57](https://github.com/carloshm91/kuberich/issues/57)).
- Preview and save built-in or custom themes globally or per context ([#56](https://github.com/carloshm91/kuberich/issues/56)).
- Invert colors with contrast correction and keep working defaults after invalid theme settings ([#56](https://github.com/carloshm91/kuberich/issues/56)).
- Open About and optionally check cached release notices without requiring an internet connection at startup ([#56](https://github.com/carloshm91/kuberich/issues/56)).
- Inspect ConfigMap and Secret keys with values hidden until you reveal or copy them ([#55](https://github.com/carloshm91/kuberich/issues/55)).
- Switch between text and Base64 values while rejecting reads from replaced or changed resources ([#55](https://github.com/carloshm91/kuberich/issues/55)).
- Edit Secrets through private drafts, redacted previews, server dry-run and a separate Apply confirmation ([#55](https://github.com/carloshm91/kuberich/issues/55)).

### Fixed

- Release table memory promptly when changing views ([#62](https://github.com/carloshm91/kuberich/issues/62)).
- Read complete configuration-key names on the first paint ([#62](https://github.com/carloshm91/kuberich/issues/62)).
- Keep plugin file locations and working directories when migrating preferences ([#58](https://github.com/carloshm91/kuberich/issues/58)).
- Switch back to earlier themes without repeatedly parsing their styles ([#58](https://github.com/carloshm91/kuberich/issues/58)).

### Security

- Use aiohttp 3.14.5 with fixes for CVE-2026-111063, CVE-2026-111064 and GHSA-2g87-pp6c-29x5.
- Use certifi 2026.10.19 without the emSign roots removed by PYSEC-2026-4320.

## [0.1.0] - 2026-10-12

[Release notes](docs/release-notes/0.1.0.md). Changes by [Carlos J. Herrera](https://github.com/carloshm91) and [Dependabot](https://github.com/apps/dependabot).

### Added

- Follow everyday workflows, troubleshooting and installation guides with command, resource and feature references ([#150](https://github.com/carloshm91/kuberich/issues/150)).
- Read the project website and guides on desktop or mobile screens ([#150](https://github.com/carloshm91/kuberich/issues/150)).
- Browse the last 1,000 shell-history rows with local paging, Unicode search and redacted selection or copy.
- Keep shell output and editors running during history review; return with Enter or Escape and see discarded-history notices.
- Install standalone Linux x86_64/ARM64 or macOS Intel/ARM64 archives with Python, certificates, terminal assets and license notices included.
- Combine regular, init, ephemeral and workload-container logs with source and UID prefixes.
- Pick or filter log sources and enroll newly started containers without replaying finished streams.
- Keep JSON log fields and scalar types while hiding recognized credentials.
- Browse discovered APIs, choose served resource versions and resolve preferred versions or ambiguous aliases.
- Read server-provided columns with metadata fallback and choose columns for the current session.
- Refresh added or removed APIs without replacing your context; keep available discovery results when some groups fail.
- Attach to running regular, init or ephemeral containers, detach and return to your previous selection with their exit status.
- Confirm uploads and downloads of files or directories, with Cancel selected by default and explicit overwrite choices.
- Upload a fixed local snapshot; download with checked archive paths, types, sizes and local destinations.
- See interrupted-upload outcomes instead of treating a partial transfer as success.
- Refresh token-file and exec certificate credentials without changing the selected helper identity.
- Use HTTP CONNECT or SOCKS5 proxies and explicit TLS server names for API access and delegated kubectl commands.
- Find GKE/OIDC migration guidance and reject encrypted private keys before an unexpected password prompt.
- Confirm individual or batch deletions with UID/version checks, propagation and grace settings, and separate per-resource outcomes.
- Create manual Jobs and suspend or resume Jobs and CronJobs after confirmation.
- Confirm workload scaling, restarts and rollback to an explicit revision.
- Follow rollout progress with HPA, paused-workload, OnDelete and permission limits shown.
- Edit manifests in a trusted editor using private drafts, redacted previews, server dry-run and separate Apply confirmation.
- Confirm annotation changes once, reject replaced or changed resources and inspect recent write outcomes.
- Forward pod or Service TCP ports with chosen or dynamically allocated local ports and IPv4/IPv6 bind settings.
- See forwarding readiness, list active sessions and stop a selected forward.
- Browse workload, batch, network, configuration, node and storage tables with typed sorting and redacted details.
- Install from the project Homebrew tap on Linux and macOS.
- Use configured Azure kubelogin helpers and request interactive sign-in with `:login`.
- Accept long exec-helper tokens while rejecting header controls and whitespace.
- Override cluster/user aliases, tokens, CA files and client certificates for one invocation.
- Set repeated impersonation groups and keep the same selected identity in API streams, container shells and the header.
- Set table repaint intervals with `--refresh` or `-r` while preserving live watches, filters and the cursor.
- Browse local contexts with cluster, user and namespace details through `:ctx`, `c` or F2 without changing kubeconfig.
- Inspect the selected pod's container images, readiness, reasons, restarts, probes, requests, limits and ports.
- Use the `k9s` theme with visible context, cluster, user, version, shortcuts and Escape trails.
- Browse namespace status and age with `:ns` or `n`; Enter opens pods and `0` selects all namespaces.
- Keep namespace filtering, selection and scroll when returning to the namespace table.
- Move through pods, containers, logs and embedded shells in one responsive terminal workspace with scrollable help.
- Navigate tables and help with keyboard or terminal mouse controls.
- Open selected-container shells with `x` or `:shell`, including configurable literal shell arguments.
- Press Enter on a pod for its regular/init containers, then Enter for logs; Escape returns through both views.
- Read current or previous container logs with head, tail, time-window and timestamp options, wrapping and literal search.
- Navigate logs with Vim keys, clear history, set marks, lock columns or open fullscreen.
- Pause log reception separately from viewport following, then copy redacted text or save selected output.
- Inspect pod YAML, details and related events, toggle managedFields and search or copy redacted text.
- See missing or denied reads, reject same-name replacements and close viewers when their target is no longer valid.
- Select pods, contexts and namespaces through commands with Tab completion and Unicode text or regex filters.
- Navigate backward or forward while preserving scope, filters, typed sorting, resource selection and viewport.
- Track pod readiness, init/sidecar states, waiting or termination reasons, restarts and continuously updated ages.
- Read live resource counts and distinguish loading, empty, stale and error states in terminals as small as 40×12.
- Recover resource watches after disconnects or expired server checkpoints.
- Browse complete paginated resource collections without losing rows between pages.
- Connect with kubeconfig contexts, TLS certificates, static tokens or configured exec credential helpers.
- Launch `kuberich` or `python -m kuberich` and inspect `--help`, `--version` or the short version output.
- Use versioned YAML preferences with environment/CLI overrides, unknown-field preservation and private atomic saves.
- Inspect `info`, initialize or check configuration offline, and choose configuration or log paths.
- Install Python packages on Linux or macOS with CPython 3.12–3.14.

### Changed

- Keep up to 10,000 log lines within a 4 MiB memory limit.
- Export aggregate logs as plain text or JSON while preserving source identities and arrival order.
- Use KubeRich under Apache-2.0 with contributor notices; earlier grants and third-party licenses stay unchanged.
- Use `kuberich` while keeping the `kubetrol` alias, existing preferences and legacy environment variables.
- Migrate development preferences explicitly without overwriting existing files.
- Install packages that exclude development tools, tests, caches and private configuration.
- See a compact `ktrol` header wordmark when terminal space is limited.
- Choose compact headers or hide the header, logo or scope information with launch options.

### Fixed

- Change focus or themes without repeatedly recalculating unchanged styles ([#150](https://github.com/carloshm91/kuberich/issues/150)).
- Keep credential-helper success and real errors intact during macOS process cleanup ([#150](https://github.com/carloshm91/kuberich/issues/150)).
- Close shell history controls or resize the workspace during shutdown without late-render crashes.
- Keep log search, marks and navigation stable as lines arrive, expire or wrap.
- Handle input, target changes and cancellation during dense log delivery, including behind covered views.
- Apply live table updates without repeatedly processing unchanged rows or blocking input.
- Keep resource order, selection and scroll stable across unrelated edits; reorder rows only when sorting or membership changes.
- Keep rejected namespace-command feedback visible until connection state changes.
- Restore the terminal and preserve hangup status after SSH loss; tmux sessions remain available for reattachment.
- Restore terminal sessions after SIGHUP or SIGTERM, including exit status 143 for interrupted native shells.
- Recover text and cursor handling after malformed terminal escape sequences, including during resizing.
- Keep the current terminal size, header shortcuts and workspace geometry correct across resizing, focus changes and view navigation.
- Distinguish AWS login/role failures from API 401/403 errors without exposing provider output.
- Share expiring-token refreshes and ignore delayed failures from an older token revision.
- Keep the selected AWS environment, working directory and helper executable in delegated shells.
- Complete commands inline inside a dedicated bordered `:` bar, with Tab acceptance and literal Enter behavior.
- Keep container shells inside the workspace; Ctrl+C reaches the program, Ctrl+] returns and Ctrl+Q quits.
- Submit the highlighted command, context or namespace once after arrow navigation; editing discards the old selection.
- Keep quiet resource watches connected without false timeout warnings while reporting genuine outages.
- Distinguish ready resource data from loading or an empty collection, with clear context and namespace shortcuts.
- Accept null optional exec-helper argument or environment lists, including doctl's `env: null`.
- Use `c`/`n`, `i`/`r`, `:status` or `:retry` when your terminal intercepts function keys.
- Prevent late results from an old context replacing your current view when switching quickly.

### Security

- Start read-only to block cluster changes, shells and attach sessions, with stale-target checks before actions.
- Hide recognized credentials and escape hostile markup or control sequences before displaying remote text.
- Pass selected resource names as literal process arguments and reject replaced targets before running an action.
- Keep rotating diagnostic logs private and redact credentials without echoing rejected arguments or exception values.
- Verify downloads with checksums, dependency reports, license notices and stable SBOM identifiers ([#89](https://github.com/carloshm91/kuberich/issues/89)).

[Unreleased]: https://github.com/carloshm91/kuberich/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/carloshm91/kuberich/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/carloshm91/kuberich/releases/tag/v0.1.0
