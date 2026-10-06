# CLI and authentication compatibility

Reference: K9s v0.51.0,
[launch flags](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/cmd/root.go).
This is the first-release contract. The development build implements help/version
commands, `info`, `config init`/`check`, log options, read-only policy, initial
view/scope/help commands, three terminal visibility flags and C01 context/namespace sessions. It recognizes all 26
audited flags, with explicit unavailable errors for behavior that has not shipped.
Recognizing a flag does not establish Kubernetes or K9s compatibility.
See the development checkpoint below, [local preferences](configuration.md) and
[terminal controls](terminal-preview.md).
No Kubetrol application is publicly released yet.

Every explicitly registered launch flag is represented below. Kubetrol keeps the
familiar spelling as a compatibility alias; kebab-case aliases may also be
provided. No option may be accepted and ignored. Presentation/export features
scheduled later report that limitation until their owning task is implemented.

| K9s flag | Kubetrol behavior / owner |
| --- | --- |
| `--refresh`, `-r` | Validated refresh interval; F05/C03 |
| `--logLevel`, `-l` | Sanitized diagnostic severity; F03/F05 |
| `--logFile` | Diagnostic destination and permissions; F03/F05 |
| `--headless` | Hide header; B01/F05 (does not mean a noninteractive API) |
| `--logoless` | Hide logo; B01/F05 |
| `--crumbsless` | Hide breadcrumbs; B01/F05 |
| `--splashless` | Skip optional startup splash; B01/F05 |
| `--invert` | Invert theme while preserving useful contrast; U01 |
| `--all-namespaces`, `-A` | All permitted namespaces; C01/F05 |
| `--command`, `-c` | Initial resource/view command; B03/F05 |
| `--readonly` | Enforce read-only policy in services and UI; F04/F05/M01 |
| `--write` | Explicitly override configured read-only preference; F05/M01 |
| `--screen-dump-dir` | Chosen export directory; O06 |
| `--kubeconfig` | Explicit kubeconfig path; C01/F05 |
| `--request-timeout` | Validated API request timeout; C01/F05 |
| `--context` | Explicit initial context; C01/F05 |
| `--cluster` | Cluster override within effective config; C01/F05 |
| `--user` | Auth-info override within effective config; C01/F05 |
| `--namespace`, `-n` | Initial namespace; C01/F05 |
| `--as` | Server-authorized user impersonation; F05/C08/O04 |
| `--as-group` | Repeatable impersonation groups; F05/C08/O04 |
| `--insecure-skip-tls-verify` | Explicit insecure transport choice, visibly indicated; default remains verification; F05/C08 |
| `--certificate-authority` | CA file override; F05/C08 |
| `--client-key` | Client key file override; F05/C08 |
| `--client-certificate` | Client certificate override; F05/C08 |
| `--token` | Explicit token override, redacted everywhere; F05/C08 |

## Current development checkpoint: F05 stage 1, C01 and B03

| Options / commands | Tested behavior now |
| --- | --- |
| `help`, `--help`, `-h` | Launch help, including the owning task for unavailable options |
| `version`, `--version` | Installed distribution version with the program name |
| `version --short`, `version -s` | Version number only |
| `info`, `config init`, `config check`, `--config`, log options | Local diagnostic/preferences behavior; no credential loading |
| `--readonly`, `--write` | Override file/environment preference for this invocation; shared command policy, visible status |
| `--headless` | Hide the application header; status/controls remain visible |
| `--logoless` | Hide the brand, retaining build information where the layout permits |
| `--crumbsless` | Hide the current context/namespace scope bar; resource-view breadcrumbs do not exist yet |
| `--command`, `-c` | Initial available pod/context/namespace/help/status/history commands share the UI grammar; unsupported views/actions return exit 4; see [B03](command-navigation.md) |
| `--refresh`, `-r` | Validate/report seconds through `info` or `config check`; explicit terminal use returns exit 4 until C03 #24 |
| `--kubeconfig`, `--context`, `--namespace`/`-n`, `--all-namespaces`/`-A`, `--request-timeout` | Read-only catalogue, explicit background client and namespace discovery/selection; see [C01](context-sessions.md) |
| Cluster/user/token/TLS/impersonation CLI overrides | Exit 4 naming F05/C08; no files read or helpers run |
| `--splashless`, `--invert`, `--screen-dump-dir` | Exit 4; there is currently no splash, theme inversion or screen export to control |

Place global options before a subcommand. Scalar options repeated on the command
line use their last value; `--as-group` preserves every occurrence in order, but
impersonation is unavailable. `--as-group` requires `--as`; client key and client
certificate must be supplied together. Namespace/all-namespaces and readonly/write
are mutually exclusive, with owned errors that identify the conflicting flags.
Syntax/type errors do not echo rejected values. Pending string arguments are
bounded and reject controls; transport-specific validation and missing-file checks
are applied by the owning adapter. A missing explicit `--kubeconfig` now returns
local I/O exit 3; an absent default opens disconnected.

Connection, presentation and initial-command options are terminal-only and are refused by
`info`/`config`. Runtime preference options are allowed by `info`/`config check`,
where they affect the effective settings, but refused by `config init`.
`help`/`version` subcommands bypass preferences and credential loading and refuse
explicit runtime/config overrides. Standard `--help`/`--version` flags exit
immediately as inspection requests. Neither path opens logs.

Read-only policy is immutable for the invocation and shared by initial and
interactive command resolution. It refuses mutation, exec/shell, attach and
unclassified external-plugin actions independently of UI shortcuts. S03/S04 enforce this policy for the native container shell. Attach, workload
mutation and plugins remain unavailable. `:shell`/`:exec` opens the container
picker in write mode; startup `--command shell` is refused because shell
execution requires deliberate pod/container selection. M01 must enforce the
same guard before its effects and provide integration evidence. `--write` only changes an application preference;
it grants no API permission. The read-only indicator remains visible when the
header is hidden and after filter/status updates.

F05 remains open: this checkpoint does not complete the initial-release criteria.
C01 supplies real sessions and namespace discovery with tested credential mechanisms;
connection overrides remain F05/C08, C03 consumes refresh,
B03 supplies resource commands, and S03/S04 prove guarded interactive execution.
C08/M01 qualify the later authentication and mutation paths. The delivery record
must recheck these integrations before F05 closes; completion remains a first-release
gate rather than a parser-only claim. Shell completion stays with D13.

Exit codes: 0 success/inspection/normal terminal quit; 1 internal failure; 2 invalid
input or noninteractive launch; 3 local file/log failure; 4 recognized unavailable
behavior; 130 interrupted non-UI operation. See [error details](configuration.md).

First-release commands: `help`/`--help`, `version`/`--version`, `version --short`/`-s`, and
`info` are first-release contracts. `info` shows configuration/data/log paths and
dependency availability without printing credentials. Shell completion for
bash/zsh/fish/PowerShell is D13; dynamic context completion reads local names
without authenticating to clusters. TUI command aliases are a separate contract
in B03/B07/U02, including resource singular/plural/short names, `ctx`, `ns`, `can`,
`xray`, directory navigation, help and quit.

## Effective configuration

Explicit CLI arguments override Kubetrol environment settings, context-specific
settings, global settings and defaults, in that order. Kubeconfig selection uses
an explicit file first, otherwise the platform's KUBECONFIG list, otherwise the
standard user file. The loader must preserve kubeconfig merging rules and resolve
relative paths against the originating file. Ambiguous combinations such as
`--readonly --write` and `--namespace ... --all-namespaces` produce a clear error.

Use Kubetrol-prefixed environment names for application settings; document their
mapping from audited K9s names. Keep standard Kubernetes, AWS, Azure, Helm and
terminal environment contracts. The source inventory includes configuration
schema fields and environment identifiers; compatibility differences belong in
U06 and must never be silent. User config remains separate from K9s config unless
an explicit validated import is requested.

Ordinary context selection only changes Kubetrol's session. Explicit context
rename/delete is a separate M08 operation with preview, backup and atomic writes.
The effective identity must be the same for list/watch, logs, exec, forwarding
and Helm, even when flags override kubeconfig defaults.

## Authentication coverage

| Provider / mode | Integration | Required evidence |
| --- | --- | --- |
| EKS | kubeconfig exec with AWS CLI `eks get-token`; profiles, role and established SSO environment | C06 contract tests for expiry/refresh/errors; real-provider smoke recorded separately |
| AKS / Entra | Azure kubelogin exec; Azure CLI, device-code, service principal and workload identity contracts | C07 tests for interactive/noninteractive behavior, tenant/expiry/errors |
| GKE | Configured `gke-gcloud-auth-plugin` | C08 exec and environment contracts; opt-in provider smoke |
| Generic clusters | Token/token-file, embedded/file certs, exec/OIDC helper, proxies and TLS overrides | C01/C08 fake-API/TLS/credential fixtures and version matrix |

Kubetrol does not issue cloud credentials or create clusters. It respects existing
local credential helpers. Missing tools and expired sessions are actionable
errors; browser/device authentication cannot block the UI indefinitely. Test exec
v1/v1beta1, expirationTimestamp, certificate responses, interactiveMode,
provideClusterInfo, cancellation and malformed output explicitly. Python SDK
support must be demonstrated; gaps require adapter work before the claim ships.

[Official EKS guidance](https://docs.aws.amazon.com/eks/latest/userguide/create-kubeconfig.html),
[official AKS kubelogin guidance](https://learn.microsoft.com/en-us/azure/aks/kubelogin-authentication),
and [Kubernetes credential plugins](https://kubernetes.io/docs/reference/access-authn-authz/authentication/#client-go-credential-plugins)
are the upstream contracts. Read-only mode is an application behavior preference;
server-side RBAC remains the security boundary.
