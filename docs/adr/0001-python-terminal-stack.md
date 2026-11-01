# Build the terminal application with Python and Textual

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

A Kubernetes resource browser needs responsive tables, focused keyboard input, streaming output,
and testable terminal interactions. Python is the project contribution language.

## Decision

- Use CPython 3.12–3.14 and Textual for the terminal application. Keep Kubernetes behavior in
  application modules rather than assuming the framework provides it.
- Use kubernetes-asyncio for the explicit client transport and maintained Kubernetes API
  coverage. Use an owned PTY and the pinned Pyte emulator for embedded interactive sessions.

## Consequences

- Textual supplies layout, widgets, input, and Pilot; KubeRich supplies authentication, watch
  recovery, target identity, process ownership, and releases.
- Go terminal frameworks and Rust/Ratatui remain alternatives if measured requirements expose an
  unsolved language or client gap. They are not parallel implementations.

## Alternatives recorded in the baseline

| Option | Recorded tradeoff |
| --- | --- |
| Python + Textual | Chosen widgets, layout, and testing fit for Python contributors |
| Python + prompt_toolkit | Strong command editing; more custom work for a resource browser |
| Python + curses/urwid | Viable, with more application layout/state/test infrastructure |
| Go + tview/Bubble Tea | Strong native distribution/client-go fit; changes contribution language |
| Rust + Ratatui | More low-level control, with higher implementation cost for this project |

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../internal/architecture-history/README.md). It does not requalify its historical
measurements.

- [pyproject.toml](../../pyproject.toml)
- [src/kuberich/ui/app.py](../../src/kuberich/ui/app.py)
- [src/kuberich/adapters/kubernetes.py](../../src/kuberich/adapters/kubernetes.py)
- [src/kuberich/adapters/emulator.py](../../src/kuberich/adapters/emulator.py)
