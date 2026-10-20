# Context sessions

Each selected context owns an independent connection. The workspace lists and
watches the selected resource scope, reports live/stale/error states and retains
its latest snapshot during temporary failures. It includes live resource tables,
details, container logs and embedded shells. See [navigation](command-navigation.md)
and [authentication setup](kubeconfig-interoperability.md) for the related workflows.
Connection errors remain in the UI so you can choose another context or retry.

## Start and select

```sh
uv run kuberich
uv run kuberich --context my-context --namespace my-namespace
uv run kuberich --kubeconfig /path/to/config --context my-context -A --request-timeout 15s
```

An explicit `--kubeconfig` reads a single file. Otherwise `KUBECONFIG` is split
using the platform path separator, then `~/.kube/config` is used if the variable
is unset or empty. Missing entries in an environment list are skipped; a missing
explicit file returns exit 3. Duplicate paths are read once. The first file to
supply a current context or named entry wins; relative credential/CA/helper paths
resolve against that entry's originating file. Selecting or switching a context
never rewrites these files or the current context. Loading the catalogue runs no
helpers and makes no requests.

Without configuration/current context the workspace stays disconnected. F2
shows the loaded contexts; it does not reload files changed by other tools.
Restart after editing kubeconfig elsewhere. An explicit unknown context produces
a configuration state without falling back to another context.

- **c / F2**, `:ctx` or `:context`: browse the local context workspace table;
  `/` filters, Enter connects and Escape restores the preceding resource view.
  `:ctx NAME` selects it directly.
- **n / F3**, `:ns` or `:namespace`: choose a namespace; `:ns NAME` permits manual selection.
- **`:ns *`** or `*` in the selector: select all namespaces.
- **i / F5** or `:status`: read the full connection message in a scrollable dialog, including in narrow terminals.
- **r / F4** or `:retry`: reconnect the selected context with a fresh client and helper cache.
- **Ctrl+Q**: quit while connecting, selecting or editing an input.

Letter shortcuts work outside text inputs; typing in the filter or command field
keeps those letters. Press Escape to return to the resource table. If the terminal
intercepts a function key, use the letter or type the colon command and Enter.
KubeRich cannot receive a key consumed by an outer terminal or tmux binding.

Selectors support arrows, PageUp/PageDown, mouse and Esc/Back. Names are rendered
as literal text. Selecting a namespace records a scope; it does not grant RBAC
permissions. `--namespace` overrides context defaults and `-A` selects all.
They are mutually exclusive. `--request-timeout` accepts seconds or ms/s/m/h,
from 0.1 through 3600 seconds; the default is 10 seconds. Discovery has a total
request deadline and helpers have bounded deadlines too.

Each context replacement cancels and awaits the previous request/helper, closes
the previous explicit SDK client and removes its private TLS files before opening
the next client. The session has a context, generation and client UUID. Namespace
changes advance the generation; selected scopes are remembered per context for
this process without writing preferences. Responses from an earlier connection attempt
cannot update the screen. No SDK global defaults are changed. Normal/error quit
awaits cleanup and restores the terminal.

## Rename or delete a context

Open `:ctx` and move the cursor to a context. Then:

- `:rename NEW` renames it. `:rename` alone opens the form with an empty name.
- **Ctrl+D** or `:delete` deletes it.

Nothing is saved until you choose Review and then Confirm. Review shows the
kubeconfig file that will change and what will change in it. Cancel, or Escape,
leaves the file as it was.

- Only the context entry changes. Its cluster and user entries stay, because
  other contexts may still use them.
- If the context is the file's `current-context`, a rename updates that value
  too. A delete removes it, and you must type `DELETE CURRENT` to confirm. Other
  deletes ask you to type `DELETE`.
- You cannot delete the context KubeRich is using now. Switch to another
  context first. Renaming it reconnects with the new name.
- Before saving, KubeRich writes a backup next to the file, for example
  `config.kuberich-20261019T101500000000.bak`. Only you can read the backup.
  To undo a change, copy the backup over the file.
- The new file replaces the old one in a single step, so a crash cannot leave
  it half-written. The file keeps its permissions. If the path is a symbolic
  link, the file it points to is changed and the link stays.
- If the file changed after Review, nothing is saved. Review again.
- The file is written again from its parsed contents. Comments and custom
  formatting are lost; Review warns you when the file has comments.

KubeRich refuses to guess when the change is unclear. This happens when the
same context name appears in more than one `KUBECONFIG` file, or when a
different file sets it as `current-context`. Edit those files yourself.
`--readonly` blocks rename and delete.

## Credentials and TLS

Supported now:

- Static bearer `token` or periodically refreshed `tokenFile`; the last successfully
  read file value takes precedence over an explicit configured token.
- Embedded or file-backed CA and client certificate/key pairs. Inline TLS data
  takes precedence over a file field. Copies live in a session-owned directory
  with mode 700 and files with mode 600; closure removes them.
- Exec **token or paired TLS certificate/key** credentials using `client.authentication.k8s.io/v1`
  or `v1beta1`. Kind/version must match the configured version. v1 requires
  `interactiveMode`; beta defaults to `IfAvailable`. `Never`/`IfAvailable` receive
  `KUBERNETES_EXEC_INFO.spec.interactive=false` and closed stdin. Args and configured
  environment variables are passed literally, without a shell. `provideClusterInfo`
  supplies cluster metadata including CA data and the reserved exec extension.
  Each session caches credentials until expiration, process closure or 401; a read
  rejected with 401 invalidates and retries once. Helpers drain both output pipes,
  cap stdout at 1 MiB/stderr at 64 KiB, and kill/reap their owned process group on
  failure, timeout, cancellation and completion.

Optional exec `args` and `env` lists may be absent, null or empty. This includes
the `env: null` form emitted in DigitalOcean/doctl kubeconfigs. Null lists are
treated as empty; malformed non-list values still produce a safe auth error.
This compatibility fix does not qualify every provider/login combination.

Kubeconfig is trusted local configuration: configured helpers run with your user
privileges, including in application read-only mode. Never launch with an
untrusted kubeconfig. Helpers are authentication tools, separate from future
operator-invoked plugins. Their credential stdout, raw SDK errors and response bodies are never printed
or logged. Explicit `:login` sends the configured native helper's prompt/stderr
to the terminal during the handoff; it is not retained in diagnostics.

TLS verification is on by default. A native kubeconfig
`insecure-skip-tls-verify: true` or an HTTP endpoint displays **Insecure transport**
in the status, including with hidden headers. `tls-server-name` is honored.
Native `proxy-url` supports HTTP(S)/SOCKS5. Without a nonempty explicit proxy,
captured HTTP(S)_PROXY/NO_PROXY settings apply. Automatic netrc identity remains
disabled. Owned real proxy/TLS contracts and Kubernetes HTTP CONNECT qualify
local behavior; [interoperability guidance](kubeconfig-interoperability.md)
records precedence, cleanup and SOCKS5 streaming limits.

KubeRich supports exec certificate renewal and native helper `:login`, including
the exact declared stdin behavior, private stdout and restored terminal.
Legacy `auth-provider` and basic credentials remain explicitly unsupported;
the same guide describes migration to exec/token/certificate entries.
Credential behavior is verified locally. Real EKS/AKS/GKE compatibility requires
separate provider trials; synthetic tests do not certify cloud tenants.
See [EKS](eks-authentication.md) and [AKS](aks-authentication.md) limits.
CLI cluster/user/token/TLS/impersonation overrides are supported;
see the [effective launch connection](k9s-cli.md#effective-invocation-connection).
They apply to this invocation, including context changes, reads, watches, logs
and the private captured kubectl shell connection. Real provider qualification
requires separate authorized trials.

## Connection states and bounds

| State | Meaning and action |
| --- | --- |
| Disconnected | No selected configuration; configure kubeconfig or use F2 |
| Connecting | Background authentication/discovery; inputs and quit stay responsive |
| Connected | Namespace discovery succeeded; resource status separately reports pod synchronization |
| Limited | Listing namespaces returned 403; select an allowed namespace manually |
| Auth error | Missing/rejected/unsupported credentials or helper failure; check login and retry |
| TLS error | Invalid/untrusted certificates or hostname mismatch; check CA/server/client files |
| Timeout | Request exceeded the deadline; check connectivity or timeout and retry |
| Unreachable | Connection/network failure; check VPN/server address and retry |
| Config error | Invalid connection/catalogue fields; fix config or select another context |
| API error | Unexpected status, malformed/excessive response; check endpoint and retry |

A 403 cannot establish that any resource operation is authorized. The terminal
connection attempts namespace discovery; resource reads have their own
explicit permission/error results. Namespace discovery follows at most
32 pages and retains at most 2048 namespace names, with 1 MiB per response;
exceeding a limit is a visible error rather than a truncated successful list.
Automatic response decompression and redirects are disabled. Kubeconfig reads
are limited to 32 paths, 1 MiB per file, 2048 named entries per merged section,
30 YAML nesting levels and 65536 parser events. Aliases, duplicate mapping keys,
duplicate names within a file and nonregular files are rejected. These are
application limits, not Kubernetes API limits.

## Qualification

Unit tests exercise merge precedence, path provenance, invalid configurations and
scope decisions. Fake numeric-loopback HTTP/TLS servers test real API requests,
static/token-file/client-certificate auth, 401/403, pagination/limits, invalid CAs,
TLS names, timeouts and cancellation. Synthetic helper scripts test exec contracts,
expiry/refresh, concurrent output, malformed responses, cancellation and reaping.
Pilot and PTYs verify responsive selectors, switching, quit and terminal restoration.
Installed artifacts and the OS/Python matrix qualify the same code.

`scripts/verify_contexts_kind.py --kind /path/to/verified-kind` creates a uniquely
named local kind cluster with an explicit temporary kubeconfig, verifies namespace
listing, TLS/client-certificate authentication, generations, resource discovery,
consistent paginated snapshots and client cleanup,
then deletes only its owned cluster in `finally`. It never selects an ambient
cluster. CI requires this check on Linux/Python 3.12 and retains sanitized JSON
evidence. The binary/version/image are pinned in the workflow/script.

Sources: [kubeconfig merge rules](https://kubernetes.io/docs/concepts/configuration/organize-cluster-access-kubeconfig/),
[exec credential contract](https://kubernetes.io/docs/reference/access-authn-authz/authentication/#client-go-credential-plugins),
[kubeconfig schema](https://kubernetes.io/docs/reference/config-api/kubeconfig.v1/),
[kind quick start](https://kind.sigs.k8s.io/docs/user/quick-start/).
