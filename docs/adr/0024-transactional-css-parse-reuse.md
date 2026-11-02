# Reuse complete stylesheet parses without partial publication

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

Theme changes can revisit identical variable snapshots while native reparsing allocates
substantial temporary graphs. Invalid CSS must still fail atomically.

## Decision

- Keep a small per-owner cache of exact complete variable snapshots and the native source-parse
  cache semantics.
- Reparse through a fresh transactional stylesheet and publish only after successful parsing.
  Copies and applications retain independent cache ownership.

## Consequences

- Source location, priority, scope, and variable changes remain part of validity; a similar-
  looking palette is not an exact cache hit.
- Errors preserve the previous published rule semantics and allow later recovery. The
  optimization changes no global stylesheet or GC policy.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../../engineering/architecture-history/README.md). It does not requalify its historical
measurements.

- [src/kuberich/ui/style_cache.py](../../src/kuberich/ui/style_cache.py)
- [src/kuberich/ui/app.py](../../src/kuberich/ui/app.py)

Related: [0023](0023-widget-style-cache-ownership.md), [0026](0026-incremental-rendering-and-cooperative-work.md).
