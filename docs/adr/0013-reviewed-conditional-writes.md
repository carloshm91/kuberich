# Bind each resource change to one reviewed conditional request

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

A confirmation for one resource/version must not authorize another target, a changed draft, or
an automatic retry after a lost response.

## Decision

- Capture identity and exact immutable request bytes, then require Review and separate one-use
  Confirm. Use UID/resourceVersion tests or deletion preconditions at the server boundary.
- Keep strict editor dry-run separate from Apply. Do not follow redirects, refresh-and-replay
  authentication, or blindly retry writes. Report uncertain outcomes explicitly.

## Consequences

- Conflicts need a new read and review. API acceptance does not establish rollout completion or
  dependent deletion.
- Batches have independent item outcomes rather than rollback. HPA/source-history checks and
  later changes remain separate cross-resource requests, not atomic transactions.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../internal/architecture-history/README.md). It does not requalify its historical
measurements.

- [src/kuberich/domain/operations.py](../../src/kuberich/domain/operations.py)
- [src/kuberich/domain/editing.py](../../src/kuberich/domain/editing.py)
- [src/kuberich/services/mutations.py](../../src/kuberich/services/mutations.py)
- [src/kuberich/services/workloads.py](../../src/kuberich/services/workloads.py)
- [src/kuberich/services/operations.py](../../src/kuberich/services/operations.py)

Related: [0007](0007-active-view-generations.md), [0022](0022-default-redaction-and-explicit-disclosure.md).
