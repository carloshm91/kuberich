# Keep pod shells inside an owned embedded terminal

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

Container interaction should keep the selected target and parent workspace visible while full-
screen remote programs receive real terminal input and resize events.

## Decision

- Run kubectl exec/attach through an owned nonblocking PTY and the pinned, unmodified Pyte
  emulator. Keep Textual active and render literal styled cells.
- Route remote keys before global bindings, except explicit local close/quit controls. Keep
  normal/alternate screens, local history, input, and control parsing within stated limits.

## Consequences

- Remote OSC and other control strings do not reach the host terminal or clipboard. History
  review is a local frozen view while the remote process continues.
- Exec and attach still target server names: a pre-launch UID check cannot create an atomic
  server-side UID precondition. Emulator support is deliberately narrower than every terminal
  protocol.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../internal/architecture-history/README.md). It does not requalify its historical
measurements.

- [src/kuberich/adapters/pty.py](../../src/kuberich/adapters/pty.py)
- [src/kuberich/adapters/emulator.py](../../src/kuberich/adapters/emulator.py)
- [src/kuberich/domain/terminal_history.py](../../src/kuberich/domain/terminal_history.py)
- [src/kuberich/ui/terminal.py](../../src/kuberich/ui/terminal.py)

Related: [0009](0009-native-terminal-handoff.md), [0027](0027-frozen-runtime-delegation.md).
