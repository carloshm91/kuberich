# Keep keyboard ownership and frame geometry predictable

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

Queued input can arrive immediately after a focus change. Resource tables and nested views
should not move their frames when a shortcut, suggestion, or status changes.

## Decision

- Give inputs their printable keys and apply navigation to the focused owner. Keep the command
  bar bordered and completion inline, with explicit Tab or cycling-and-Enter acceptance.
- Share stable header/input/frame/trail geometry across local contexts, namespaces, resources,
  containers, logs, and inspection. Keep context rows local until Enter deliberately connects.

## Consequences

- Native arrows and page keys remain available alongside familiar additional navigation keys.
  Escape first leaves input, then clears a filter, then returns.
- An embedded live terminal retains its earlier remote-key route. Compact layout must expose
  clipped information through help rather than inventing another navigation mode.

The current inline suffix uses a narrow pinned Textual Input rendering boundary.
Its cursor, selection, literal text, and queued-input controls must be rechecked on
framework upgrades; the design does not claim complete public-API independence.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../../engineering/architecture-history/README.md). It does not requalify its historical
measurements.

- [src/kuberich/ui/commands.py](../../src/kuberich/ui/commands.py)
- [src/kuberich/ui/chrome.py](../../src/kuberich/ui/chrome.py)
- [src/kuberich/ui/keybindings.py](../../src/kuberich/ui/keybindings.py)
- [src/kuberich/ui/nested.py](../../src/kuberich/ui/nested.py)
- [src/kuberich/ui/contexts.py](../../src/kuberich/ui/contexts.py)
