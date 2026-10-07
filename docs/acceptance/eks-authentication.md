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
- [Smoke safety](../../tests/contract/test_eks_verifier.py): explicit scope
  requirements, generic-helper refusal, local reads/refresh/delegation and
  cleanup on invalid payload or kubectl failure.
- [Owned real Kubernetes and kubectl](../../scripts/verify_shell_kind.py):
  synthetic AWS-shaped helper, real TLS/API reads, concurrent forced refresh,
  delegated actual kubectl read and actual exec RBAC denial with terminal return.

The full measured matrix and owned-cluster outcomes are recorded after execution.
Synthetic/local observations do not complete real provider acceptance.
