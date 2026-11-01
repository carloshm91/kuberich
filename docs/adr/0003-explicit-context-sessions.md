# Use a separate explicit connection for each selected context

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

Process-global Kubernetes configuration and implicit current-context selection can redirect an
asynchronous action when another view changes scope.

## Decision

- Build each connection from the chosen kubeconfig catalogue and invocation overrides. Give it a
  client identity, context generation, and explicit cleanup path.
- Namespace/resource changes replace view scope; context changes and retries replace the
  connection. Do not rewrite kubeconfig merely to select a view.

## Consequences

- Results and actions must match their client and view generation before publication.
- Kubeconfig context editing is a separate reviewed local operation. It is not an effect of
  ordinary navigation.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../../engineering/architecture-history/README.md). It does not requalify its historical
measurements.

- [src/kuberich/config/catalog.py](../../src/kuberich/config/catalog.py)
- [src/kuberich/domain/connections.py](../../src/kuberich/domain/connections.py)
- [src/kuberich/services/sessions.py](../../src/kuberich/services/sessions.py)
- [src/kuberich/adapters/kubernetes.py](../../src/kuberich/adapters/kubernetes.py)

Related: [0004](0004-credential-helpers-and-delegation.md), [0007](0007-active-view-generations.md).
