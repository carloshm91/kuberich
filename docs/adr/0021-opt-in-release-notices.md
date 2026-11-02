# Make release discovery optional and non-executable

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

An update notice must not turn a terminal launch or offline local command into an implicit
download, installation, or authenticated request.

## Decision

- Keep checks off by default. Use an unauthenticated public stable-release read with a short
  deadline, response bound, validated version/URL, and private finite-age cache.
- Expose verified/cached state in About and a version notice. Failures do not prevent launch,
  and local info/help/version/config-check remain offline.

## Consequences

- A notice never downloads or executes packages. The user upgrades through the installation
  channel.
- The cache is a performance convenience, not release authorization or a guarantee that every
  network configuration can reach GitHub.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../../engineering/architecture-history/README.md). It does not requalify its historical
measurements.

- [src/kuberich/domain/releases.py](../../src/kuberich/domain/releases.py)
- [src/kuberich/services/updates.py](../../src/kuberich/services/updates.py)
- [src/kuberich/ui/appearance.py](../../src/kuberich/ui/appearance.py)

Related: [0017](0017-versioned-local-preferences.md), [0029](0029-immutable-release-activation.md).
