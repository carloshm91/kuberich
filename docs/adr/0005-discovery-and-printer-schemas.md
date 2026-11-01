# Resolve API identity through discovery and version-pinned layouts

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

Clusters serve different API versions and may reuse short aliases. Server printer columns can
change while old objects remain visible.

## Decision

- Resolve the actual group/resource/version and scope from the selected client discovery.
  Require qualification for ambiguous names rather than guessing an endpoint.
- Keep printer metadata separate from full resource records. Pin saved server-column layouts to
  their version and ordered schema signature; fall back to metadata when Table conversion is
  unavailable.

## Consequences

- A renewed schema cannot reinterpret an old positional value under a different header.
- Generic discovered views provide read-only inspection. Dedicated built-in routes retain their
  own supported actions and guards.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../internal/architecture-history/README.md). It does not requalify its historical
measurements.

- [src/kuberich/domain/resources.py](../../src/kuberich/domain/resources.py)
- [src/kuberich/domain/custom.py](../../src/kuberich/domain/custom.py)
- [src/kuberich/services/resources.py](../../src/kuberich/services/resources.py)
- [src/kuberich/ui/custom.py](../../src/kuberich/ui/custom.py)

Related: [0006](0006-list-watch-continuity.md), [0019](0019-saved-resource-view-contracts.md).
