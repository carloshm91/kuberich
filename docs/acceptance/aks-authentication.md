# C07 AKS acceptance evidence

C07 #22 delivers native-helper local contracts and an explicit native login route.
Actual cloud trials are deferred by the maintainer to Q05 #87. No real Entra/AKS
certification is claimed. Final full-suite/coverage/owned-kind results will be
recorded here before merging the issue-linked PR.

| Acceptance behavior | Verification |
| --- | --- |
| Azure CLI/device/cache, SPN secret/certificate inputs, workload identity, v1/beta | `tests/contract/test_azure_credentials.py` |
| Expiration, concurrent refresh, API 401 versus 403, captured delegated identity | Same contract suite; `scripts/verify_shell_kind.py` actual API/kubectl |
| Safe provider hints, bounded token/prompt decisions | Critical `tests/unit/test_credential_helpers.py` |
| Prompt failure, explicit login, non-TTY refusal, context replacement, cancelled retry | `tests/ui/test_azure_sessions.py` |
| Real native stdin, private credential stdout, repeated login, Ctrl+C/cancel/SIGTERM, restoration | `tests/terminal/test_azure_login.py` |
| Output/deadline bounds, read-only auth policy and owned cleanup | `tests/contract/test_processes.py` |
| Fresh wheel native login outside the checkout | `tests/packaging/test_distribution.py` |
| Explicit read-only opt-in scope/refresh/delegation/private-file cleanup | `tests/contract/test_aks_verifier.py` |

Provider-shaped tests use local owned programs, not actual Microsoft credentials.
Azure PFX/PEM certificate inputs still result in native bearer credentials; generic
exec TLS certificate outputs/rotation remain C08 #47 and fail explicitly. See
[the resulting behavior and limits](../aks-authentication.md).

The actual synthetic Pilot recovery frame is [retained as SVG](assets/azure-login-recovery.svg).
