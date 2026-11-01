# Own external commands through one explicit process service

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

Helpers, editors, plugins, kubectl sessions, and clipboard programs can outlive their immediate
waiter or leave descendants holding pipes.

## Decision

- Capture executable arguments, environment, directory, purpose, and mode before asynchronous
  preparation. Use argument vectors rather than interpolated shell strings.
- ProcessRunner owns startup, pipes or PTYs, output limits, deadlines, and process-group
  cleanup. Apply read-only policy before executable lookup and process creation.

## Consequences

- Cancelling a waiter does not detach background work. The manager or caller retains
  responsibility until cleanup completes.
- Plugin trust classification cannot be reused to authorize arbitrary non-plugin commands.
  Shared cleanup must preserve failures instead of reporting success while work remains.

Darwin can deny a group signal while its members are exiting. The runtime uses
only finite nonblocking zero-signal probes after that denial; only ESRCH confirms
disappearance. A live or persistently denied group remains a cleanup failure.
An exited leader or EPERM alone is not evidence that its descendants are gone.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../internal/architecture-history/README.md). It does not requalify its historical
measurements.

- [src/kuberich/domain/processes.py](../../src/kuberich/domain/processes.py)
- [src/kuberich/services/processes.py](../../src/kuberich/services/processes.py)
- [src/kuberich/adapters/credentials.py](../../src/kuberich/adapters/credentials.py)
- [src/kuberich/services/access.py](../../src/kuberich/services/access.py)
- [src/kuberich/runtime.py](../../src/kuberich/runtime.py)

Related: [0009](0009-native-terminal-handoff.md), [0027](0027-frozen-runtime-delegation.md).
