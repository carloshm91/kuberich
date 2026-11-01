# Release discarded native table cache rings promptly

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

Native LRU rings can retain discarded table rendering values until a later cyclic collection,
increasing temporary retention during view churn.

## Decision

- Use an application-owned native LRU subclass for FrameTable caches. Preserve lookup,
  insertion, eviction, counters, capacities, and key ordering while unlinking discarded rings on
  clear/discard/retirement.
- Apply the adapter only to KubeRich tables and compare it with the pinned native
  implementation.

## Consequences

- The adapter must preserve actual cache identities and native behavior; replacing the cache
  with a mutable debug map is not equivalent.
- This remains a narrow private framework boundary requiring upgrade qualification. It does not
  justify global GC changes or a relaxed responsiveness limit.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../internal/architecture-history/README.md). It does not requalify its historical
measurements.

- [src/kuberich/ui/table_cache.py](../../src/kuberich/ui/table_cache.py)
- [src/kuberich/ui/presentation.py](../../src/kuberich/ui/presentation.py)

Related: [0023](0023-widget-style-cache-ownership.md), [0026](0026-incremental-rendering-and-cooperative-work.md).
