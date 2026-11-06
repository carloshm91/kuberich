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

## Artifact browser width invalidation

Pinned Textual 8.2.8 can paint a fixed-height row before idle column measurement.
Its cell, row and line cache keys omit the column widths; later automatic sizing
does not invalidate that earlier paint. A controlled public-API interleaving
observes the correct filename width alongside its stale truncated rendering.

Only [ArtifactTable](../../src/kuberich/ui/artifact_browser.py) adapts the native
`_update_dimensions(new_rows)` boundary. It snapshots actual rendered widths,
calls the native method once without consuming its row iterable, and clears
inherited render caches with an explicit refresh only when widths change.
Native measurement, data, cursor, scrolling and cache ownership remain intact.
Other tables keep their existing behavior.

This adds a private compatibility boundary under the existing exact pin. Qualify
early-render/idle interleavings, real browser scan/filter publication and source
and installed PTYs at both terminal sizes. Remove this override when the same
visible-text controls pass against the selected native Textual implementation
without it; the stable private-API removal task retains that obligation.
