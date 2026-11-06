# ADR 0040: Curated resource observations

Status: accepted for the unreleased development implementation.

## Context

Discovery and server Table cells provide a generic browser, but do not establish
the meaning, confidentiality or identity of resource-specific facts. The same
plural can belong to several groups and versions. Events additionally summarize
occurrences about another object; a grouped observation has no Kubernetes UID.

## Decision

Keep [family records](../../src/kuberich/domain/curated.py) and the scaling,
policy and access extractors independent of Textual and the Kubernetes SDK.
Match group, served version, plural, kind and scope before extracting allowlisted
facts. Metadata-only and unsupported representations retain safe identity and an
explicit limitation rather than reusing printer values. The existing standard
table remains the renderer for the 18 ordinary families.

Retain a closed set of [literal destinations](../../src/kuberich/domain/curated_navigation.py):
declared references, collection predicates, relationship modes and authorization
intents. A [finite navigator](../../src/kuberich/services/curated_navigation.py)
owns one latest request and at most two bounded object reads. It uses the
injected context client, discovered descriptors, captured namespace and object
identity. It never fetches a declared URL or interpolates a shell command.
Reference resolution distinguishes an explicit cluster scope from a namespace
hint on a controller reference. Missing versions, ambiguous kinds, denied reads
and UID replacements do not silently choose another destination.

Inspectors keep their fresh GET version separately from the version observed in
the parent table. An unchanged older parent snapshot may coexist with a newer
GET; a newly observed third version invalidates the link. Versions are opaque
equality tokens. The current-origin callback runs around owned awaits and again
before a topmost inspector hands navigation back to the root. Detached screens
remain owned until their serializer, link request and navigator have drained.

Bound derived cells, combined detail rows/links and the complete serialized
detail/action payload. Display clipping never changes lookup identity. Default
details and exports conceal webhook trust bytes and sensitive arbitrary fields.
The new families remain read-only at effectful service boundaries as well as in
the available-action model; registry enrollment does not widen mutation scope.

The [Events model](../../src/kuberich/domain/events.py) retains compact facts
without freeform messages or notes. Its separate table distinguishes genuine
Event UID rows from groups by source API, type, reason and object identity.
Missing referenced UIDs stay separate, and unknown occurrence counts/times do not
become zero or a creation timestamp. One owned projection worker enforces fact
and byte limits; it creates no additional LIST/WATCH or Kubernetes client.

The root [source clock](../../src/kuberich/ui/event_source.py) timestamps actual
snapshot identity and full scope using a weak reference. Repainting, filtering,
sorting and quiet watches do not retimestamp it. Visible observation time and
export provenance use that anchor; reported occurrence time remains separate.
Actual collection completeness and connection status remain authoritative.
Grouped exports are table captures; groups never acquire a resource origin.

## Consequences

Curated navigation shares existing history, selection and viewport restoration.
Resource-specific interpretation requires explicit supported schemas; unknown
APIs still have a metadata fallback. Declaration views do not prove enforcement,
runtime environment, eviction success or historical continuity.

The [source inventory](../internal/curated-resource-inventory.json) records the
19 named families, pinned public API/menu comparison and additional menu gaps.
It does not establish complete Lens, K9s or paid-feature parity. Behavioral,
terminal, installed-artifact and disposable-cluster evidence belongs in the
[acceptance record](../internal/acceptance/curated-resources.md). Deterministic
critical modules retain complete line and branch coverage requirements.
