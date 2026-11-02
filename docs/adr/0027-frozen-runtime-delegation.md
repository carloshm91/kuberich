# Separate frozen loader state from external program environments

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

A bundled executable needs its internal loader state, but passing that state to kubectl, an
editor, or a credential helper can load incompatible libraries.

## Decision

- Dispatch reserved internal PTY/credential children before ordinary CLI/UI imports. Frozen
  binaries re-execute themselves for internal launchers; source/wheel paths use their isolated
  interpreter.
- Only the final external command receives a copied environment with bundle-injected library
  paths removed or the previous Linux path restored. Do not rewrite application/session
  environments globally.

## Consequences

- Standalone sessions do not require an external Python merely to launch their internal child.
- Source tests cannot qualify a frozen binary. Clean-target installed/native tests must exercise
  the exact built artifact and its actual delegation.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../../engineering/architecture-history/README.md). It does not requalify its historical
measurements.

- [scripts/build_standalone.py](../../scripts/build_standalone.py)
- [src/kuberich/runtime.py](../../src/kuberich/runtime.py)
- [src/kuberich/adapters/credential_child.py](../../src/kuberich/adapters/credential_child.py)
- [src/kuberich/services/processes.py](../../src/kuberich/services/processes.py)

Related: [0008](0008-external-process-ownership.md), [0031](0031-standard-python-packaging.md).
