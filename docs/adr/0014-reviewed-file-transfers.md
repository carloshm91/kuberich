# Validate copied trees privately before destination publication

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

A container archive can contain traversal, links, special files, excessive metadata, or changes
to a destination that the user did not approve.

## Decision

- Review explicit absolute paths and replacement intent. Snapshot uploads privately; scan
  download archive headers and extract only validated regular trees in private staging.
- Retain no-follow parent descriptors and reviewed file identity for publication. Do not merge
  existing directories or automatically retry remote uploads.

## Consequences

- Cancellation removes private partial downloads, but an interrupted upload can leave partial or
  completed remote files.
- Directory publication and remote path checks cannot provide a transaction against every
  concurrent filesystem change. The result must disclose those limits.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../internal/architecture-history/README.md). It does not requalify its historical
measurements.

- [src/kuberich/domain/transfers.py](../../src/kuberich/domain/transfers.py)
- [src/kuberich/services/transfers.py](../../src/kuberich/services/transfers.py)
- [src/kuberich/ui/transfers.py](../../src/kuberich/ui/transfers.py)
- [src/kuberich/domain/processes.py](../../src/kuberich/domain/processes.py)

Related: [0008](0008-external-process-ownership.md), [0022](0022-default-redaction-and-explicit-disclosure.md).
