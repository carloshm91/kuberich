# Manage forwards as connection-owned TCP sessions

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

Local listeners must not start merely because an annotation is listed, and a stale resource or
context must not keep an unintended tunnel alive.

## Decision

- Capture resource UID, numeric port intent, bind address, and connection before launch. Require
  explicit remote-bind approval and observe all actual listener readiness.
- Keep forwards with their connection across view/namespace changes; stop them on replacement or
  exit. Reconnect only an opted-in previously ready child within the stated attempt limit.

## Consequences

- Dynamic local ports and Service backends can change on reconnection; report observed ports
  separately from requested values.
- Annotations cannot grant local permission. UID checks reduce name-recreation races without
  making kubectl server selection atomic.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../../engineering/architecture-history/README.md). It does not requalify its historical
measurements.

- [src/kuberich/domain/forward_presets.py](../../src/kuberich/domain/forward_presets.py)
- [src/kuberich/config/forwarding.py](../../src/kuberich/config/forwarding.py)
- [src/kuberich/services/port_forwards.py](../../src/kuberich/services/port_forwards.py)
- [src/kuberich/ui/port_forwards.py](../../src/kuberich/ui/port_forwards.py)

Related: [0003](0003-explicit-context-sessions.md), [0008](0008-external-process-ownership.md).
