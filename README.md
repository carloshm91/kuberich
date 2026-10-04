# Kubetrol

A keyboard-driven Kubernetes terminal UI, built with Python and Textual.

Inspired by [K9s](https://k9scli.io/). Built by Python enthusiasts.

Kubetrol aims to make browsing resources, investigating failures, following logs,
and managing workloads comfortable from your terminal, including over SSH.
It is an independent project and is not affiliated with K9s.
All Kubetrol capabilities will be open source under MIT, with no paid feature tiers.

## Project status

**The development CLI is installable from this checkout. No public application
release is available yet.**

It currently provides `--help`, `--version`, and an honest development-status
message. The terminal interface and Kubernetes connections are the next steps.

The first release, **0.0.1**, will provide a usable resource browser, live pod
updates, filtering, resource details, container logs, and interactive exec.
Linux and macOS are the initial supported operating systems. Textual Web is
outside the product scope.

## Try the development CLI

With [uv](https://docs.astral.sh/uv/getting-started/installation/) and Python
3.12, 3.13, or 3.14, run these commands from the repository:

```sh
uv sync --locked --group dev
uv run kubetrol --help
uv run kubetrol --version
uv run kubetrol
```

The last command reports the current development stage. It does not require a
kubeconfig or contact a cluster. `uv run python -m kubetrol` is also supported.

## Public installation

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
The reviewed critical modules must reach 100%. CI checks the complete production
package, changed executable lines, and critical modules independently, with tests
that demonstrate rejection of regressions. See the quality policy for check names
and the current private-repository branch-protection limitation.

## Community

Use [GitHub issues](https://github.com/carloshm91/kubetrol/issues) for bugs and
feature proposals. Please read [CONTRIBUTING.md](CONTRIBUTING.md),
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), and [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE). Copyright (c) 2026 Carlos Herrera and Kubetrol contributors.
