# Kubeconfig and credential interoperability: C08 #47

KubeRich uses the selected context's effective connection for resource reads,
watches, logs, guarded writes, shells and port forwarding. It does not change
your kubeconfig or infer a different cloud account when authentication fails.
The contracts below are tested with owned helpers, HTTP/TLS/proxy servers,
native terminals, installed packages and a disposable Kubernetes cluster.
Real cloud-provider certification remains opt-in Q05 #87.

## Configuration and private material

`--kubeconfig` selects one file; otherwise `KUBECONFIG` can list files separated
by the operating system's path separator. Catalogue merging preserves the
directory that supplied each cluster/user entry. Relative CA, certificate, key,
token-file and helper paths resolve against that directory, including when the
context and user come from different files. Embedded TLS data overrides its
corresponding file. CA/certificate/key copies and generated connection snapshots
live in an owned mode-700 directory with mode-600 files; awaited session cleanup
removes them.

Encrypted static client keys are refused before OpenSSL can request a passphrase
inside the application. Use a compatible unencrypted key or an explicit exec
helper that owns decryption; KubeRich never starts an implicit password prompt.

`tokenFile` is read at connection preparation, then checked before requests at
most every 60 seconds. A 401 forces a reread before one read-only retry. The last
successful file value takes precedence over an explicit `token`; an unavailable
rotation preserves that value. An unreadable initial file can use only the
explicit configured token. It never selects an anonymous identity as a fallback.
Effectful requests receive refreshed credentials before sending and are not
automatically replayed after a rejection or uncertain response.

## ExecCredential

The declared helper receives literal argv and configured environment entries,
runs in its original kubeconfig directory, and uses a captured inherited
environment. Bare executable names resolve through the effective helper PATH;
the successfully used absolute executable is pinned for delegated tools.
Capturing includes variables that were absent, so a later caller cannot inject
a different profile or helper identity. Helpers remain trusted local programs
running with your user's privileges, including in read-only mode.

KubeRich supports `client.authentication.k8s.io/v1` and `v1beta1`, with matching
response kind/version. Version v1 requires `interactiveMode`; beta defaults to
`IfAvailable`. The native `:login` command explicitly runs that same helper:

| Declared mode | Ordinary background authentication | Explicit native `:login` |
| --- | --- | --- |
| `Never` | Closed stdin, `interactive=false` | Closed stdin, `interactive=false` |
| `IfAvailable` | Closed stdin, `interactive=false` | Terminal stdin, `interactive=true` |
| `Always` | Refused with a login hint | Terminal stdin, `interactive=true` |

The background helper never inherits terminal input. Login requires the native
terminal, keeps credential stdout private and restores the workspace after
success, Ctrl+C, cancellation or termination. The configured helper controls
its terminal stderr, such as browser/device prompts. KubeRich does not retain
that interactive output in logs or diagnostics. Headless/non-TTY/Web operation
cannot provide this handoff.

`provideClusterInfo` must be a boolean and defaults to false. Only true includes
`spec.cluster`: effective server, verification setting, CA data, TLS name,
proxy and the `client.authentication.k8s.io/exec` extension configuration.
`spec.interactive` always describes the stdin actually supplied. See the
[Kubernetes credential API](https://kubernetes.io/docs/reference/config-api/client-authentication.v1/).

Responses contain either a bounded bearer token or a paired PEM client
certificate/private key. Mixed identities, missing pairs, encrypted helper keys,
invalid versions/JSON and expired or timezone-free deadlines are rejected.
The helper's output is bounded to 1 MiB; stderr is bounded to 64 KiB. Each
session owns its cache, helper process group, deadline and cancellation.

Certificate renewal validates the key pair, creates fresh private files and
replaces the connection pool. Previous TLS connections close so the new pair
participates in a new handshake. Changing to a token removes the old certificate
identity. Invalid replacement material refuses the request; it cannot silently
continue under the previous certificate. Concurrent refresh shares one lock;
an old response cannot invalidate a newer credential revision.

## Proxies, TLS and delegated tools

An explicit nonempty `proxy-url` wins. Otherwise the captured `HTTP_PROXY` /
`HTTPS_PROXY` or lowercase equivalents select the proxy, with `NO_PROXY` bypass
rules. Environment settings bypass localhost/loopback; an explicit proxy still
applies there. CGI-style `HTTP_PROXY` is refused. Supported URL schemes are
HTTP, HTTPS and SOCKS5, including proxy credentials. Proxy authentication stays
separate from the Kubernetes bearer token. Automatic netrc identity remains
disabled.

Server certificates use the configured CA and original server hostname, or
nonempty `tls-server-name`. This also applies through SOCKS5 and certificate
renewal. Disabling verification remains explicit and visible as insecure
transport. Proxy failures and TLS mismatches produce fixed safe diagnostics.
Repeated impersonation groups and user/UID/extras retain their meaning.

Shells and forwards receive a captured private kubeconfig with the same server,
proxy, TLS material, helper and impersonation settings. They do not reload the
ambient current context. HTTP CONNECT is qualified against real Kubernetes
for logs, exec and forwarding. SOCKS5 qualifies API reads/streams/TLS; Kubernetes
documents a limitation for SPDY exec/attach/forward transports. KubeRich preserves
the selected proxy and reports failures rather than silently bypassing it.
See the [kubeconfig API](https://kubernetes.io/docs/reference/config-api/kubeconfig.v1/).

The shared private-connection staging also accepts Helm's future purpose. Actual
Helm operations and their installed-tool qualification remain M06 #66; C08 does
not claim that unfinished product feature works.

## GKE, OIDC and legacy migration

For GKE, install `gke-gcloud-auth-plugin` using Google's instructions and
regenerate the intended cluster entry with `gcloud container clusters
get-credentials CLUSTER --location LOCATION`. Select that context in KubeRich.
Google documents this exec plugin as the client authentication mechanism.
[GKE setup and migration](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/cluster-access-for-kubectl).

External OIDC helpers use the same exec contract; KubeRich does not embed an
issuer, token exchange, keyring or browser-login implementation. An OIDC
`kubelogin get-token` entry without Azure's `--server-id` remains a generic
helper. For AKS, use the configured Azure kubelogin exec entry and
[AKS guidance](aks-authentication.md). For EKS, retain the intended
[AWS profile/role entry](eks-authentication.md).

Legacy `auth-provider` entries, including GCP/Azure/OIDC modes, and HTTP basic
username/password are explicitly unsupported. Migrate the selected entry to
the provider's exec helper or an explicit token/certificate user. KubeRich refuses
conflicting mechanisms and never guesses a replacement identity or rewrites
provider credential files. The automated provider-shaped fixtures verify local
contracts; they do not establish successful cloud exchange, tenant policies,
natural cache expiry or SSH browser forwarding.
