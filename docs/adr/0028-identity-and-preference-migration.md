# Migrate application identity without duplicating runtime packages

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

A canonical command rename must not lose existing preferences or create two diverging
implementations.

## Decision

- Use kuberich for the distribution, Python package, and canonical CLI. Keep the initial
  kubetrol console alias delegated to the same entry point.
- Prefer canonical environment/default paths, read a legacy default only when the new default is
  absent, and require explicit non-overwriting config migration.

## Consequences

- Migration preserves unknown fields, source bytes, and effective relative path targets. An
  invalid existing canonical file cannot silently fall back.
- Historical measurements retain their original names in engineering records. Renaming the
  product is not authorization to publish a package, website, or release.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../../engineering/architecture-history/README.md). It does not requalify its historical
measurements.

- [pyproject.toml](../../pyproject.toml)
- [src/kuberich/config/paths.py](../../src/kuberich/config/paths.py)
- [src/kuberich/config/store.py](../../src/kuberich/config/store.py)
- [src/kuberich/config/schema.py](../../src/kuberich/config/schema.py)
