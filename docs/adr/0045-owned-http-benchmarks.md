# Own reviewed HTTP benchmark load and local results

Status: implemented in development source; protected delivery and cumulative phase qualification remain separate.
Date: 2026-11-10.

## Context

An HTTP load test can disrupt a workload independently of Kubernetes API writes.
A selected Service does not identify the Pod that kubectl will forward, and an
old local port does not establish ownership of its current listener. External
tool output and request credentials require separate privacy and process limits.

## Decision

Require an explicit writable action, fresh target checks and a service-issued,
one-use intent over one backend Pod, request and immutable load options. Bind
Service provenance, Pod UID, resolved TCP port, client generation and connection
identity. Resolve at most 128 backend candidates; refuse incomplete enumeration.

Use the explicitly configured Vegeta v12.13.0 executable through `ProcessRunner`.
Probe its supported version only after Run, before opening a dedicated loopback
forward. A development-only acquisition script pins official archive and extracted
binary digests for Linux/macOS amd64/arm64. Production neither provisions tools
nor treats a version string as binary authentication.

Each run owns a new Pod forward with an ephemeral local port and no reconnects.
A narrow forward observer reports readiness and loss for the exact UUID/attempt.
Do not reuse an ordinary Service forward's listener or claim load balancing.
Stop on observed target/client/policy invalidation or forward loss; never adopt
another listener, backend or forwarding attempt.

Pass literal argv and a minimal noncredential environment. Private 0700 run
directories and 0600 JSON target/raw-result files keep request values off argv.
Use HTTP/1.1, no redirects, no persistent connections, fixed worker/connection
ceilings, finite request/duration limits and no metrics listener. Attack output
is capped at 2 MiB; version/report output and process deadlines are independent.

Decode the pinned report schema in an owned worker. Reject duplicate/nonfinite
JSON, unknown fields, inconsistent totals/intervals and invalid percentiles.
Keep integer nanoseconds and explicit denominators. Distinguish status 0,
4xx/5xx and 3xx; discard raw error strings and retained-byte throughput claims.

Persist only the normalized allowlist: UUID/times, safe target provenance,
method/load, known producer/parser version, completion and validated metrics.
Use `ArtifactFiles` descriptor anchors and immutable entry identities. Serialize
this application's writers; refuse unknown, unsafe, changed or malformed entries.
Apply 100-record/32 KiB-record/4 MiB/30-day retention only during explicit saves.
The local browser never creates, prunes, executes, connects or grants replay.

Drain load/report/parser ownership before the dedicated forward, private files
and client material. Escape, context replacement and app shutdown use that same
boundary. A completed in-memory result survives persistence refusal with an
explicit save-failed observation.

## Consequences

- Requested pacing may catch up after worker saturation. It is not an exact
  per-second traffic ceiling, and the nominal request count allows a boundary.
- Percentiles include failures. Single-sample rates are unavailable. 2xx/3xx
  throughput follows the producer's success semantics, with redirects separate.
- `max-body=0` still drains response bodies. No whole-wire byte or external RSS
  quota is claimed; request deadlines and output limits remain separate controls.
- kubectl's name-based remote selection and an unobserved local listener change
  retain a final race. Notification stops observed loss without claiming atomic
  UID binding for every connection.
- File entry operations are reviewed named link/unlink transactions, not an
  interprocess filesystem compare-and-swap. Unknown files are never pruned.
- Safe metadata can still identify a workload. Local cleanup does not promise
  secure erasure of every historical copy of sensitive bytes.
- Provider, native-platform, installed and cumulative release qualification need
  their own measured evidence; a local service proof establishes no parity claim.

## Source and related decisions

The pure [request contracts](../../src/kuberich/domain/benchmarks.py),
[target decisions](../../src/kuberich/domain/benchmark_targets.py), and
[result codec](../../src/kuberich/domain/benchmark_results.py) are independent
of Textual. The [service](../../src/kuberich/services/benchmarks.py),
[tool owner](../../src/kuberich/services/benchmark_tool.py), and
[store](../../src/kuberich/services/benchmark_store.py) enforce effect boundaries.
See [managed forwards](0015-managed-tcp-forwards.md),
[local artifacts](0037-reviewed-local-artifacts.md),
[external processes](0008-external-process-ownership.md), and
[benchmark acceptance](../internal/acceptance/http-benchmarks.md).
