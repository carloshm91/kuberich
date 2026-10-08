# M02 #44 acceptance evidence

The selected-resource `:edit` / Shift+E action captures context/scope/name/UID,
defaults to Cancel and requires explicit trusted-local-editor disclosure before
creating a full-manifest draft. Editor argv is immutable, quoted and shell-free.
Owned drafts start with directory/file modes 0700/0600, use bounded no-follow
reads and are removed before form return or captured client cleanup.

Changed JSON-compatible YAML produces an immutable conditional structural patch
and a separately redacted diff; placeholders never enter request values.
Formatting-only edits, failed/cancelled editors and invalid/identity-changing
manifests cannot send a patch. Manual Validate uses strict server dry-run without
persistence. Separate Apply requires the exact validated intent and one-use
confirmation; the shared owner revalidates and retains public/uncertain outcomes.
A concurrent version or replacement UID requires a fresh edit; no overwrite,
automatic merge or replay is offered. Secret full-manifest access remains #55.

## Qualification in progress

Final frozen commit and complete Linux interpreter measurements are added after
the suite completes. Focused verification already exercised all 114 executable
lines and 40 branches of critical `domain/editing.py`. This is the 33rd critical
deterministic module, with no production exclusions or reduced gates.

Contracts use actual files and owned HTTP/TLS to verify dry-run versus persistence,
captured token/impersonation, exact bodies, RBAC/error responses, UID/version/scope
conflicts and proof invalidation. Held reads/file workers exercise cancellation,
repeat cleanup, creation discard and drain before SDK shutdown. Malformed YAML
and server error payloads remain absent from public status/history.

Pilot covers 40×12 and 100×30, default Cancel, local disclosure, redacted preview,
dry-run, separate Apply, read-only and held read/creation under F4/Escape/exit.
Actual foreground-editor PTYs qualify source success/no-op/failure/malformed/
Ctrl+C and fresh-wheel console/module success outside the checkout. Each verifies
native terminal/job control, restoration, 40-column resizing and file removal.

## Actual disposable Kubernetes

```sh
uv run python -m scripts.verify_editing_kind --kind /tmp/kubetrol-tools/kind --evidence /tmp/kubetrol-44-evidence/kind.json
uv run python -m scripts.verify_mutations_kind --kind /tmp/kubetrol-tools/kind --evidence /tmp/kubetrol-44-evidence/mutations-kind-regression.json
```

The M02 verifier passed 12 checks on owned Kubernetes 1.36.4: permissions,
unchanged draft/version, non-persisting dry-run, exact Apply, preservation,
proof reuse refusal, concurrent-version refusal, strict unknown-field rejection,
actual dry-run PATCH denial for a get-only user, same-name replacement refusal,
file cleanup and caller configuration invariance. Its owned cluster was deleted
and absence verified. M01 regression passed all eight actual annotation/RBAC/
atomic-precondition checks on a separate owned cluster, also deleted. Neither
trial used the maintainer's active context or a cloud provider.

## Corrected trials and limits

Native PTYs caught disclosure toggles being delivered after priority focus moves
when Space/Tab/Enter arrived in one packet. Disclosure now uses a scoped priority
binding before focus changes; rapid native input passed. Form close initially
painted the table before asynchronous unmount file cleanup. Cancel/Escape now
wait for owned cleanup before dismissing; pending annotation forms use the same
ordering. Intermediate failed trials remain in raw evidence and are not final
qualification. Full matrix and exact delivery artifact results are pending.

Native macOS and hosted release qualification remain unavailable under the
account Actions block. Arbitrary external editor backups/history, secure erasure,
SIGKILL, older server/admission versions and cloud certification are outside this
measured scope. See [editor behavior](../editing.md). No tag, public repository,
release or package is published.

Raw evidence: `/tmp/kubetrol-44-evidence` (local, rather than durable hosted artifacts).
