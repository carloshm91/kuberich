# Publish only observations belonging to the current view

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

Rapid context/resource changes can leave old requests, parsers, and UI callbacks finishing after
the user has selected another view.

## Decision

- WorkspaceService coalesces selection intent, cancels and awaits obsolete work, and publishes
  observations through a generation-checked ViewStore.
- Subscriptions hold one replaceable pending observation rather than an event history. UI
  consumers reject old revisions before applying rows or restoring a viewport.

## Consequences

- Selection invalidates old snapshots immediately. An old error cannot overwrite a newer
  successful connection.
- Closing a view or client must await its work; hiding a screen is not proof that its resource
  ownership ended.

An accepted nested scope command drains covered read owners before dispatch.
A rejected command leaves the current view and streams running. Resource actions
keep the originating UID rather than following a changed hidden table cursor.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../internal/architecture-history/README.md). It does not requalify its historical
measurements.

- [src/kuberich/domain/views.py](../../src/kuberich/domain/views.py)
- [src/kuberich/services/workspace.py](../../src/kuberich/services/workspace.py)
- [src/kuberich/services/sessions.py](../../src/kuberich/services/sessions.py)
- [src/kuberich/ui/app.py](../../src/kuberich/ui/app.py)
