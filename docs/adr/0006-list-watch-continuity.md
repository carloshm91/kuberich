# Keep collection snapshots consistent and watch versions opaque

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

A partial list, expired watch checkpoint, or permission denial must not appear as a successful
empty collection.

## Decision

- Read a complete consistent paginated snapshot before watching its collection resourceVersion.
  Maintain UID-indexed WatchState and treat versions as opaque strings.
- Resume retryable interruptions from the last applied checkpoint; relist on expiration and stop
  on nonretryable permission/protocol failures. A slow sink pulls one event at a time.

## Consequences

- Replay memory, collection size, and retry delays have explicit limits. There is no unbounded
  producer queue.
- A temporary outage keeps the previous rows marked stale. A successful empty list remains
  distinct from a failure.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../../engineering/architecture-history/README.md). It does not requalify its historical
measurements.

- [src/kuberich/domain/watches.py](../../src/kuberich/domain/watches.py)
- [src/kuberich/services/watches.py](../../src/kuberich/services/watches.py)
- [src/kuberich/services/resources.py](../../src/kuberich/services/resources.py)
- [src/kuberich/adapters/kubernetes.py](../../src/kuberich/adapters/kubernetes.py)
