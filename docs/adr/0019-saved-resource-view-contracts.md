# Pin saved navigation to actual resource and input contracts

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

An alias, changed server column, or local template must not reinterpret values as executable
code or silently apply a layout to another resource.

## Decision

- Use literal command aliases and validated per-view keys. Keep fixed safety actions reserved
  and reject cycles, collisions, and ambiguous preset arguments.
- Identify saved views by context/GVR and printer signature. Read jump templates as field paths
  only, yielding a local selector for the target view.

## Consequences

- Column visibility is a display choice, not a confidentiality boundary. Typed sorting can use a
  hidden field.
- Changed printer schemas fall back without deleting the old preference. Unknown template data
  cannot execute Python, shell expansion, or arbitrary expressions.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../../engineering/architecture-history/README.md). It does not requalify its historical
measurements.

- [src/kuberich/domain/aliases.py](../../src/kuberich/domain/aliases.py)
- [src/kuberich/domain/keyboard.py](../../src/kuberich/domain/keyboard.py)
- [src/kuberich/domain/resource_preferences.py](../../src/kuberich/domain/resource_preferences.py)
- [src/kuberich/domain/jumps.py](../../src/kuberich/domain/jumps.py)
- [src/kuberich/config/navigation.py](../../src/kuberich/config/navigation.py)
