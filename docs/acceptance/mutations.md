# M01 #43 acceptance evidence

The implementation adds guarded mutation services, an explicit `:annotate`
confirmation and bounded `:writes` history. The service owns real conditional API
writes; resource-specific editor/scale/delete operations remain their own tasks.

Focused HTTP/Pilot/policy/navigation qualification passed 208 cases before the
final matrix. The pure mutation module measured 100% of 132 executable lines and
38 branches. Actual TLS/auth/impersonation, 401/403/404/409/422/429/5xx, atomic
preconditions, dropped/invalid/oversized responses after application, cancellation,
confirmation replacement/reuse, and active/history bounds are exercised. A real
exec helper is not refreshed or replayed after the actual write returns 401.
Repeated cancellation drains an owned receipt-decoding thread.

Three actual source/fresh-wheel console/module PTYs passed keyboard entry,
Tab/Shift+Tab, Review/Cancel/Confirm, exact key/value transport, public history,
40×12 resize, exit and original terminal mode restoration. Pilot covers 40×12
and 100×30 confirmation, field/scope changes, read-only, history, pending writes
and exit. An initial task-name collision with Textual was corrected; test mounting
waits now respect the actual DOM lifecycle. Actual PTYs caught deferred Tab focus
placing value text in the key field; scoped priority focus bindings corrected it.
Failed trials remain in `/tmp/kubetrol-43-evidence`.

```sh
uv run python -m scripts.verify_mutations_kind --kind /tmp/kubetrol-tools/kind --evidence /tmp/kubetrol-43-evidence/kind.json
```

The newly owned Kubernetes 1.36.4 cluster passed Docker-node/API/config ownership
verification before fixture writes. A real ConfigMap annotation changed while
existing data/annotations were retained. Actual JSON Patch rejected old object
versions and UIDs after same-name recreation, without applying the intended value.
An explicitly impersonated get-only user passed the read and received actual
patch RBAC denial. Caller configuration remained unchanged. The cluster was
deleted and its absence verified.

Final frozen-source Python 3.12/3.13/3.14 complete suites, independent production/
critical/changed-line gates, final builds/audits and current-head DCO will be
recorded before closure. Hosted billing, macOS and real cloud/public-release
qualification remain separate; no artifacts or tags are published by this task.
