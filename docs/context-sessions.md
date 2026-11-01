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
`interactiveMode`. Legacy `auth-provider` and basic credentials are unsupported;
regenerate those entries with a current provider tool or use a supported method.

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
