# Admit aggregate log sources through controller identity

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

Matching labels alone do not prove workload ownership, and containers within the same pod can
have different start and previous-instance availability.

## Decision

- Resolve Deployment/ReplicaSet/Pod and CronJob/Job/Pod membership through controller references
  and UIDs. Establish log eligibility from each container instance.
- Own membership watches and at most eight readers, with stable source identities and separate
  per-source/shared retention limits. Source filtering changes presentation rather than reader
  admission.

## Consequences

- A recreated pod receives a new identity. Ended streams do not silently replay when another
  source changes.
- Generation, admission, formatting, and export are drained before client cleanup; the App keeps
  a closing aggregate registered until that work finishes.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../internal/architecture-history/README.md). It does not requalify its historical
measurements.

- [src/kuberich/domain/aggregate_logs.py](../../src/kuberich/domain/aggregate_logs.py)
- [src/kuberich/domain/log_json.py](../../src/kuberich/domain/log_json.py)
- [src/kuberich/services/aggregate_logs.py](../../src/kuberich/services/aggregate_logs.py)
- [src/kuberich/ui/aggregate_logs.py](../../src/kuberich/ui/aggregate_logs.py)

Related: [0011](0011-single-container-log-streams.md), [0007](0007-active-view-generations.md).
