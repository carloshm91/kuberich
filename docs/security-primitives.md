# Security primitives and integration contracts

F04 provides shared helpers and test isolation. It does not connect a cluster,
execute a plugin, or implement mutation authorization. The terminal preview
continues to start disconnected. See the [threat model](kubetrol-threat-model.md)
for boundaries, existing controls and the remaining issue owners.

## Presenting untrusted text

Resource names, annotations, logs, kubeconfig labels and tool output must pass
through `security.presentation.safe_text`. It returns a literal Rich `Text`,
which can be passed directly to Textual widgets and table cells. Rich markup
such as `[link=...]` remains visible text without adding styles or hyperlinks.
Do not pass its `.plain` value back through a markup parser.

```python
from kubetrol.security.presentation import safe_text

table.add_row(safe_text(namespace), safe_text(resource_name))
log_widget.write(safe_text(log_chunk, multiline=True))
```

Input is bounded to 16,384 characters before redaction and rendering. Truncated
input gets a literal notice. C0/C1 controls, ESC/OSC/ANSI sequences, bidi controls,
Unicode line separators and lone surrogates become visible Unicode escapes.
Expansion can produce up to six characters per escaped input character, plus
the truncation notice. Unicode text and emoji joiners remain intact. Only
`multiline=True` preserves line feeds; tabs, carriage returns and other controls
remain escaped. A future log service must also bound its retained buffer and
queue; a per-chunk bound alone does not establish bounded stream memory.

`diagnostics.redaction.sanitize_text` uses the same control helper with a
65,536-character input bound and single-line output by default. Existing
diagnostic records have a separate byte limit. Credential patterns include
Bearer/Basic credentials, URL passwords, JWTs, AWS access IDs, private keys and
sensitive key/value fields. Tests use synthetic values only.

Pattern redaction cannot recognize arbitrary opaque secrets. Default Secret
views must conceal values, and external error adapters must construct allowlisted
summaries containing the operation, status and safe resource identifiers rather
than copying response bodies, auth-helper stderr, exception values or environment
dumps. `403 Forbidden listing pods in fixture-ns` is actionable context. An opaque
credential embedded in an arbitrary message is not safe just because it passed
the redactor. Explicit secret reveal and export policy remain B04/A07 work.

## Capturing an action target

`domain.targets.SessionIdentity` is created once for each owned client. It has an
explicit context, nonnegative generation and unique connection UUID. Reopening
the same named context produces a different connection identity.
`ResourceTarget` captures that identity, API group/resource, namespace, name,
object UID and optional container in frozen dataclasses. An empty group denotes
the core API; `namespace=None` denotes cluster scope.

Capture the target before the first await or confirmation dialog. Do not rebuild
it from the current row later. Call `target.require_current(session, uid=uid)`
against the action service's current owned client and freshly observed object.
It rejects a context/generation/client change and same-name object recreation
without exposing rejected values. See Kubernetes' [object identity contract](https://kubernetes.io/docs/concepts/overview/working-with-objects/names/).

This is a local staleness guard. It does not implement permissions, read-only
policy, locking or a server-side transaction. C01 owns the client/session binding
and generation transitions; M01 must enforce the guard in operation services,
check read-only policy and use API UID/resourceVersion preconditions appropriate
to each write. Otherwise a resource could change between checking and using it.
Confirmation, conflict handling and uncertain write outcomes remain those
services' responsibility. Kubernetes RBAC remains the authorization boundary.

## Process arguments

`security.arguments.freeze_arguments` copies an explicit sequence into a tuple.
Arguments must be nonempty strings of at most 8,192 characters and contain no
terminal/directional controls or lone surrogates. Spaces, Unicode, quotes and
shell metacharacters remain literal; values are never silently normalized.
Targets also reject resource/name identifiers beginning with `-`.

This helper neither executes a process nor validates every tool's options.
S03 command builders must use a fixed executable/operation, explicit effective
kubeconfig/context/namespace/container and argument-vector process APIs without
a shell. Bind flag values in forms such as `--context=value`; use the tool's
supported option terminator for positional values where appropriate. Avoid
implicit environment/current-directory context fallback. See Python's
[subprocess security contract](https://docs.python.org/3/library/subprocess.html#security-considerations).
PTY handoff, subprocess cleanup, cancellation and read-only classification are
future integration work; these pure helpers do not qualify those behaviors.

## Preventing accidental test-cluster access

The root `tests/conftest.py` autouse fixture applies to every test family. It
sets `KUBECONFIG` to a nonexistent temporary path, removes in-cluster service
environment variables, and traps SDK configuration/client-factory entry points
in both public and implementation modules. An accidental ambient loader fails
before reading credentials or invoking helpers, even with no explicit arguments.

Tests that need Kubernetes configuration use
`tests.support.clusters.load_disposable_config(DisposableContext(...))`. The
fixture must own a temporary directory/file, use an explicit `kubetrol-test-` or
`kind-kubetrol-test-` context, contain exactly one matching context and cluster,
and bind a numeric loopback endpoint with an explicit port. Remote URLs, userinfo,
proxy endpoints, paths/query/fragment redirects, external CA/key files and
credential helpers are rejected before the SDK sees the file. Parsing rejects
aliases, duplicate/nonstring keys, excessive depth/events and files over 64 KiB.
Embedded test credentials must be generated synthetic values, or credentials
created for an owned disposable cluster.

The permitted loader receives an explicit context and a separate SDK
`Configuration`, with persistence disabled. The SDK default and caller's config
file are preserved. The guard tests load a synthetic file without opening an API
connection. Starting/cleaning kind clusters and real API qualification remain C01
and the corresponding integration issues.

This is a regression barrier for trusted test authors, not an OS network sandbox.
Direct HTTP calls, subprocesses and aliases captured before fixture installation
require review. Existing terminal/packaging subprocess tests supply their own
temporary config paths. Future cloud-helper fixture qualification must provide
an explicit safe harness rather than disabling the ambient traps.

## Verify this issue

```sh
uv run pytest tests/unit/test_security_text.py tests/unit/test_targets.py tests/quality/test_cluster_safety.py
```

These checks exercise real Rich rendering of hostile strings, preservation of
actionable error context, immutable capture across an await, client/UID changes,
ambient-loader refusal, unsafe fixture rejection, and an actual isolated SDK
configuration load. The full suite and coverage commands remain in
[the quality policy](quality.md). All four new production helper modules are
designated critical and require 100% line and applicable branch coverage.
