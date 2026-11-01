# 0032: Own kubeconfig preparation and expose explicit compatibility limits

Status: accepted for the foundations phase

## Context

A kubeconfig that works with kubectl should connect or produce an actionable
message naming the incompatible field. The v1 schemas in client-go 1.35, 1.36
and 1.37 have the same field inventory. Schema compatibility does not certify
authentication against every provider or cluster version.

KubeRich must keep a client, credentials, temporary files and cleanup owner for
each selected context. Offline diagnostics cannot import the Kubernetes SDK.
Background authentication cannot inherit terminal input, and loading credentials
must not write the source kubeconfig.

## Decision

Retain the bounded catalogue and owned connection preparation. Continue using
`kubernetes_asyncio.client.Configuration` and `ApiClient` explicitly per session.
Do not replace this boundary with the SDK kubeconfig loader in version 36.1.0.

The SDK offers an explicit `client_configuration` and a `persist_config=False`
option. Those options avoid its global default and source-write paths when used
correctly; these avoidable defaults are not the reason to reject the API.
Remaining public-API differences matter:

| Concern | Pinned SDK loader | Required owned behavior |
| --- | --- | --- |
| TLS files | `FileOrData` shares a module-level material/path cache until process exit | Private files belong to one session and disappear after awaited closure |
| File work | Synchronous reads/writes in loader paths | Regular-file and byte bounds, outside the terminal event loop |
| Exec helpers | Loader/provider owns its separate execution path | Literal argv, stdin policy, bounded pipes, timeout, process-group reaping and explicit login |
| Renewal | Loader refresh is separate from request ownership | Per-client expiry/401 coordination and actual TLS pool replacement |
| Effective identity | Loader authentication precedence and fields differ | One captured identity for reads, writes and delegated tools, including impersonation |
| SOCKS TLS | Loader configuration alone does not establish the connector's SNI behavior | Existing real TLS/proxy contracts preserve the configured server name |

The current SOCKS connector drops request-level `server_hostname`. Keep the
existing binding at Python's public `SSLContext.wrap_bio` boundary, covered by
real matching/mismatching TLS and renewal tests. This is not a reason to weaken
verification or replace a configured name with the endpoint address.

Support explicit Basic credentials without prompting. A public, per-session
transport method returns the prepared Authorization header for both read and
write requests. Basic credentials remain distinct from bearer storage and are
staged as username/password in private delegated configuration. Anonymous
requests do not receive invented credentials; overrides replace the selected
mechanism without changing the catalogue.

For legacy OIDC, implement the accepted exec-migration alternative rather than
an additional in-process issuer, browser, refresh cache and persistence stack.
The explicit local `kubeconfig oidc-migration` command emits a reviewable
int128/kubelogin v1 fragment. It preserves only validated issuer/client-id/CA
metadata, resolves a CA file against its original user entry and substitutes a
fixed placeholder when a client secret needs manual configuration. Existing ID,
refresh and client-secret values are not copied. No helper, issuer request,
installer or source-file write runs during generation. The chosen helper owns
future sign-in and refresh after the user reviews and applies the fragment.

## Consequences

We maintain field and provider-shaped contracts alongside the adapter. Empty
optional context strings and inline TLS-data fallbacks match kubectl defaults;
opaque extension payloads remain opaque. Known unsupported mechanisms, encrypted
keys and bounded-input limits receive fixed field-specific diagnostics.

This is not a claim of complete provider certification. Synthetic helpers and
owned TLS/proxy/API tests establish local contracts. Real cloud, Teleport and
tailnet trials remain separate opt-in work. A future SDK loader can replace this
code only after demonstrating equivalent ownership, validation and transport
behavior without importing private implementation details.

## Sources

- [client-go v1 schema](https://github.com/kubernetes/client-go/blob/v0.36.4/tools/clientcmd/api/v1/types.go)
- [client-go effective connection](https://github.com/kubernetes/client-go/blob/v0.36.4/tools/clientcmd/client_config.go)
- [SDK 36.1.0 loader](https://github.com/tomplus/kubernetes_asyncio/blob/36.1.0/kubernetes_asyncio/config/kube_config.py)
- [SDK 36.1.0 exec provider](https://github.com/tomplus/kubernetes_asyncio/blob/36.1.0/kubernetes_asyncio/config/exec_provider.py)
- [int128/kubelogin options](https://github.com/int128/kubelogin/blob/master/docs/usage.md)
- [Python TLS BIO interface](https://docs.python.org/3/library/ssl.html#ssl.SSLContext.wrap_bio)
