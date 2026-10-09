# C08 #47: kubeconfig, credential and proxy interoperability

Issue: [#47](https://github.com/carloshm91/kuberich/issues/47).
Implementation branch: `feat/47-credential-interop`.
Scope: implemented credential/transport contracts; qualification receipts below
and on the live issue identify the candidate actually verified.
No release/package/site publication is included.

## Behavior evidence

| Behavior | Owned evidence |
| --- | --- |
| Merged source directories, relative TLS, embedded CA, token files, generic exec token/certificate | Contract tests and real Kubernetes verifier |
| GKE/OIDC-shaped executable, argv/env, provideClusterInfo and captured identity | Actual local helpers; no cloud exchange claimed |
| Periodic token file, 401 reread, explicit fallback and no anonymous fallback | Real HTTP requests and bounded owned file reads |
| Certificate expiry, simultaneous refresh, changed peer serial/new TLS pool, certificate-to-token transition | Actual TLS/key pairs and concurrent requests |
| Invalid/encrypted keys, exclusive-file collision, repeated cancellation and queued session close | Real SSL/file work, preserved preexisting files and awaited cleanup |
| Repeated cancellation during initial file preparation | Held actual CA-file work finishes before the private directory is removed |
| Authenticated HTTP/HTTPS proxies, CONNECT, SOCKS5 and original/overridden TLS names | Actual loopback relays; separate API/proxy identity and repeated impersonation headers |
| Proxy disconnect/timeout and wrapped TLS errors for reads/log/watch | Actual refused/delayed handshakes; fixed private diagnostics |
| Never/IfAvailable/Always login, Ctrl+C/cancel/SIGTERM, console restoration | Native PTYs; installed-wheel checks also required before merge |
| Shared captured connection for exec/forward/future Helm staging | Private mode-600 snapshots, captured helper environment and exact cleanup; actual Helm remains #66 |
| Logs, real delegated exec and live TCP forward through HTTP CONNECT | Real owned kind, four credential mechanisms and real kubectl |

The focused command
`uv run --locked --python 3.12 pytest --tb=short -q tests/contract/test_proxy_transport.py tests/contract/test_generic_credentials.py tests/contract/test_workspace.py`
passed **72 cases**. The native generic/Azure/handoff command
`uv run --locked --python 3.12 pytest -q tests/terminal/test_credential_login.py tests/terminal/test_azure_login.py tests/ui/test_handoff.py`
passed **24 cases**. These are measured focused runs, not final whole-package
coverage claims. New credential/proxy deterministic modules are included in the
critical 100% inventory without exclusions.

The final native command
`uv run --locked --python 3.12 pytest --tb=short -q tests/terminal/test_credential_login.py tests/packaging/test_distribution.py -k 'generic or encrypted_key'`
passed **11 cases**, including source and fresh-wheel encrypted-key refusal before
any password prompt or API contact. Both embedded and file-based PKCS#8 and
traditional encrypted keys have actual SSL fixture coverage.
`uv run --locked --python 3.12 pytest --tb=short -q tests/quality/test_site.py tests/quality/test_ci_policy.py tests/quality/test_cluster_safety.py`
passed **94 cases**, preserving the owned-loopback test boundary.

The actual Kubernetes command
`uv run --locked --python 3.12 python -m scripts.verify_credential_interop_kind --kind artifacts/operations-46/tools/kind --kubectl artifacts/operations-46/tools/kubectl`
passed **27 checks** on Python 3.12.12 and the pinned kind 0.33.0/Kubernetes 1.36.4.
Its report retains fixed booleans and tool/platform identity, never credential
material. The temporary proxy, forwards, clients, files and cluster were removed;
the maintainer's active context was not used.

## Final qualification

Required before merge: final-head full suite/independent line and branch coverage,
changed-line coverage, all 37 critical modules, source/fresh-installed native
terminals, locked/fresh dependency audits, artifact checks, owned-kind
qualification and required Linux 3.12/3.13/3.14 plus native macOS 3.12 checks.
Measured results and the final head are retained on the live issue/PR; the focused
receipts above do not substitute for those whole-candidate gates.

## Deliberate limits

Real GKE, OIDC issuer, EKS/AKS exchanges, natural provider expiry and tenant/login
policy matrices remain explicit opt-in Q05 #87. Legacy auth-provider/basic entries
are rejected with an exec/token/certificate migration path. Native helper stderr
is controlled by the configured trusted helper, while credential stdout stays
private. Kubernetes documents the SOCKS5/SPDY exec/attach/forward limitation;
selected proxy settings are preserved, without a silent direct-network fallback.
Helm staging is reusable; Helm product operations are not claimed before #66.
