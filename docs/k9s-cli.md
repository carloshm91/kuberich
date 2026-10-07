# CLI and authentication compatibility

Reference: K9s v0.51.0,
[launch flags](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/cmd/root.go).
This is the first-release contract. The development build implements help/version
commands, `info`, `config init`/`check`, log options, read-only policy, initial
view/scope/help commands, three terminal visibility flags, context/namespace sessions,
effective refresh and invocation connection overrides. It recognizes all 26
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

## Current development checkpoint: F05 connection integration

| Options / commands | Tested behavior now |
| --- | --- |
| `help`, `--help`, `-h` | Launch help, including the owning task for unavailable options |
| `version`, `--version` | Installed distribution version with the program name |
| `version --short`, `version -s` | Version number only |
| `info`, `config init`, `config check`, `--config`, log options | Local diagnostic/preferences behavior; no credential loading |
| `--readonly`, `--write` | Override file/environment preference for this invocation; shared command policy, visible status |
| `--headless` | Hide the application header; status/controls remain visible |
| `--logoless` | Hide the brand, retaining build information where the layout permits |
| `--crumbsless` | Hide the identity bar and resource-view navigation trail |
| `--command`, `-c` | Initial available pod/context/namespace/help/status/history commands share the UI grammar; unsupported views/actions return exit 4; see [B03](command-navigation.md) |
| `--refresh`, `-r` | Effective periodic table ages/local repaint (0.1–3600 seconds); watches remain live independently; validated/reportable through `info` and `config check` |
| `--kubeconfig`, `--context`, `--namespace`/`-n`, `--all-namespaces`/`-A`, `--request-timeout` | Read-only catalogue, explicit background client and namespace discovery/selection; see [C01](context-sessions.md) |
| Cluster/user/token/TLS/impersonation CLI overrides | Per-invocation effective connection shared by API reads, watches, logs and captured kubectl shells; source kubeconfigs stay unchanged |
| `--splashless`, `--invert`, `--screen-dump-dir` | Exit 4; there is currently no splash, theme inversion or screen export to control |

Place global options before a subcommand. Scalar options repeated on the command
line use their last value; `--as-group` preserves every occurrence in order, but
impersonation requires API-server authorization. `--as-group` requires `--as`; client key and client
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
unclassified external-plugin actions independently of UI shortcuts. S03/S04 and #121 enforce this policy for the embedded container shell. Attach, workload
mutation and plugins remain unavailable. `:shell`/`:exec` opens the container
picker in write mode; startup `--command shell` is refused because shell
execution requires deliberate pod/container selection. M01 must enforce the
same guard before its effects and provide integration evidence. `--write` only changes an application preference;
it grants no API permission. The read-only indicator remains visible when the
header is hidden and after filter/status updates.

F05 #19 completes the initial launch connection contract with the integrations
above. Provider qualification remains C06/C07/C08, later mutations remain M01,
and shell completion remains D13. Unsupported presentation/export flags continue
to fail explicitly until their owning feature ships.

## Effective invocation connection

`--cluster` and `--user` select named entries from the merged kubeconfig, overriding
the selected context's references. Missing aliases fail safely; there is no
fallback identity. The selected context and its namespace remain independent.
The header shows effective aliases/impersonated subject, while `:ctx` lists the
stored catalogue entries. Overrides persist across context switches for this
invocation and never rewrite the source kubeconfigs.

`--token` replaces the selected user's token-file, certificate, exec and legacy
mechanisms. A client certificate requires both `--client-certificate` and
`--client-key` and also replaces those mechanisms. Replaced helpers never run.
Token and client-certificate overrides are mutually exclusive, an intentional
restriction to make the effective identity unambiguous. Ordinary kubeconfig
credential support and its provider limits are described in [sessions](context-sessions.md).

`--certificate-authority` replaces inline/file CA material and enables verification.
`--insecure-skip-tls-verify` or `=true` explicitly clears CA material and disables
verification; `=false` forces verification using the selected CA/system trust.
Explicit CA and insecure=true cannot be combined. TLS server-name/proxy settings
stay with the selected cluster. Relative override paths are captured against the
launch directory; native kubeconfig paths retain their source-file directory.
Missing/invalid files surface as a safe connection state before resource calls.
Insecure transport remains visible even when the header is hidden.

`--as` replaces the complete stored impersonation identity: previous groups,
UID and extras are discarded. Repeat `--as-group` to choose groups for that
subject, retaining order and duplicates (maximum 64). Without `--as`, loaded
kubeconfig impersonation, including UID and bounded extras, is preserved.
The API server enforces impersonation and resource permissions; 401 and 403
remain distinct. Impersonation does not change the credentials used to authorize
the request itself. Headers and the private kubectl connection carry the same
effective identity.

Diagnostics never load these credentials or print tokens/private keys. Supplying
connection options to local inspection commands is refused. Credential strings
are bounded and reject controls; a command-line token is visible to the caller's
shell/history/process tooling, so an existing kubeconfig/token helper is preferable
for regular use. No token is persisted in Kubetrol preferences.

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
