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

## Current implementation notes

The current [phase runner](../../scripts/qualification_runner.py) and
[stage catalog](../../scripts/qualification.py) run the full-tree private-access
check and actual startup validator before the complete suite. Runtime controls
and independent coverage gates remain required. Missing platform, owned-cluster,
or repetition evidence stays pending; an engineering preview is not a release.
Inputs stay frozen during each command, and the runner drains its captured process
group even after the leader exits. Only verified group absence establishes cleanup.

The [canonical release fixture](../../tests/packaging/conftest.py) retains its own
command log and available partial audit output after generation fails, in a
separate per-attempt directory with mode 0700. A retention error cannot replace
the original failure. A successful ordinary audit is not evidence for a failed
canonical attempt; retaining output does not diagnose the producer's cause.

For 0.x, startup and runtime/collection latency observations keep their unchanged
targets and report unmet values honestly. `--strict-startup` and
`KUBERICH_STRICT_RUNTIME_BUDGETS=1` enforce their original limits explicitly;
actual source major 1 and later, including prereleases, enforce them automatically.
RSS, forbidden-import absence, valid output/source/frames, deadlines, resource
bounds, functionality and owned cleanup remain hard gates. Negative latency
controls remain strict. See the current [quality policy](../quality.md).
These current notes do not attribute later gates to the archived source snapshot.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../internal/architecture-history/README.md). It does not requalify its historical
measurements.

- [tests/conftest.py](../../tests/conftest.py)
- [scripts/owned_kind.py](../../scripts/owned_kind.py)
- [docs/quality.md](../../docs/quality.md)
- [scripts/check_coverage.py](../../scripts/check_coverage.py)
