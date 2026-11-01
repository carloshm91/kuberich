# Load and execute only explicitly configured local plugins

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

User programs can access files, credentials, and clusters with the launching user permissions.
Loading a definition is not a sandbox or a safety classification.

## Decision

- Load explicit versioned global/context definitions and locations, with no cluster or ambient-
  directory executable discovery. Expand variables once into literal argv/environment.
- Use typed input, one-use review, shared process ownership, and explicit
  trusted_read_only/dangerous checks. Background ownership belongs to the plugin manager;
  foreground output belongs to the native terminal.

## Consequences

- Read-only mode admits only an explicitly trusted, non-dangerous definition. It does not infer
  safety from the command name.
- K9s YAML is not a drop-in parser format. Compatibility adaptations and external dependencies
  remain separate from native application features.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../../engineering/architecture-history/README.md). It does not requalify its historical
measurements.

- [src/kuberich/domain/plugins.py](../../src/kuberich/domain/plugins.py)
- [src/kuberich/config/plugins.py](../../src/kuberich/config/plugins.py)
- [src/kuberich/adapters/plugin_files.py](../../src/kuberich/adapters/plugin_files.py)
- [src/kuberich/services/plugins.py](../../src/kuberich/services/plugins.py)
- [src/kuberich/ui/plugins.py](../../src/kuberich/ui/plugins.py)

Related: [0004](0004-credential-helpers-and-delegation.md), [0008](0008-external-process-ownership.md).
