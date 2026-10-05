# Context sessions

C01 connects to Kubernetes for bounded namespace discovery. The terminal does not
yet show pods, watch resources, display logs or execute commands in containers.
C02 adds a separate [resource read backend](resource-discovery.md), qualified
independently of UI integration.
Connection errors remain in the UI so you can choose another context or retry.

## Start and select

```sh
uv run kubetrol
uv run kubetrol --context my-context --namespace my-namespace
uv run kubetrol --kubeconfig /path/to/config --context my-context -A --request-timeout 15s
```

An explicit `--kubeconfig` reads a single file. Otherwise `KUBECONFIG` is split
using the platform path separator, then `~/.kube/config` is used if the variable
is unset or empty. Missing entries in an environment list are skipped; a missing
explicit file returns exit 3. Duplicate paths are read once. The first file to
supply a current context or named entry wins; relative credential/CA/helper paths
resolve against that entry's originating file. Nothing rewrites these files or
the current context. Loading the catalogue runs no helpers and makes no requests.

Without configuration/current context the workspace stays disconnected. F2
shows the loaded contexts; it does not reload changed files. Restart after editing
kubeconfig. An explicit unknown context produces a configuration state without
falling back to another context.

- **c / F2**, `:ctx` or `:context`: choose a context; `:ctx NAME` selects it directly.
- **n / F3**, `:ns` or `:namespace`: choose a namespace; `:ns NAME` permits manual selection.
- **`:ns *`** or `*` in the selector: select all namespaces.
- **i / F5** or `:status`: read the full connection message in a scrollable dialog, including in narrow terminals.
- **r / F4** or `:retry`: reconnect the selected context with a fresh client and helper cache.
- **Ctrl+Q**: quit while connecting, selecting or editing an input.

Letter shortcuts work outside text inputs; typing in the filter or command field
keeps those letters. Press Escape to return to the resource table. If the terminal
intercepts a function key, use the letter or type the colon command and Enter.
Kubetrol cannot receive a key consumed by an outer terminal or tmux binding.

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

## Credentials and TLS

Supported now:

- Static bearer `token` or `tokenFile`; a token file is read when the session opens.
- Embedded or file-backed CA and client certificate/key pairs. Inline TLS data
  takes precedence over a file field. Copies live in a session-owned directory
  with mode 700 and files with mode 600; closure removes them.
- Noninteractive exec **token** credentials using `client.authentication.k8s.io/v1`
  or `v1beta1`. Kind/version must match the configured version. v1 requires
  `interactiveMode`; beta defaults to `IfAvailable`. `Never`/`IfAvailable` receive
  `KUBERNETES_EXEC_INFO.spec.interactive=false` and closed stdin. Args and configured
  environment variables are passed literally, without a shell. `provideClusterInfo`
  supplies cluster metadata including CA data and the reserved exec extension.
  Each session caches tokens until expiration, process closure or 401; a read
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
operator-invoked plugins. Their output, raw SDK errors and response bodies are
never printed or logged.

TLS verification is on by default. A native kubeconfig
`insecure-skip-tls-verify: true` or an HTTP endpoint displays **Insecure transport**
in the status, including with hidden headers. `tls-server-name` is honored.
Native `proxy-url` is explicit and tested with an owned local HTTP proxy; ambient proxy/netrc configuration is not used by
the API session. Proxy/provider combinations remain qualification work in C08.

Exec certificate rotation, helpers requiring stdin (`interactiveMode: Always`),
legacy `auth-provider` and basic username/password authentication are explicitly
unavailable with an authentication message. Log in outside the UI where supported,
or use a supported credential mechanism. EKS/AKS/GKE helper and actual provider
qualification remain C06/C07/C08; generic synthetic exec tests do not certify them.
CLI cluster/user/token/TLS/impersonation overrides remain gated by F05/C08.

## Connection states and bounds

| State | Meaning and action |
| --- | --- |
| Disconnected | No selected configuration; configure kubeconfig or use F2 |
| Connecting | Background authentication/discovery; inputs and quit stay responsive |
| Connected | Namespace discovery succeeded; resource views are upcoming |
| Limited | Listing namespaces returned 403; select an allowed namespace manually |
| Auth error | Missing/rejected/unsupported credentials or helper failure; check login and retry |
| TLS error | Invalid/untrusted certificates or hostname mismatch; check CA/server/client files |
| Timeout | Request exceeded the deadline; check connectivity or timeout and retry |
| Unreachable | Connection/network failure; check VPN/server address and retry |
| Config error | Invalid connection/catalogue fields; fix config or select another context |
| API error | Unexpected status, malformed/excessive response; check endpoint and retry |

A 403 cannot establish that any resource operation is authorized. The terminal
checkpoint attempts namespace discovery; C02 resource reads have their own
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
