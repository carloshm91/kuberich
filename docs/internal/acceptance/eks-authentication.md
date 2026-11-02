# C06 #21: EKS contract and qualification evidence

## Scope

Implemented local provider contracts: declared AWS exec arguments/environment,
version negotiation, session-local refresh/cache revisions, fixed private-safe
failure hints and captured AWS identity settings in delegated kubectl.
The explicit read-only smoke is prepared for an authorized maintainer test context.
**Real AWS/EKS qualification is pending.** The maintainer explicitly deferred
their real-cluster trial until an installable preview and authorized continuing
private development with measured local/disposable-cluster evidence. C06 delivers
the provider contracts under that clarification; Q05 #87 retains optional real
provider certification. No EKS/SSO/role matrix certification is claimed.

Evidence sources:

- [Provider contracts](../../tests/contract/test_eks_credentials.py): v1/v1beta1,
  Never/IfAvailable, literal roles/profiles, inherited environment capture,
  twenty concurrent expiration requests, delayed concurrent 401 responses even
  for identical token bytes, API 401/403, invalid responses, process cancellation
  and private shell snapshots.
- [Critical diagnostic decisions](../../tests/unit/test_credential_helpers.py):
  fixed hints, bounds, malformed/private output and generic helper separation.
- [Terminal behavior](../../tests/ui/test_eks_sessions.py): local context
  navigation while AWS is waiting, SSO recovery text and Ctrl+Q cleanup.
  [Actual synthetic SSO recovery render](assets/eks-sso-recovery.svg).
- [Smoke safety](../../tests/contract/test_eks_verifier.py): explicit scope
  requirements, generic-helper refusal, local reads/refresh/delegation and
  cleanup on invalid payload or kubectl failure.
- [Owned real Kubernetes and kubectl](../../scripts/verify_shell_kind.py):
  synthetic AWS-shaped helper, real TLS/API reads, concurrent forced refresh,
  delegated actual kubectl read and actual exec RBAC denial with terminal return.

## Measured local qualification

Frozen application/tests/scripts commit: `872a56df18dbe95cf72d7bc4ddfb00df5367d4df`.
Later acceptance/backlog/agent-guidance edits and the SVG are documentation only;
the three qualified trees are unchanged.

- `src`: `37621b135a61563eb6e9295916a980c3c1c24030`
- `tests`: `1edbace5b8ba168c3dec92cae20d3cb91979757e`
- `scripts`: `4888f760dc3e0dbff571866710b8b432047488cc`

| Linux interpreter | Behavioral tests | Production lines | Production branches | Changed executable lines |
| --- | --- | --- | --- | --- |
| CPython 3.12.12 | 1,794 passed | 6,203/6,230 (99.57%) | 1,798/1,838 (97.82%) | 67/67 (100%) |
| CPython 3.13.12 | 1,794 passed | 6,203/6,230 (99.57%) | 1,798/1,838 (97.82%) | 67/67 (100%) |
| CPython 3.14.3 | 1,794 passed | 6,096/6,123 (99.56%) | 1,798/1,838 (97.82%) | 67/67 (100%) |

All 29 critical modules meet 100% lines and applicable branches. Each matrix
passed Ruff, formatting, strict mypy, plan/link validation, full behavioral/PTY/
clean-installed artifact tests, independent coverage gates, build and Twine.
The verifier additionally passed strict mypy. Each minor retained 58 actual UI
SVGs and 64 terminal result records. Source/test/script trees and raw logs/reports/
distributions are retained privately under `/tmp/kubetrol-21-evidence`.

The 50 new checks include the two important negative controls: restoring
unconditional 401 invalidation fails with three helper calls instead of two;
restoring nonempty-only environment validation rejects valid `AWS_PAGER=""`.
Both corrected regressions pass. The earlier candidate completed 3.14; 3.12/3.13
were deliberately interrupted to fix the empty-environment case. Those earlier
runs are archived separately and do not count as final qualification.

Actual owned-cluster command on the final frozen application:

```sh
uv run --locked --python 3.12 python -m scripts.verify_shell_kind --kind /tmp/kubetrol-tools/kind --kubectl /tmp/kubetrol-tools/shell/bin/kubectl --evidence /tmp/kubetrol-21-evidence/final-kind-shell.json
```

Kind 0.33.0 / Kubernetes 1.36.4 / kubectl 1.36.4 passed the synthetic AWS-shaped
helper contract against real TLS/API reads, five concurrent forced-refresh reads,
a delegated actual kubectl read, and real exec RBAC denial with terminal return.
The existing shell, fullscreen vi, resize, repeat return and explicit TLS/token/
alias/impersonation cases also passed. Eight owned-kind terminal records were
retained; the newly created cluster was deleted and its absence verified.

Hosted Actions cannot execute while account billing/spending limits block jobs;
macOS results are unavailable for this PR. Inspect the final PR's actual check
runs and retain those limitations with the maintainer-authorized local workflow.
No hosted pass is manufactured. Full platform/protection gates still apply before
public release. Installed AWS CLI 2.33.8 presence/version was inspected only;
no real AWS token/STS request or EKS cluster test was run. The later maintainer
trial and Q05 certification remain explicitly pending.
