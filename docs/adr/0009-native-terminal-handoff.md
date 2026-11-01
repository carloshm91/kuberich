# Lease and restore the native terminal for explicit foreground tools

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

An editor, provider login, or foreground local plugin needs terminal control that cannot be
safely shared with a rendering Textual application.

## Decision

- Use public Textual suspension with a POSIX terminal lease covering foreground process group,
  terminal attributes, and temporary signal handling.
- Finish process cleanup and resume the application before propagating failure or cancellation.
  Native handoffs are explicit and serialized.

## Consequences

- Normal event handlers remain asynchronous. The deliberately suspended terminal is an explicit
  interaction boundary.
- A revoked SSH TTY can be impossible to restore; recognize that specific loss without
  concealing failures on a live terminal. Headless launches cannot perform a native handoff.

The mounted native application owns and restores its signal handlers. The first
termination signal chooses the exit status; native handoff defers application
exit until suspension resumes. A revoked output stream is discarded at hangup
without hiding restoration failures on a still-live terminal.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../internal/architecture-history/README.md). It does not requalify its historical
measurements.

- [src/kuberich/adapters/terminal.py](../../src/kuberich/adapters/terminal.py)
- [src/kuberich/ui/handoff.py](../../src/kuberich/ui/handoff.py)
- [src/kuberich/ui/shutdown.py](../../src/kuberich/ui/shutdown.py)
- [src/kuberich/services/processes.py](../../src/kuberich/services/processes.py)

Related: [0010](0010-embedded-container-terminal.md), [0008](0008-external-process-ownership.md).
