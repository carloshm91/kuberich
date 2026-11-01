# Configure your workspace

Change local preferences without changing Kubernetes configuration. Run
`kuberich info` to find the preference file and diagnostic log used on your machine.
`--config` selects preferences; `--kubeconfig` selects Kubernetes connections.

## Create and check preferences

```sh
kuberich config init
kuberich config check
kuberich info
```

Init creates defaults and refuses an existing file. Check validates without
writing files, connecting, or running credential helpers. Global flags go before
a local command: `kuberich --config /absolute/path/preferences.yaml config check`.

The preference path comes from `--config`, `KUBERICH_CONFIG`, `KUBETROL_CONFIG`,
then the platform default with the legacy fallback described below. Linux uses
`~/.config/kuberich/config.yaml` unless XDG_CONFIG_HOME is set;
macOS uses `~/Library/Application Support/kuberich/config.yaml`.
An absent default file uses defaults; an explicitly selected missing file fails.

```yaml
schema_version: 1
theme: k9s
refresh_seconds: 2.0
read_only: false
log_level: WARNING
log_file: null
shell: ["sh"]
```

The [generated configuration reference](config-reference.md) lists actual fields,
defaults, and extension declarations. Preference files accept safe YAML up to
64 KiB. Unknown root fields are preserved and reported; unknown schema versions
are refused. Loading and checking do not rewrite files.

## Understand precedence and reload

Runtime CLI overrides win over `KUBERICH_*` environment variables, file settings,
and defaults. Each layer must be valid even if another overrides it. Relative
YAML log paths resolve against the preference directory; environment and CLI
paths resolve against the launch directory.

`context_settings` can add read-only mode or a refresh interval for exact context
names. CLI/environment refresh overrides win; context values then precede global
file values. A read-only context cannot be made writable by `--write`.

KubeRich checks the file every two seconds. Valid changes update themes, aliases,
jumps, context settings, plugins, shell, and refresh without losing your view.
Keys, mouse mode, and log settings need a restart. Turning read-only off in a file
does not make the running session writable. Invalid or deleted files leave the
last valid preferences active and show a message. Use `config check` for details.

## Choose and save a theme

Open `:themes` or run `kuberich --command themes`. The standalone picker needs no
cluster. Moving through themes previews them. **Global** saves the global theme
and update-check choice; **Context** saves only the named context's theme.
**Back** or Escape cancels a preview. Preview alone writes nothing.

An environment theme wins over a context theme, then global `theme`, then `k9s`.
The picker reports the effective name when another layer overrides your save.
`--invert` reverses this session's resolved colors without saving. `kuberich-mono`
provides black/white colors with visible state words.

```yaml
schema_version: 1
appearance:
  schema_version: 1
  check_updates: false
  themes:
    ocean:
      primary: '#5fd7ff'
      foreground: '#ffffff'
      background: '#000000'
      dark: true
  contexts:
    demo-lab: ocean
```

Use fictional names here as a template. Custom themes require primary,
foreground, and background; optional colors and limits appear in the reference.
Colors are quoted six-digit hex values. Background, surface, and panel also
accept `'default'` for the terminal's background, whose contrast cannot be checked.
Other foreground contrast must reach 4.5:1; primary/accent/status colors need 3:1.
Palettes contain no executable CSS or Python. `appearance.full_gvr_titles: true`
adds API versions to standard resource titles; custom resources always show them.

Saves preserve unrelated settings and refuse a competing file change. Local
preference saves work in cluster read-only mode. They never persist runtime
connection, environment, or read-only overrides.

## Set keys, aliases, and resource layouts

```yaml
schema_version: 1
navigation:
  schema_version: 1
  mouse: false
  keys:
    resources:
      first: H
      last: K
  aliases:
    work: pods
    lab: ctx demo-lab
```

`table` supplies shared table defaults; specific table profiles override them.
Logs and text use independent profiles. See the generated key reference for
profiles and actions. Fixed navigation, safety, and per-view action keys cannot
be replaced. Keys are one ASCII letter/digit or a permitted Ctrl/Alt combination;
counts and chords are unsupported. Duplicate effective keys are refused.

Aliases expand literal command text, never a shell expression. Up to 64 aliases
and eight expansion steps are allowed. Built-in names, cycles, ambiguous preset
arguments, and discovered-resource collisions are refused. Aliases work with
completion and supported startup views, retaining the target's checks.

`:views` edits columns as `key[:width][:alignment]`, their order, and typed sorting.
For example, `name:24:left ready:8:center age:8`. Width is auto or 1–256;
alignment is auto/left/center/right. Name stays visible, as does namespace in an
all-namespace list. Apply changes the session; Global or Context saves explicitly.
Context preferences win over global layouts. A changed server-printer schema
uses working defaults without reinterpreting old positions under new labels.
Hidden columns can still participate in sorting/filtering.

## Define a resource jump

A jump opens another view with a local filter from the selected row:

```yaml
schema_version: 1
jumps:
  schema_version: 1
  definitions:
    node-pods:
      source: v1/nodes
      target: v1/pods
      namespace: "*"
      fields: "spec.nodeName={{ metadata.name }}"
```

Use `:jump` or `:jump node-pods`. Templates read fields or a label map, without
functions, conditions, or executable code. Missing or unsafe selector values
produce an error. `labels` and `fields` are mutually exclusive. Run `config check`
to validate definitions offline.

## Optional update notices

Checks are off by default. Enable `appearance.check_updates` or the picker checkbox
and save Global. KubeRich reads GitHub's public stable-release endpoint, caches
results for up to 24 hours, and shows a validated newer version in the header.
`:about` shows installed version, license, and check state. Local info/help/version
and config check stay offline. Nothing is downloaded or installed automatically.

## Legacy files and diagnostic logs

The `kubetrol` console command is a deprecated alias in the 0.3 source. It prints
a fixed warning to stderr, then runs the same CLI; help/version stdout and exit
codes stay unchanged. Use `kuberich` or `python -m kuberich`. The previous console
alias is scheduled for removal in 0.4.0; it is not a second Python package.

`KUBETROL_*` preference variables remain fallbacks after corresponding
`KUBERICH_*` variables. If the new default preference file is absent, the old
Kubetrol file is read in place. An existing invalid file, directory, or symlink
at the new path does not silently fall back. `info` reports the selected file,
migration status, and destination without writing anything.

Run `kuberich config migrate` explicitly with default paths and no runtime
overrides to create a mode-0600 KubeRich file atomically. It keeps the old file,
unknown fields, read-only policy, and effective settings. File-relative log paths
become absolute so their destination stays the same. Existing destinations are
never replaced, including a competing creation. A repeated migration validates
the current file without rewriting it; the success notice appears only when a
file is created. Explicit preference paths cannot be relocated implicitly.
Migration does not move kubeconfig, credentials, logs, or tool installations.
Existing legacy log/lock headers and archives remain accepted for explicit log
paths; default new logs use KubeRich's directory.

Normal launches write private, redacted diagnostic logs, about 1 MiB each with
three archives. One writer can use a log path at a time; give simultaneous
instances different `--log-file` values. Foreign nonempty files and symlinks are
refused as log destinations. Diagnostics omit raw kubeconfig, helper output,
resource bodies, and editor drafts. Redaction cannot recognize every sensitive
phrase; inspect any report before sharing it.
