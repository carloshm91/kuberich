# Separate tested release preparation from artifact publication

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

A release retry must not rebuild different bytes, infer approval from a local merge, or publish
a version outside the reviewed phase map.

## Decision

- Keep release decisions and I/O tooling outside the installed runtime. Validate the cumulative
  task graph, exact source/checks/protections, artifact identities, and authored release notes
  before activation.
- Confine publication credentials and OIDC/write privileges to the protected release job. Reuse
  the approved immutable artifact bundle and verify retries against its frozen body and assets.

## Consequences

- A passing development matrix or local candidate is not production publication approval.
- PyPI, native downloads, and the project tap have distinct delivery boundaries. A formula
  update remains a reviewed repository change.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../internal/architecture-history/README.md). It does not requalify its historical
measurements.

- [scripts/release_policy.py](../../scripts/release_policy.py)
- [scripts/release.py](../../scripts/release.py)
- [docs/releases.md](../../docs/releases.md)

Related: [0031](0031-standard-python-packaging.md), [0030](0030-owned-verification-fixtures.md).
