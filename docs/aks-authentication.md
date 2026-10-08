# AKS authentication

KubeRich runs the Azure `kubelogin get-token` exec entry declared in the selected
trusted kubeconfig. It does not implement Azure login protocols, store a second
identity database, convert the kubeconfig, select another tenant or provision AKS.

## Implemented local contract

- Exec `client.authentication.k8s.io/v1` and `v1beta1`; v1 requires a valid
  `interactiveMode`, while beta defaults to `IfAvailable`.
- Literal provider args/env, including `azurecli`, `devicecode`, service principal
  (`spn`) password/PFX certificate inputs and `workloadidentity` federation settings.
  The provider owns precedence, caches and certificate/token exchange. Native
  kubelogin returns a bearer token even when the service principal uses a certificate.
- Concurrent expiration and 401 refresh share the per-context cache. Delayed 401s
  cannot invalidate a newer revision. API 403 remains an authorization failure,
  distinct from missing kubelogin/Azure CLI, login expiry, tenant configuration,
  service-principal credentials and federation hints.
- Captured inherited `AZURE_*`, `AAD_*`, `ARM_*`, `AZURESUBSCRIPTION_*`, `HOME`,
  `PATH` and `KUBECACHEDIR` are retained for delegated kubectl, together with the
  declared args/env, resolved helper executable and kubeconfig working directory.
  Changing the launch environment or source kubeconfig cannot redirect that session.
- Exec bearer credentials have a separate 64 KiB visible-ASCII bound, avoiding the
  8 KiB argument/name limit for group-heavy JWTs. Whitespace and control/header
  injection are rejected. This is a client bound; the selected server/proxy can
  impose a lower HTTP header limit.

## Explicit login and retry

Ordinary background requests use closed stdin and `spec.interactive=false`.
Existing provider sessions can supply credentials without leaving the UI.
A recognized device-code prompt stops the owned background helper promptly and
shows a fixed `:login` hint; private device codes and provider output stay out of
widgets/logs. Unrecognized helper waits still have the request deadline.
Browser-interactive mode and `Always` require an explicit login rather than an
automatic browser/terminal interaction.

On a configured Azure context, `:login` temporarily suspends the native workspace
and runs the same declared helper. The provider's stderr/prompt uses the terminal;
stdout credential JSON is captured with the existing 1 MiB bound and is never
printed. `Never` retains closed stdin; `IfAvailable` and `Always` receive terminal
stdin and `spec.interactive=true`. The handoff has a five-minute application
limit; a declared provider timeout may be shorter. Ctrl+C cancels the child.
After success KubeRich validates the response and reconnects through the ordinary
per-context API path. Failure/cancellation restores the UI and offers retry.
Shutdown or a context replacement owns process cleanup and rejects old results.

This route is allowed in application read-only mode because authentication is
needed for reads. It requires a native POSIX terminal; headless/non-TTY/Web surfaces
refuse it. The configured local helper controls its own interactive stderr output;
KubeRich does not record that output in diagnostics. Do not configure a provider
verbosity that prints secrets. For `azurecli`, establish the intended `az login`
session externally; `:login` runs the declared kubelogin entry, not an inferred
`az login` command or a different login mode.

## Qualification limits

The automated evidence uses owned synthetic helpers, loopback APIs, actual PTYs,
fresh wheel installation and a disposable kind cluster with real kubectl. It
establishes local adapter/process behavior, not successful Microsoft Entra
exchange or tenant policy compatibility. Actual AKS/Entra certification is deferred
to the maintainer's later opt-in trials in Q05 #87. No real tenant is contacted by
the automated suite. Linux results do not establish macOS qualification.

C08 #47 retains generic GKE/OIDC/legacy-provider transport qualification and
`ExecCredential.status.clientCertificateData/clientKeyData` output rotation.
That Kubernetes TLS mechanism is distinct from Azure service-principal certificate
**inputs**; unsupported certificate outputs still fail explicitly. Conditional
Access, browser forwarding on SSH and provider cache/keyring differences need
actual environment evidence. See [acceptance evidence](acceptance/aks-authentication.md).

## Optional read-only test-context smoke

The developer verifier requires every explicit scope and an acknowledgement:

```sh
uv run python -m scripts.verify_aks_auth --kubeconfig /path/to/test-kubeconfig --context TEST_CONTEXT --namespace TEST_NAMESPACE --kubectl /path/to/kubectl --acknowledge-test-cluster
```

It requires a declared Azure helper, reads at most one pod through the API, forces
only the local cache deadline, verifies five concurrent reads share one refresh,
and checks a real delegated kubectl read using a private mode-600 config that is
removed afterwards. It performs no resource writes, exec or provisioning.
Forced refresh does not prove natural expiry, real interactive login, or the
full Entra mode/policy matrix; the evidence says so. It never falls back to the
active user context, and returns fixed sanitized failures.

## Sources

Reviewed Azure kubelogin source at
[`5d03c6dd909e27b36b39a1cb9a815f2b47d9a180`](https://github.com/Azure/kubelogin/tree/5d03c6dd909e27b36b39a1cb9a815f2b47d9a180),
including [token writer](https://github.com/Azure/kubelogin/blob/5d03c6dd909e27b36b39a1cb9a815f2b47d9a180/pkg/internal/token/execCredentialWriter.go),
[device prompt](https://github.com/Azure/kubelogin/blob/5d03c6dd909e27b36b39a1cb9a815f2b47d9a180/pkg/internal/token/devicecodecredential.go)
and [environment precedence](https://github.com/Azure/kubelogin/blob/5d03c6dd909e27b36b39a1cb9a815f2b47d9a180/pkg/internal/token/options.go).
Latest observed provider release was v0.2.20; it is not a qualified installed version.

- [Microsoft AKS authentication](https://learn.microsoft.com/en-us/azure/aks/kubelogin-authentication)
- [Azure login modes](https://azure.github.io/kubelogin/concepts/login-modes.html)
- [Azure get-token arguments](https://azure.github.io/kubelogin/cli/get-token.html)
- [Kubernetes exec input/output contract](https://kubernetes.io/docs/reference/access-authn-authz/authentication/#client-go-credential-plugins)

- [Microsoft Entra error-code reference](https://learn.microsoft.com/en-us/entra/identity-platform/reference-error-codes)
