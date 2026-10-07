# C07 AKS acceptance evidence

C07 #22 delivers native-helper local contracts and an explicit native login route.
Actual cloud trials are deferred by the maintainer to Q05 #87. No real Entra/AKS
certification is claimed. The measured local qualification is recorded below.

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

## Measured local qualification

Frozen source/tests/scripts commit: `fec745bdb26b05840625c84b9ee9689ac59c4389`.
The final acceptance update changes documentation only; the qualified trees are:

- `src`: `6744b8082e29aaf05e8a0d88bd7860859dd02c30`
- `tests`: `53e9d3b58294761c0878a9861660d289576e4471`
- `scripts`: `86dde75354828566d3d0e7b1e8e4ec4226c8cf84`

| Linux interpreter | Behavioral tests | Production lines | Production branches | Changed executable lines |
| --- | --- | --- | --- | --- |
| CPython 3.12.12 | 1,915 passed | 6,307/6,334 (99.57%) | 1,848/1,888 (97.88%) | 183/183 (100%) |
| CPython 3.13.12 | 1,915 passed | 6,307/6,334 (99.57%) | 1,848/1,888 (97.88%) | 183/183 (100%) |
| CPython 3.14.3 | 1,915 passed | 6,201/6,227 (99.58%) | 1,849/1,888 (97.93%) | 183/183 (100%) |

All 29 critical modules pass 100% lines and applicable branches in every minor.
Each matrix passed Ruff, formatting, strict mypy, plan/link validation, the full
behavioral/real-PTY/clean-install suite, independent coverage gates, build and
Twine. Both provider verification modules additionally passed strict mypy.
Each minor retained 59 actual UI SVGs and 70 terminal result records, including
the five new Azure native-login scenarios. The source and fresh-wheel trials
assert private credential stdout, declared stdin, repeated login, interruption,
cancelled retry, parent shutdown, process cleanup and actual terminal restoration.

Representative full-matrix commands, repeated with explicit Python 3.13 and 3.14:

```sh
uv sync --locked --group dev --python 3.12
uv run --locked --python 3.12 ruff check .
uv run --locked --python 3.12 ruff format --check .
uv run --locked --python 3.12 mypy --strict src/kubetrol scripts/check_coverage.py scripts/check_quality_gate.py
MYPYPATH=src uv run --locked --python 3.12 mypy --strict --explicit-package-bases -m scripts.verify_aks_auth -m scripts.verify_eks_auth
uv run --locked --python 3.12 python scripts/validate_plan.py
uv run --locked --python 3.12 pytest --cov=kubetrol --cov-branch --cov-report=term-missing --cov-report=xml --cov-report=json
uv run --locked --python 3.12 python scripts/check_coverage.py coverage.json
uv run --locked --python 3.12 diff-cover coverage.xml --compare-branch origin/main --fail-under 90 --total-percent-float --format json:diff-coverage.json
uv build --python 3.12
uv run --locked --python 3.12 twine check dist/*
```

Three isolated negative controls each failed the intended regression test:
restoring the 8 KiB token limit rejects the actual 16 KiB HTTP bearer header;
disabling prompt recognition leaves the automatic device-code helper waiting;
restoring the previous workspace cancellation behavior leaves login at Connecting.
The corrected behavior passes. No production file was changed by these controls.

Actual owned-cluster command on the frozen source:

```sh
uv run --locked --python 3.12 python -m scripts.verify_shell_kind --kind /tmp/kubetrol-tools/kind --kubectl /tmp/kubetrol-tools/shell/bin/kubectl --evidence /tmp/kubetrol-22-evidence/kind-shell.json
```

Kind 0.33.0 / Kubernetes 1.36.4 / kubectl 1.36.4 passed real TLS/API reads,
five concurrent forced-refresh reads, delegated actual kubectl reads and actual
exec RBAC denial using the Azure-shaped local helper. The existing native/embedded
shell, fullscreen vi, resize, repeated return and explicit TLS/token/alias/
impersonation cases also passed. Nine actual kind terminal result records were
retained. The newly created fixture cluster was deleted and its absence verified.
Its report explicitly records `real_azure_aks_qualified: false`.

Raw logs, reports, actual terminal/SVG artifacts, distribution bytes and the
qualification summary are retained privately under `/tmp/kubetrol-22-evidence`.
Hosted Actions jobs have zero executed steps because account billing/spending
limits prevent startup. DCO passes; unavailable hosted/macOS checks are recorded
on the final PR under the authorized local workflow. No hosted pass is fabricated.
Full platform/protection qualification remains required before public release.
