# Bound projection and rendering work without changing its meaning

Status: Accepted for the source snapshot described here.
Migrated: 2026-11-01.

## Context

Large tables, log wrapping, formatting, and repeated fixed-height status updates can consume the
UI loop even when network I/O is asynchronous.

## Decision

- Reuse immutable unchanged rows and compatible log geometry, prune caches to current
  identities, and yield between limited batches. Keep expensive decoding/projection/formatting
  in explicitly drained workers.
- Avoid layout changes for unchanged or fixed-height labels. Keep native full behavior for
  unknown/mutable renderables, changed geometry, or incompatible ordering.

## Consequences

- Selection, typed sorting, search, wrap, and cancellation semantics remain unchanged.
  Generation checks still reject obsolete publication.
- Line/cache bounds are not a universal memory or latency guarantee. Original runtime workloads
  and failure evidence remain separate verification requirements.

An age-only repaint preserves feedback attached to the current immutable view.
A new view/connection observation may replace that feedback, so ordinary refresh
does not overwrite a rejected command with an unrelated transient status.

## Source and related decisions

This record extracts an implemented decision from the [previous architecture
log](../../engineering/architecture-history/README.md). It does not requalify its historical
measurements.

- [src/kuberich/services/pods.py](../../src/kuberich/services/pods.py)
- [src/kuberich/services/filtering.py](../../src/kuberich/services/filtering.py)
- [src/kuberich/ui/log_body.py](../../src/kuberich/ui/log_body.py)
- [src/kuberich/ui/presentation.py](../../src/kuberich/ui/presentation.py)
- [src/kuberich/ui/chrome.py](../../src/kuberich/ui/chrome.py)
