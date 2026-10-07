# Local preferences and diagnostics

This development build provides `info`, `config init`, `config check`, and local
diagnostic logging, alongside the [terminal preview](terminal-preview.md).
Preference inspection does not connect to Kubernetes. The UI applies built-in themes and displays
read-only mode in both header/status and shared command decisions. The native shell service applies the shared read-only guard before preparation.

## Commands

```sh
uv run kubetrol info
uv run kubetrol config check
uv run kubetrol config init
uv run kubetrol --config /path/to/preferences.yaml config check
uv run kubetrol --log-level DEBUG --log-file /path/to/kubetrol.log
```

Place global flags before a command. `--logLevel`/`-l` and `--logFile` are aliases
for `--log-level` and `--log-file`. `--config` selects **Kubetrol preferences**;
`--kubeconfig` selects Kubernetes connection configuration for a terminal launch.

`info` prints JSON with installed versions, local config/data/log paths, validated
effective preferences, unknown-field count and migration status. It never prints
unknown field names/values, credential environment variables or kubeconfig
contents. `info` and `config check` create no files. They do not execute cloud
credential helpers or inspect/connect to a cluster.

`config init` creates schema-v1 defaults at the selected path. It never overwrites
an existing file, persists environment overrides, or creates diagnostic logs.
All runtime overrides are rejected for this command. You can edit the YAML with your
own editor and run `config check` afterward. There is no automatic rewrite on load.

## Paths and precedence

The config path is chosen from `--config`, then `KUBETROL_CONFIG`, then
[platformdirs](https://platformdirs.readthedocs.io/en/latest/api.html). An absent
default file uses the defaults below. An explicitly selected missing file fails
with exit 3; use `config init` to create it. Empty/comment-only files also use
defaults. Paths expand `~`, support spaces and reject control characters.

| Platform | Default preferences | Default diagnostic log |
| --- | --- | --- |
| Linux | `$XDG_CONFIG_HOME/kubetrol/config.yaml` or `~/.config/kubetrol/config.yaml` | `$XDG_STATE_HOME/kubetrol/log/kubetrol.log` or `~/.local/state/kubetrol/log/kubetrol.log` |
| macOS | `~/Library/Application Support/kubetrol/config.yaml` | `~/Library/Logs/kubetrol/kubetrol.log` |

`info` reports the actual paths on your machine. Preference operations never
load Kubernetes credentials or change kubeconfig or its `current-context`. Files recognized as
kubeconfig are rejected as preferences. Startup never writes preference files.

Preference precedence is **explicit runtime CLI override → `KUBETROL_*`
environment → selected YAML → defaults**. Each layer is validated; a malformed
file/environment value fails even if a higher layer would override it. This
prevents an invalid lower layer from silently resurfacing on the next invocation.
The file is always read; log flags do not bypass a broken config.

| YAML field | Default | Environment | Runtime CLI |
| --- | --- | --- | --- |
| `shell` | `["sh"]` | Not available | Not available; configure YAML |
| `theme` | `k9s` | `KUBETROL_THEME` | Not yet available |
| `refresh_seconds` | `2.0` | `KUBETROL_REFRESH` | `--refresh`, `-r`; periodic table ages/local repaint, independent of live watches |
| `read_only` | `false` | `KUBETROL_READONLY` | `--readonly` / `--write` (mutually exclusive) |
| `log_level` | `WARNING` | `KUBETROL_LOG_LEVEL` | `--log-level`, `--logLevel`, `-l` |
| `log_file` | `null` (platform path) | `KUBETROL_LOG_FILE` | `--log-file`, `--logFile` |

Environment read-only values are `true`/`false`, case insensitive. Levels accept
DEBUG, INFO, WARNING, ERROR or CRITICAL, case insensitive, and are normalized to
uppercase in effective settings. Refresh must be a finite number
in 0.1–3600 seconds; booleans and numeric strings in YAML are rejected. Theme IDs
are 1–64 ASCII letters/digits/underscores/hyphens starting with a letter; available
themes must also be `k9s` or registered built-in Textual themes when opening the UI.
`config check` validates the schema, while the UI validates availability.
A null log path selects the platform
default, while an empty path is an error.

Relative `log_file` values from YAML resolve against that file's directory.
Relative environment/CLI paths resolve against the invocation's working directory,
including when their text happens to match the file's value.

Runtime choices never rewrite preferences. `--write` explicitly overrides a valid
file/environment read-only setting for this invocation. Read-only blocks commands
through a shared service decision, including the native shell service.
See the [launch contract](k9s-cli.md) for aliases, availability and command-specific
option handling. Context-specific preference precedence arrives with context support;
the current flat schema applies global settings only.

`shell` is a list of 1–32 nonempty strings, with an executable first and
literal arguments after it. Strings and shell expressions are rejected. For
example, `shell: ["/bin/bash", "-l"]` selects bash only in images that contain it.
The list is captured at launch; restart after changing it. Diagnostics omit this
argument list. See [native shells](container-shell.md).

## Schema, compatibility and writes

```yaml
schema_version: 1
theme: textual-dark
refresh_seconds: 2.0
read_only: false
log_level: WARNING
log_file: null
shell: ["sh"]
```

Unknown fields are retained in memory and preserved by the atomic save API; they
do not become effective settings or appear in diagnostics. Unknown schema versions
are rejected so older builds cannot overwrite a newer schema. Versionless/v0
preferences migrate `refresh` to `refresh_seconds` and `readonly` to `read_only`
in memory. Supplying both a legacy and current name fails. A later explicit save
writes version 1 while retaining unknown fields; current CLI commands do not
perform that migration write automatically.

YAML uses a [safe loader](https://pyyaml.org/wiki/PyYAMLDocumentation), unique string
keys and a 64 KiB input limit. Aliases, object-construction tags, multiple documents,
more than 20 nested collections and excessive parser events are rejected. Parser
errors identify the problem without echoing source values or source excerpts.

Writes use a mode-0600 temporary file in the destination directory, flush/fsync it,
and commit with an atomic link for creation or replace for an explicit save.
Creation cannot overwrite a concurrent writer. New application directories are
mode 0700; existing parent directories keep their permissions. Destination
symlinks are refused. A failure or interrupt before commit leaves the previous file
intact and removes the temporary file. A post-commit cleanup/directory-sync failure
returns exit 3 and explicitly says the preferences were saved but durability or
cleanup could not be confirmed; reread the file before retrying.

## Logging and errors

The ordinary CLI creates its local log and a small persistent `.lock` sibling,
both mode 0600. A nonblocking process lock permits only one writer per log path;
concurrent instances must use different `--log-file` values. Logs rotate at
approximately 1 MiB with three archives. Each formatted record is bounded to
8 KiB in UTF-8; total log storage is bounded by four times (1 MiB + 8 KiB), plus
the small lock file. Open files and locks are released on normal exit or failure.

Nonempty destinations and existing archives must have Kubetrol's diagnostic
header. Foreign files, symlinks and nonregular files are refused rather than
modified. This includes a mistakenly selected kubeconfig. An empty regular file
is accepted. These checks prevent mistaken destinations; they are not a sandbox
against another program modifying files with the same user's privileges.

Logs use an application-owned logger without console handlers or root/SDK
logging configuration changes. Messages redact common tokens, Bearer/Basic auth,
JWTs, passwords, secret/access/API keys, private-key blocks, certificate data and
HTTP URL passwords. Terminal control and directional-control characters are
escaped. Debug exceptions include type and frame locations, excluding exception
values, source text, chained exception values and locals. Raw kubeconfig, external
command output, credential-helper responses and arbitrary API bodies must never
be logged; pattern matching is defense in depth, not proof that arbitrary text
contains no secret. Debug output stays in the file.

| Exit | Meaning |
| --- | --- |
| `0` | Successful command, help, version or normal UI quit (including Ctrl+C) |
| `1` | Unexpected internal/local failure; concise message without raw exception |
| `2` | Invalid arguments, settings, schema, YAML or a noninteractive UI launch |
| `3` | Missing explicit file, local permissions/I/O, existing init destination or log ownership failure |
| `4` | Recognized option/command requires behavior not shipped in this development build |
| `130` | Interrupted non-UI operation |
| `143` | SIGTERM during a native shell, after cleanup and terminal restoration |

Argument parsing does not echo rejected arguments, which might contain tokens.
Settings errors name the setting without printing its value. Logging failures
cannot fall back to Python logging's raw-record stderr output.

The tests exercise temporary files, real wheel entry points, injected permission,
replace/fsync failures, interrupts, migration round trips, redaction, bounded
rotation and an actual second process competing for a log. They never use a real
cluster or the maintainer's kubeconfig.
