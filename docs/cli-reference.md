# Commands, keys, and launch options

Generated from application declarations for source version `SOURCE_VERSION`.

Keys apply to the focused view. Inputs keep their normal editing keys;
configured additional keys and plugins can change effective shortcuts.
Press `?` in a view for its current actions. See [navigation](command-navigation.md).

## Launch options

| Option / aliases | Description |
| --- | --- |
| `help`: `-h`, `--help` | show this help message and exit |
| `version`: `-h`, `--help` | show this help message and exit |
| `version`: `--short`, `-s` | print only the version number |
| `info`: `-h`, `--help` | show this help message and exit |
| `bug-report`: `-h`, `--help` | show this help message and exit |
| `bug-report`: `--output` | new report file; existing files are refused |
| `config init`: `-h`, `--help` | show this help message and exit |
| `config check`: `-h`, `--help` | show this help message and exit |
| `config migrate`: `-h`, `--help` | show this help message and exit |
| `config`: `-h`, `--help` | show this help message and exit |
| `kubeconfig oidc-migration`: `-h`, `--help` | show this help message and exit |
| `kubeconfig`: `-h`, `--help` | show this help message and exit |
| `-h`, `--help` | show this help message and exit |
| `--version` | show program's version number and exit |
| `--config` | KubeRich preferences YAML (separate from kubeconfig) |
| `--kubeconfig` | single kubeconfig file (otherwise KUBECONFIG or ~/.kube/config) |
| `--context` | context to connect (otherwise current-context) |
| `--namespace`, `-n` | initial namespace (otherwise the context namespace) |
| `--all-namespaces`, `-A` | select all namespaces for this session |
| `--request-timeout` | API/helper timeout: 0.1-3600 seconds, or ms/s/m/h (default 10s) |
| `--log-file`, `--logFile` | local diagnostic log path |
| `--log-level`, `--logLevel`, `-l` | DEBUG, INFO, WARNING, ERROR, or CRITICAL |
| `--refresh`, `-r` | periodic table refresh seconds (0.1-3600); watch changes remain live |
| `--readonly` | block mutations, shell, attach and plugins |
| `--write` | override the configured read-only preference for this session |
| `--command`, `-c` | initial terminal command: po, ctx, ns, helm, manifests, node-shell-recover, pulse, overview, exports, benchmarks, themes, views, about, status, retry, back, forward, help or quit |
| `--screen-dump-dir` | initial local export directory; created privately only on Save |
| `--benchmark-directory` | local benchmark result directory; created privately only by an explicit run |
| `--headless` | hide the application header |
| `--logoless` | hide the brand in the header |
| `--crumbsless` | hide the context/namespace scope bar |
| `--invert` | invert this session theme with readable contrast |
| `--splashless` | unavailable: startup splash |
| `--cluster` | kubeconfig cluster alias for this invocation |
| `--user` | kubeconfig auth-info alias for this invocation |
| `--as` | user/service account to impersonate; server permission required |
| `--as-group` | impersonation group; repeat to retain multiple groups |
| `--insecure-skip-tls-verify` | skip TLS verification explicitly; accepts =true or =false |
| `--certificate-authority` | CA certificate file; enables TLS verification |
| `--client-key` | client private key file; requires --client-certificate |
| `--client-certificate` | client certificate file; requires --client-key |
| `--token` | bearer token override; never included in diagnostics |

## Local CLI commands

Global options go before the command. Use `kuberich COMMAND --help` for its options.

| Command | Description |
| --- | --- |
| `kuberich help` | show launch help without loading configuration |
| `kuberich version` | show installed version without loading configuration |
| `kuberich info` | show safe local paths, preferences and installed versions |
| `kuberich bug-report` | write a private redacted diagnostic bundle |
| `kuberich config` | initialize, validate or migrate local preferences |
| `kuberich config init` | create defaults without overwriting existing files |
| `kuberich config check` | validate effective preferences without writing files |
| `kuberich config migrate` | copy legacy defaults without deleting or overwriting files |
| `kuberich kubeconfig` | inspect an explicitly selected kubeconfig locally |
| `kuberich kubeconfig oidc-migration` | print a secret-free OIDC exec migration fragment without writing files |

## In-app commands

Type `:` before an alias. Arguments and resource requirements depend on the task;
registration alone does not make a command available in every view or at launch.
Resource aliases are in the [resource reference](resource-reference.md).

| Aliases | Action |
| --- | --- |
| `about` | about |
| `annotate` | annotate |
| `attach` | attach |
| `back` | back |
| `benchmark` | benchmark |
| `benchmarks` | benchmarks |
| `can-i` | can i |
| `cleanup` | cleanup |
| `columns` | columns |
| `context`, `contexts`, `ctx` | contexts |
| `cordon` | cordon |
| `create` | create |
| `debug` | debug |
| `delete` | delete |
| `deletebatch` | delete batch |
| `diagnose` | diagnose |
| `diagnostics` | diagnostics |
| `download` | download |
| `drain` | drain |
| `edit` | edit |
| `ev`, `event`, `events` | events |
| `export` | export |
| `exports` | exports |
| `forward` | forward |
| `helm` | helm |
| `helmcharts` | helm catalog |
| `?`, `help` | help |
| `hist`, `history` | history |
| `jump` | jump |
| `login` | login |
| `logsall` | logs all |
| `manifests` | manifests |
| `namespace`, `namespaces`, `ns` | namespaces |
| `node-shell` | node shell |
| `node-shell-recover` | node shell recover |
| `open` | open relationship |
| `pluginjobs` | plugin jobs |
| `plugins` | plugins |
| `po`, `pod`, `pods` | pods |
| `popeye` | popeye |
| `portforward` | port forward |
| `pf`, `portforwards` | port forwards |
| `overview`, `pulse` | pulse |
| `exit`, `q`, `quit` | quit |
| `rbac` | rbac |
| `refresh` | refresh |
| `rename` | rename |
| `restart` | restart |
| `resume` | resume |
| `retry` | retry |
| `rollback` | rollback |
| `rollout` | rollout |
| `rules` | rules |
| `scale` | scale |
| `server` | server |
| `exec`, `shell` | shell |
| `status` | status |
| `suspend` | suspend |
| `theme`, `themes` | themes |
| `trigger` | trigger |
| `uncordon` | uncordon |
| `upload` | upload |
| `usedby` | used by |
| `views` | views |
| `who-can` | who can |
| `writes` | writes |
| `xray` | xray |
| `resource NAME[.GROUP][/VERSION] [NAMESPACE or *]` | Browse a discovered resource |
| `plugin NAME` | Review a configured local plugin |

### Local view controls

`:!!`, `:copy`, `:copyns`, `:copytext`, `:crumbsless`, `:errors`, `:favorite`, `:favorites`, `:fullscreen`, `:headless`, `:mark`, `:range`, `:selectall`, `:selectnone`, `:wide`.

`favorite` takes `add NAMESPACE` or `remove NAMESPACE`; other local view controls
take no arguments. `!!` repeats through the normal checks, without confirming a write.

## Additional navigation defaults

Each row is generated from an effective default key profile. Fixed arrows and
page keys stay available. Table Home/End move horizontally; Ctrl+Home/End select
first/last rows. Uppercase letters are distinct keys, not Vim sequences.

Profile 1: `table`, `contexts`, `containers`, `container-inspection`, `history`, `data`, `themes`, `forwards`, `sources`.
Profile 2: `resources`, `events`, `namespaces`.
Profile 3: `logs`, `text`.

| Action | Profile 1 | Profile 2 | Profile 3 |
| --- | --- | --- | --- |
| down | `j` | `j` | `j` |
| first | `g` | `g` | `g` |
| half down | `J` | `J` | `ctrl+d` |
| half up | `ctrl+u` | `ctrl+u` | `ctrl+u` |
| last | `G` | `G` | `G` |
| left | `h` | `h` | `h` |
| page down | `ctrl+f` | `ctrl+f` | `ctrl+f` |
| page up | `ctrl+b` | `ctrl+b` | `ctrl+b` |
| reverse sort | — | `S` | — |
| right | `alt+l` | `alt+l` | `l` |
| sort | — | `s` | — |
| up | `k` | `k` | `k` |

## View action keys

| View | Key | Action |
| --- | --- | --- |
| Containers | `l` | Logs |
| Containers | `s, x` | Shell |
| Containers | `a` | Attach |
| Containers | `u` | Upload |
| Containers | `d` | Download |
| Containers | `e` | Environment / image |
| Containers | `M` | Metric history |
| Diagnostic evidence | `o` | Open resource |
| Diagnostic evidence | `e` | Open Event |
| Diagnostic evidence | `n` | Next Event |
| Diagnostic evidence | `l` | Current logs |
| Diagnostic evidence | `p` | Previous logs |
| Diagnostic evidence | `r` | Refresh evidence |
| Diagnostic evidence | `escape` | Back |
| Embedded terminal | `tab` | Focus Next |
| Embedded terminal | `shift+tab` | Focus Previous |
| Embedded terminal | `ctrl+c,super+c` | Copy selected text |
| Events | `j` | Down |
| Events | `k` | Up |
| Events | `g` | First row |
| Events | `G` | Last row |
| Events | `ctrl+b` | Page up |
| Events | `ctrl+f` | Page down |
| Events | `ctrl+u` | Half page up |
| Events | `J` | Half page down |
| Events | `h` | Scroll left |
| Events | `alt+l` | Scroll right |
| Events | `s` | Next sort field |
| Events | `S` | Reverse sort |
| Events | `question_mark` | Keys |
| Events | `w` | Warnings |
| Events | `t` | Groups |
| Inspection | `y` | YAML |
| Inspection | `d` | Details |
| Inspection | `e` | Events |
| Inspection | `L` | Links |
| Inspection | `m` | Managed fields |
| Inspection | `slash` | Search |
| Inspection | `n` | Next match |
| Inspection | `N` | Previous match |
| Inspection | `ctrl+y` | Copy |
| Logs | `c` | Container |
| Logs | `v` | Previous |
| Logs | `o` | Window |
| Logs | `p` | Pause |
| Logs | `f` | Follow |
| Logs | `t` | Timestamps |
| Logs | `w` | Wrap |
| Logs | `L` | Column lock |
| Logs | `C` | Clear |
| Logs | `m` | Mark |
| Logs | `z` | Fullscreen |
| Logs | `slash` | Search |
| Logs | `n` | Next match |
| Logs | `N` | Previous match |
| Logs | `question_mark` | Help |
| Logs | `ctrl+y` | Copy |
| Logs | `ctrl+s` | Save |
| Relationships | `right` | Expand relationship |
| Relationships | `left` | Collapse relationship |
| Relationships | `shift+right, alt+l` | Scroll right |
| Relationships | `shift+left, h` | Scroll left |
| Relationships | `j` | Down |
| Relationships | `k` | Up |
| Relationships | `g` | First row |
| Relationships | `G` | Last row |
| Relationships | `ctrl+b` | Page up |
| Relationships | `ctrl+f` | Page down |
| Relationships | `ctrl+u` | Half page up |
| Relationships | `J` | Half page down |
| Relationships | `question_mark` | Keys |
| Workspace | `slash` | Filter |
| Workspace | `colon` | Cmd |
| Workspace | `question_mark, f1` | Help |
| Workspace | `y` | YAML |
| Workspace | `d` | Details |
| Workspace | `e` | Events |
| Workspace | `E` | Edit |
| Workspace | `v` | Data keys |
| Workspace | `ctrl+d` | Review deletion |
| Workspace | `l` | Logs |
| Workspace | `L` | Aggregate logs |
| Workspace | `x` | Shell |
| Workspace | `F` | Port forward |
| Workspace | `c, f2` | Contexts |
| Workspace | `n, f3` | Namespaces |
| Workspace | `r, f4` | Retry |
| Workspace | `i, f5` | Status |
| Workspace | `M` | Metric history |
| Workspace | `o` | Open resource |
| Workspace | `alt+left` | Previous view |
| Workspace | `alt+right` | Next view |
| Workspace | `space` | Mark |
| Workspace | `shift+down` | Extend selection |
| Workspace | `shift+up` | Extend selection |
| Workspace | `ctrl+y` | Copy name |
| Workspace | `escape` | Back |
| Workspace | `q, ctrl+q, ctrl+c` | Quit |
