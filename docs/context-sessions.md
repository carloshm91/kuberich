# Connect to a context

Choose an explicit context from a trusted kubeconfig. KubeRich uses that file's
endpoint, TLS settings, and credentials; it does not provision clusters or keep
a separate cloud identity database.

## Select configuration and scope

```sh
kuberich --kubeconfig /absolute/path/to/kubeconfig --context demo-lab --namespace demo-apps --readonly
```

The names are fictional. An explicit `--kubeconfig` selects one file. Otherwise,
KubeRich merges paths from `KUBECONFIG`, or reads `~/.kube/config` when it is empty.
The first file supplying a named entry wins. Relative credential, CA, and helper
paths resolve against the file that supplied that entry.

`:ctx` opens the context table; Enter connects to the selected context.
`:ctx NAME` connects directly. `:ns` opens namespaces, `:ns NAME` selects a known
namespace, and `:ns *` selects all namespaces. `--namespace` and `-A` are mutually
exclusive. Selecting scope never grants permissions or rewrites current-context.

The context list is loaded at launch. Restart after another tool changes
kubeconfig. An unknown explicit context produces an error without falling back.
Without a configured current context, the workspace stays disconnected.

## Authenticate

Static tokens, token files, CA certificates, and client certificate/key pairs are
supported. Exec credential helpers can return tokens or paired TLS certificates
using `client.authentication.k8s.io/v1` or `v1beta1`. Version v1 requires
`interactiveMode`. Explicit `username`/`password` Basic authentication is also
supported, including an empty half, without a password prompt. Basic credentials
stay separate from bearer tokens; mixed credential mechanisms are refused.
Legacy `auth-provider` entries need migration to a supported helper.

A kubeconfig helper runs as your local user, including in read-only mode. Trust
the executable, arguments, environment, and kubeconfig before opening a session.
Ordinary background authentication uses closed stdin. Helpers keep their own
provider caches; KubeRich caches their response for this connection until expiry,
rejection, or closure. A read rejected with 401 can refresh once. Resource writes
are never replayed automatically.

For a helper that needs interaction, type `:login`. KubeRich temporarily gives the
native terminal to the declared helper and restores the workspace afterward.
Credential JSON on stdout stays private; the helper controls its terminal prompts
and stderr. Ctrl+C cancels login. `:login` runs the declared entry and does not
invent a provider login command. A native interactive terminal is required.

## EKS

Install the AWS CLI required by your kubeconfig's `aws eks get-token` entry.
Its profiles, role assumption, SSO cache, and environment decide the AWS identity.
For an SSO profile, complete login outside KubeRich, then use `:retry`:

```sh
aws sso login --profile demo-profile
```

Use your actual configured profile. A missing CLI, expired session, denied role,
or rejected token produces an authentication message. Check the same profile,
PATH, and environment used when launching KubeRich. See
[AWS EKS connection setup](https://docs.aws.amazon.com/eks/latest/userguide/create-kubeconfig.html).

## AKS

Install Azure kubelogin and use its declared `kubelogin get-token` exec entry.
Azure CLI, device-code, service-principal, and workload-identity settings belong
to that tool. For `azurecli` mode, establish the intended `az login` session
outside KubeRich. A device-code prompt during background authentication offers
`:login`; it does not display the private code in a widget or open a browser
automatically. See [AKS authentication](https://learn.microsoft.com/en-us/azure/aks/kubelogin-authentication).

## GKE and other exec helpers

Install the provider's current helper, such as `gke-gcloud-auth-plugin`, and
regenerate a kubeconfig that declares it as an exec entry. Establish any required
provider login before launching KubeRich. The generic Kubernetes exec protocol
also supports compatible OIDC helpers. Provider login policy, keyrings, browser
forwarding, and real-account compatibility depend on your environment; local
helper support does not certify every EKS, AKS, or GKE account.

## Migrate a legacy OIDC entry

Print a proposed exec fragment from an explicitly selected kubeconfig:

```sh
kuberich --kubeconfig /absolute/path/to/kubeconfig --context demo-lab kubeconfig oidc-migration
```

This command stays offline, runs no helper, and changes no file. Install
int128/kubelogin separately, review its issuer, client, CA, and scopes, then apply
the fragment yourself. Replace any fixed client-secret placeholder in a private
configuration. Existing ID, refresh, and client-secret values are never copied;
the helper handles future sign-in and refresh. Relative issuer CA paths resolve
against the file that supplied the user entry.

## TLS, proxies, and overrides

TLS verification is enabled by default. `tls-server-name`, configured CA data,
and client certificates are respected. HTTP endpoints or
`insecure-skip-tls-verify: true` show **Insecure transport**. Do not bypass
verification to hide a certificate error; correct the endpoint, hostname, or CA.

A kubeconfig `proxy-url` takes precedence over inherited HTTP(S)_PROXY settings;
NO_PROXY applies when no explicit proxy is selected. HTTP(S) and SOCKS5 proxy
settings are accepted, with transport-specific limits. Explicit launch flags can
override the cluster, user, server, token, TLS, and impersonation for this
invocation; see the [command reference](cli-reference.md). They also apply after
context changes and to the private connection passed to kubectl.

Shells, attach, transfers, forwards, and plugins use a private connection file.
Changing the source kubeconfig after connection cannot redirect those actions.
Provider helpers remain external programs and may update their own caches.

## Kubeconfig compatibility

The v1 field inventory is identical in upstream kubectl/client-go 1.35, 1.36 and
1.37. The table applies to all three schemas; local contracts and the separately
pinned integration client establish only the behavior actually tested. Cluster
version skew and real provider sign-in still need their own qualification.

| Fields | Behavior |
| --- | --- |
| `apiVersion`, `kind` | Accept omitted/empty values or `v1`/`Config`; other values name the invalid field |
| `clusters`, `users`, `contexts`, named `name` and payload | First whole named entry wins across merged files; each entry keeps its source directory |
| `current-context`, `KUBECONFIG` list | First nonempty current context wins; explicit file overrides the list; no source write |
| `preferences.colors`, `preferences.extensions` | Accepted deprecated metadata; does not change terminal preferences |
| Top-level, cluster, user and context `extensions`; `name`, `extension` | Named opaque metadata, including scalar payloads; reserved cluster exec extension is passed only when requested |
| Context `cluster`, `user`, `namespace` | Explicit aliases; empty user is anonymous, empty namespace means `default` |
| Cluster `server` | HTTP(S), including URL path prefixes; embedded credentials/query/fragment refused by field |
| `tls-server-name`, `insecure-skip-tls-verify` | Explicit verification name/policy; insecure transport remains visible |
| `certificate-authority`, `certificate-authority-data` | Source-relative paths; nonempty inline data wins, empty data falls back to file |
| `proxy-url` | HTTP(S)/SOCKS5; session proxy environment when omitted/empty; no silent proxy bypass |
| `disable-compression` | Boolean accepted and kept for delegation; the HTTP client already requests identity encoding |
| User `client-certificate`, `client-key`, `client-certificate-data`, `client-key-data` | Paired private session copies; encrypted keys refused before a passphrase prompt |
| `token`, `tokenFile` | Size-limited bearer values; last successful file value wins, refresh and one read-only 401 retry |
| `username`, `password` | Explicit Basic identity, including empty half; no implicit prompt or netrc fallback |
| `as`, `as-uid`, `as-groups`, `as-user-extra` | Validated repeated impersonation attributes; subject required |
| `exec.command`, `exec.args`, `exec.env.name/value` | Literal argv/environment and source directory; helper with output/time limits |
| `exec.apiVersion`, `exec.interactiveMode` | v1/v1beta1 and explicit native login policy; unsupported versions name the field |
| `exec.installHint` | Metadata accepted; KubeRich displays fixed safe installation guidance |
| `exec.provideClusterInfo` | Boolean; only true supplies effective cluster metadata and reserved extension |
| `auth-provider.name`, `.config` | Field-specific migration hint; OIDC fragment generation preserves checked metadata only |
| OIDC `idp-issuer-url`, `client-id`, `idp-certificate-authority`, `idp-certificate-authority-data` | Validated issuer/client metadata and source-relative CA become literal helper options |
| OIDC `client-secret`, `id-token`, `refresh-token`, `extra-scopes` | Secret placeholder and manual scope review; existing credential values never copied |

Mixed credential mechanisms are refused with their field names; choose the
intended identity or use an explicit invocation override. File/argument/YAML
bounds remain application limits. Unsupported fields never trigger another user,
context, helper or ambient credential fallback.

## Recover a connection

Type `:status` for the complete message and `:retry` after correcting it.
`:login` is for interaction with the declared helper. Retry replaces the current
connection and stops its logs, shells, forwards, and other session work first.
A namespace-list 403 allows manual namespace selection; it does not establish
permission to read or change resources there.

`--request-timeout` defaults to ten seconds and accepts 0.1–3600 seconds using
seconds or `ms`, `s`, `m`, and `h` suffixes. Increase it deliberately for a slow
connection. See [troubleshooting](troubleshooting.md) for status meanings.

## Rename or delete a local context

In `:ctx`, select a context and use `:rename NEW` or `:delete`. These actions edit
kubeconfig and require write mode. Review identifies the file and change; a
separate Confirm saves it. Cluster and user entries stay unchanged.

Renaming current-context updates its name too. Deleting that file's current
context requires typing `DELETE CURRENT`; other deletions require `DELETE`.
You cannot delete the context KubeRich is currently using. Switch first.
A private backup is written beside the file before replacement. Restore it
explicitly if needed. Comments and custom YAML formatting are lost on rewrite.

If the file changes after Review, review again. Ambiguous entries across multiple
files are refused. A renamed connected context reconnects under its new name.

## Provider documentation

Use the provider's instructions for its CLI, login mode, and kubeconfig entry:

- [AWS EKS access](https://docs.aws.amazon.com/eks/latest/userguide/create-kubeconfig.html)
- [Microsoft AKS authentication](https://learn.microsoft.com/en-us/azure/aks/kubelogin-authentication)
- [Google GKE authentication](https://cloud.google.com/kubernetes-engine/docs/how-to/cluster-access-for-kubectl)
