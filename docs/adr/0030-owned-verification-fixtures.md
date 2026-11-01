# Use explicit disposable fixtures and preserve original failures

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

Contract, terminal, cluster, and timing evidence can become misleading if it uses an active user
context or changes a failing workload until a rerun passes.

## Decision

- Use explicit owned loopback APIs, PTYs/processes, and disposable kind clusters with verified
  identities and scoped cleanup. Never fall back to the maintainer active kubeconfig.
- Keep original failed logs and source inputs. Label fixture controls, diagnostics, platform
  gaps, and nonqualifying observations separately from release qualification.

## Consequences

- A recorded CrashLoop state does not reserve future server log availability. Fixture
  synchronization must not fabricate a production response or relax the actual assertion.
- Coverage supports confidence but does not replace reconnect, cancellation, permissions,
  installed artifacts, or real-terminal tests.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../../engineering/architecture-history/README.md). It does not requalify its historical
measurements.

- [tests/conftest.py](../../tests/conftest.py)
- [scripts/owned_kind.py](../../scripts/owned_kind.py)
- [docs/quality.md](../../docs/quality.md)
- [scripts/check_coverage.py](../../scripts/check_coverage.py)
