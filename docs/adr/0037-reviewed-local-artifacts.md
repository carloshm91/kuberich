# 0037: Bind local exports to frozen sources and explicit file operations

Status: implemented in development source; qualification evidence is separate

## Context

A saved resource, log excerpt or diagnostic report crosses from a changing
cluster view into a long-lived local file. The visible header can differ from
the actual collection namespace. A browser must treat a file and its metadata
as untrusted even when another KubeRich instance originally wrote it. Sensitive
export consent must not become a general permission to reveal or replace files.

## Decision

Use immutable `domain.exports` captures with independent header, collection,
identity, observation-time and presentation fields. Narrow source ports capture
already-produced data before opening the review. Resource rows provide a real
served identity; inspection documents stay already-redacted documents. Log
captures bind to the producing read, not controls whose replacement read is
still draining. A table capture requires a published current frame and conceals
arbitrary custom/server columns. Unknown screens do not fall back to capturing
an underlying resource table.

`ExportService` owns preparation, publication, reading, paging and consent.
Pure codecs validate bounded schema-versioned artifacts and reapply redaction
on read. Safe previews remain redacted even for a prepared sensitive resource.
Keep one current safe preview across destination-only edits, draining dependent
work and revoking consent before marking the fields ready again. Saving creates
a separate, fresh preparation bound to the reviewed destination; release it on
success, failure or cancellation. Path edits do not serialize a large unchanged
log snapshot again, and a failed Save does not turn the preview into a consumed
publication capability.
Support JSON contains explicit inline components and omissions, never an
arbitrary recursive archive. No export operation uploads, launches an opener
or silently writes the clipboard.

Sensitive consent is a one-use service-issued capability. Bind it to exact
capture/session/UID/version/content, purpose and destination or file identity.
Do not accept caller-constructed substitutes. Fresh resource reads enforce
normal permission and UID/version checks; list permission is not GET permission.
Viewing, copying and saving sensitive bytes have separate acknowledgements.
Application screenshot guards inspect disclosure state across the screen stack.

`ArtifactFiles` owns descriptor-based physical directory traversal and local
entry checks. Reject symlink components, traversal, foreign/writable roots and
unsafe entries. Require owned regular single-link files. Stage and fsync writes
before exclusive new-file publication or explicitly reviewed replacement; use
private modes and recheck reviewed identity/content. Report post-commit,
durability and cleanup outcomes truthfully. This does not promise a filesystem
compare-and-swap primitive against another process running as the same user.

Blocking filesystem and serialization work uses owned cooperative workers.
Cancellation drains them rather than abandoning a running thread. Client close
revokes and drains all generations of that connection; independent local-file
jobs survive a cluster switch and drain on application exit. UI handlers hold
typed captures/results, not filesystem descriptors or policy implementations.

`:exports` is a local browser command. Its startup path returns before context
initialization and the optional initial release check, while preserving local
configuration validation and explicit later context/retry commands. The default
root is created only on an explicit Save; opening a browser is read-only.

## Consequences

Users can inspect the exact saved provenance and choose a location, overwrite,
disclosure or deletion independently. Immutable captures may intentionally be
older than the still-running view. Changed source intent invalidates a review;
ordinary arrivals do not substitute newer data without review.

Resource/log/diagnostic/support formats deliberately differ in disclosure
eligibility. Unsupported or excessive content is refused or labelled as omitted.
Recognition-based redaction cannot prove that arbitrary prose or identifiers
contain no confidential information. Sharing remains a user decision.

Golden codecs, temporary-filesystem races, service consent/cancellation tests,
owned-HTTP source capture, actual App navigation and installed terminal checks
verify these boundaries. See the [export guide](../exports.md),
[architecture](../architecture.md) and [quality policy](../quality.md).
