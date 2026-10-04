# Changelog

User-visible changes are grouped under Added, Changed, Fixed, and Security.
Release entries are written in release PRs and linked to their Git tags.

## Unreleased

### Fixed

- Accept null optional exec credential args/env lists, including doctl's `env: null`,
  with regression tests for authentication and switching away from an auth error.
- Reach context/namespace pickers with `c`/`n` outside text inputs and connection
  status/retry with `i`/`r` or `:status`/`:retry` when a terminal intercepts function keys.

### Added

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
- Installable Python development package with `kubetrol --help`, `--version`,
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
