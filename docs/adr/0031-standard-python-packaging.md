# Build standard Python artifacts with one explicit backend

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

Contributors need a reproducible environment and users need installable wheels, source archives,
and independently checked native distribution channels.

## Decision

- Use uv for locked development environments and build invocation, with Hatchling as the
  declared wheel/sdist backend.
- Select runtime modules, TCSS, typing assets, metadata, and licenses explicitly. Keep
  development tooling and private files out of installed payloads.

## Consequences

- A complete wheel/sdist payload and equivalent rebuild are checked rather than inferred from a
  successful import.
- Native archives include a runtime and required notices; Homebrew has its own dependency/bottle
  contract. Installed and upgrade behavior require their actual channel tests.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../internal/architecture-history/README.md). It does not requalify its historical
measurements.

- [pyproject.toml](../../pyproject.toml)
- [uv.lock](../../uv.lock)
- [tests/packaging/test_artifacts.py](../../tests/packaging/test_artifacts.py)
- [tests/packaging/test_distribution.py](../../tests/packaging/test_distribution.py)
- [docs/installation.md](../../docs/installation.md)
