# Kubetrol

A keyboard-driven Kubernetes terminal UI, built with Python and Textual.

Inspired by [K9s](https://k9scli.io/). Built by Python enthusiasts.

Kubetrol aims to make browsing resources, investigating failures, following logs,
and managing workloads comfortable from your terminal, including over SSH.
It is an independent project and is not affiliated with K9s.
All Kubetrol capabilities will be open source under MIT, with no paid feature tiers.

## Project status

**Planning and repository preparation. No application release is available yet.**

The first release, **0.0.1**, will provide a usable resource browser, live pod
updates, filtering, resource details, container logs, and interactive exec.
Linux and macOS are the initial supported operating systems. Textual Web is
outside the product scope.

## Installation

Installation instructions will be published after the first release passes its
release checklist. The planned first-release channels are PyPI (uv/pipx) and
the project's Homebrew tap. Standalone Linux and macOS executables are planned
for 0.1.0. These channels are tracked work, not currently available downloads.

## Development

- [First preview checkpoints](docs/first-preview.md)
- [Roadmap and release milestones](docs/roadmap.md)
- [Issue index and implementation order](docs/backlog.md)
- [Complete K9s capability audit](docs/k9s-parity.md)
- [CLI and authentication compatibility](docs/k9s-cli.md)
- [Architecture decisions](docs/architecture.md)
- [Contribution workflow](CONTRIBUTING.md)
- [Testing and coverage policy](docs/quality.md)
- [Versioning, tags, and release procedure](docs/releases.md)
- [Distribution and platform support](docs/distribution.md)
- [Development assistants and skills](docs/agent-setup.md)

Application coverage must reach **at least 90% for lines and branches separately**.
The target is 100% for critical logic. There is no application code yet, so an
application coverage percentage would currently be misleading.

## Community

Use [GitHub issues](https://github.com/carloshm91/kubetrol/issues) for bugs and
feature proposals. Please read [CONTRIBUTING.md](CONTRIBUTING.md),
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), and [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE). Copyright (c) 2026 Carlos Herrera and Kubetrol contributors.
