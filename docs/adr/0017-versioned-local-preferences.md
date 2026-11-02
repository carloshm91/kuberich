# Keep local preferences versioned and explicit to save

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

Application preferences must stay separate from kubeconfig and must not silently persist runtime
overrides or rewrite a broken file.

## Decision

- Use a safe limited YAML loader, typed defaults, independently versioned extensions, explicit
  precedence, and atomic private-file saves. Preserve unknown root fields for forward
  compatibility.
- Keep runtime CLI/environment choices out of saved documents. Reload valid preference changes
  while retaining the last working document after invalid input.

## Consequences

- Preview/load/check do not write files. Context settings can make read-only stricter, never
  weaken another required restriction.
- Competing file changes need a fresh load before saving. Keys, mouse mode, and logs have
  documented restart boundaries.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../internal/architecture-history/README.md). It does not requalify its historical
measurements.

- [src/kuberich/config/schema.py](../../src/kuberich/config/schema.py)
- [src/kuberich/config/store.py](../../src/kuberich/config/store.py)
- [src/kuberich/config/context_settings.py](../../src/kuberich/config/context_settings.py)
- [src/kuberich/services/appearance.py](../../src/kuberich/services/appearance.py)
- [src/kuberich/ui/live_preferences.py](../../src/kuberich/ui/live_preferences.py)

Related: [0019](0019-saved-resource-view-contracts.md), [0028](0028-identity-and-preference-migration.md).
