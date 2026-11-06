# ADR 0038: Container configuration provenance

Status: accepted for the current development implementation.

## Context

A container can combine literal assignments, several configuration sources,
Downward API selectors and dependent values. Current API objects cannot prove
what a running process consumed at startup. Reading many sources also creates
freshness and lifetime boundaries that a single configuration-key view does not
cover.

## Decision

Use one finite inspector per captured Pod UID and container family/name. The
[domain records](../../src/kuberich/domain/container_inspection.py) contain only
metadata, image facts and private content bindings. The
[pure resolver](../../src/kuberich/domain/container_environment.py) preserves
declaration order, per-use optionality, unknown-source barriers and backward,
one-pass dependencies. It resolves only a selected entry's dependency closure.
Values and raw objects stay in repr-suppressed temporary work, outside public
snapshots, default presentation, diagnostics and exports.

The [service](../../src/kuberich/services/container_inspection.py) uses captured
core resource descriptors and the existing per-context client. Collection reads
the Pod, bounded referenced sources and the Pod again. Disclosure is a separate
one-use intent with fresh UID, opaque version and canonical content comparisons.
Publication rechecks its operation and intent generation after owned awaits.
A known changed binding retires only its matching snapshot; a newer reload
survives an old request's failure. Retiring a cursor intent preserves valid
metadata.

Missing optional assignments preserve earlier bindings. Forbidden or unknown
sources do not become empty maps. Unsupported runtime fields and node defaults
remain unresolved. Quantities follow the bounded Kubernetes reference semantics
instead of a generic division. Declared and status image fields keep their
origins; runtime identifiers remain opaque.

One owner bounds reads, references, rows, encoded input, metadata and resolution
work. The transport's typed body-limit failure distinguishes exhausted input
allowance from HTTP or malformed-response failures. A publication deadline does
not imply an executor thread stopped: cancellation drains transport and parser
work before the client or credential lifetime ends.

The [nested screen](../../src/kuberich/ui/container_inspection.py) hides values
on selection, section, suspension, reload and close. Reveal and copy use separate
intents. Known stale configuration retains a Reload-required state until a new
index succeeds. Metadata export reuses ADR 0037's captured-origin lease, which
survives its own review overlay while the originating snapshot remains valid.
The inspector blocks application screenshots anywhere in the screen stack.

## Consequences and limits

Inspection describes current API configuration rather than observed process
environment. It requires no process exec, registry query, scanner or additional
watch. Source versions may change after the last read; this is a checked interval,
not a transactional multi-object snapshot.

The UI retains parent selection and viewport, while the operation owner retains
detached screens until their cleanup callback. Existing read-only policy permits
these reads and explicit disclosures. Dedicated semantic, real HTTP, Pilot,
terminal, installed-artifact and disposable-cluster tests verify different
boundaries; coverage alone does not establish them. Measured results belong in
the [acceptance record](../internal/acceptance/container-inspection.md).
