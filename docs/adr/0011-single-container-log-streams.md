# Separate log delivery, retained history, and viewport following

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

Watching resources and reading container output have different recovery semantics. Scrolling
older output must not silently pause delivery or replay a finished stream.

## Decision

- Validate the selected pod/container, frame and sanitize UTF-8 output, and consume sequentially
  with backpressure. Do not automatically replay an opened or ended log stream.
- Keep retained line identities and byte/line limits separate from follow, pause, search, marks,
  wrap, and explicit export. Changing read options closes the old stream before reopening.

## Consequences

- A user can pause reception or leave follow independently. Dropped/rotated output cannot be
  recovered from the local buffer.
- Save/copy uses sanitized retained output and rechecks target validity. A requested file save
  can finish during graceful close.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../../engineering/architecture-history/README.md). It does not requalify its historical
measurements.

- [src/kuberich/domain/logs.py](../../src/kuberich/domain/logs.py)
- [src/kuberich/domain/log_view.py](../../src/kuberich/domain/log_view.py)
- [src/kuberich/services/logs.py](../../src/kuberich/services/logs.py)
- [src/kuberich/services/log_export.py](../../src/kuberich/services/log_export.py)
- [src/kuberich/ui/logs.py](../../src/kuberich/ui/logs.py)
