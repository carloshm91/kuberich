# Keep domain decisions independent of terminal and SDK types

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

The same access, identity, parsing, and recovery decisions must work in services, CLI entry
points, and terminal views.

## Decision

- Keep domain models and decisions free of Textual and generated SDK objects.
- Compose application services with explicit transport/process adapters. Let the UI render
  observations and invoke services; config and diagnostics remain separate boundary modules.

## Consequences

- Pure decisions can be tested without an application or cluster. Transport and terminal
  contracts still require their own behavioral tests.
- The current App remains a substantial composition and event-routing owner. This decision does
  not claim that every application operation has already moved to a separate controller.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../../engineering/architecture-history/README.md). It does not requalify its historical
measurements.

- [src/kuberich/domain/resources.py](../../src/kuberich/domain/resources.py)
- [src/kuberich/domain/targets.py](../../src/kuberich/domain/targets.py)
- [src/kuberich/services/workspace.py](../../src/kuberich/services/workspace.py)
- [src/kuberich/ui/app.py](../../src/kuberich/ui/app.py)
