# EKS authentication: C06 #21

Kubetrol uses the `aws eks get-token` exec entry already declared in your trusted
local kubeconfig. The AWS CLI owns its credential chain, profiles, role assumption,
SSO cache and refresh; Kubetrol does not embed AWS credentials or create clusters.
The local contracts below are implemented. **Actual AWS/EKS qualification is
pending a maintainer-provided test context; #21 remains open.**

## Supported local contracts

- Honor declared arguments/environment and `client.authentication.k8s.io/v1`
  or `v1beta1`. Version v1 requires `interactiveMode`; Never and IfAvailable
  receive closed stdin and `KUBERNETES_EXEC_INFO.spec.interactive=false`.
- Cache tokens per context until their expiration, rejection or session closure.
  Concurrent refresh requests share the helper lock. Delayed 401 responses from
  an older cache revision cannot invalidate a newer revision, even when AWS
  returns the same token bytes; each request retries a rejection at most once.
- Capture inherited helper environment when the session is created. Refresh
  preserves it. Delegated shells inherit the same AWS variables and HOME, retain
  declared exec env/args, and use the same kubeconfig-relative working directory.
  A bare `aws` command is resolved using the effective helper PATH and pinned
  in the private kubectl connection snapshot. No inherited AWS secrets are
  added to the snapshot file; captured variables remain in process memory.
- Drain helper pipes concurrently with existing 1 MiB stdout/64 KiB stderr
  bounds, timeout, process-group cleanup and no raw output in diagnostics.
  Closing a session discards the credential cache and prevents further delegation.
- Show fixed hints for a missing AWS CLI, execution permissions, recognized SSO
  errors, denied AssumeRole, missing credentials and expired AWS credentials.
  Unknown helper failures retain a generic AWS hint. Recognition is best effort
  for a declared `aws ... eks get-token` executable; wrappers retain generic
  helper errors. Kubernetes 401 and 403 remain separate API outcomes.

Complete SSO login outside Kubetrol using the profile from your exec entry:

```sh
aws sso login --profile YOUR_PROFILE
```

Then retry with `r` or `:retry`. Kubetrol does not open a browser automatically or
rewrite your kubeconfig/AWS files. The AWS CLI may renew its own cached credentials
as part of the configured helper. InteractiveMode Always and exec certificate
rotation remain C08 #47; this ticket does not implement interactive cloud login.

## Opt-in real smoke

Run only on a **test context explicitly authorized by its owner**. The script
refuses omitted scopes and non-AWS exec entries, and never falls back to the
active/default context:

```sh
uv run python -m scripts.verify_eks_auth \
  --kubeconfig /absolute/path/to/test-kubeconfig \
  --context YOUR_EKS_TEST_CONTEXT \
  --namespace YOUR_TEST_NAMESPACE \
  --kubectl /absolute/path/to/kubectl \
  --acknowledge-test-cluster
```

It reads at most one pod per response through the Python adapter, forces only
the session-local cache expiration for five concurrent reads, and performs the
same pod read with real kubectl and a private connection snapshot. It creates no
cluster resources, performs no exec and calls no provisioning APIs. Its report
contains fixed outcomes/platform information; no token, account, ARN, context,
namespace, kubeconfig, helper output or pod contents are retained. The private
snapshot is removed and the client/TLS directory closed on success and failure.

This smoke does **not** prove naturally expiring tokens, the full SSO/role matrix,
or the server-side principal merely from successful reads. Qualification must
record actual AWS CLI/Kubernetes/kubectl/platform versions and the authorized
profile/role/SSO scenarios separately, without publishing private identities.
The checked-in tests use local synthetic helpers, and the kind verifier uses a
synthetic AWS-shaped helper with a disposable service-account token. Neither is
real-cloud evidence. See [measured acceptance](acceptance/eks-authentication.md).

## Sources

- [EKS kubeconfig and AWS helper](https://docs.aws.amazon.com/eks/latest/userguide/create-kubeconfig.html)
- [AWS CLI get-token](https://docs.aws.amazon.com/cli/latest/reference/eks/get-token.html)
- [AWS CLI SSO sessions](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html)
- [AWS CLI 2.36.46 ExecCredential version negotiation](https://github.com/aws/aws-cli/blob/2.36.46/awscli/customizations/eks/get_token.py)
- [Kubernetes exec credential protocol](https://kubernetes.io/docs/reference/access-authn-authz/authentication/#client-go-credential-plugins)
