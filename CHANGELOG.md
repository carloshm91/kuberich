# Changelog

User-visible changes are grouped under Added, Changed, Fixed, and Security.
Release entries are written in release PRs and linked to their Git tags.

## Unreleased

### Added

- Project roadmap, architecture, quality requirements, and release methodology.
- Contribution and security policies, issue templates, and a structured backlog.
- Installable Python development package with `kubetrol --help`, `--version`,
  module invocation, and an explicit status message before the terminal UI exists.
- Locked Textual/Kubernetes dependencies, developer tooling, and clean-artifact
  installation tests for Python 3.12 through 3.14 on Linux and macOS.
- Independent production line/branch coverage gates, 90% changed-line coverage,
  100% critical-module coverage, and regression checks for invalid/missing evidence.
- A Linux/macOS application quality matrix and aggregate status that rejects
  failed, cancelled, or skipped dependencies; private-repository merge checks
  remain manually verified until GitHub branch protection is available.

No public application release has been published. Development installation is
available from a source checkout; PyPI and Homebrew publication come later.
