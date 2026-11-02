# Scope rendering caches to their application and widget owners

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

Native cache keys can retain renderer instances or widget graphs after a screen is removed,
making ordinary repeated navigation accumulate unreachable work.

## Decision

- Keep the application-specific style cache and component-node reuse scoped to KubeRich objects.
  Use immutable color values for shared rendering computations rather than renderer instances.
- Retain native composition/reset behavior and validate theme, focus, resize, inline styles, and
  removal against pinned native controls.

## Consequences

- This source still has narrow private Textual integration boundaries. They are explicit upgrade
  risks, not claims of public-API independence.
- No global Textual monkeypatch or garbage-collection threshold change is used. Cache changes do
  not by themselves prove a runtime latency target.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../internal/architecture-history/README.md). It does not requalify its historical
measurements.

- [src/kuberich/ui/style_cache.py](../../src/kuberich/ui/style_cache.py)
- [src/kuberich/ui/app.py](../../src/kuberich/ui/app.py)
- [src/kuberich/ui/presentation.py](../../src/kuberich/ui/presentation.py)

Related: [0024](0024-transactional-css-parse-reuse.md), [0025](0025-native-table-cache-retirement.md).
