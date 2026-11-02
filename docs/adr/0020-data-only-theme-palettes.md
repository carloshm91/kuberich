# Treat theme configuration as validated color data

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

Global/context appearance and previews should be customizable without loading executable CSS or
persisting temporary changes.

## Decision

- Validate color palettes, contrast, theme names, and context references in domain models.
  Convert valid values through Textual theme APIs.
- Keep preview/cancel separate from explicit save. Apply environment/context/global precedence
  and session-only inversion without rewriting the terminal palette.

## Consequences

- Unknown or invalid theme choices leave source files intact and use visible working fallback
  behavior.
- Terminal-default background is allowed, but its contrast cannot be measured because the
  application does not know the actual terminal surface.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../../engineering/architecture-history/README.md). It does not requalify its historical
measurements.

- [src/kuberich/domain/appearance.py](../../src/kuberich/domain/appearance.py)
- [src/kuberich/ui/appearance.py](../../src/kuberich/ui/appearance.py)
- [src/kuberich/services/appearance.py](../../src/kuberich/services/appearance.py)

Related: [0017](0017-versioned-local-preferences.md), [0024](0024-transactional-css-parse-reuse.md).
