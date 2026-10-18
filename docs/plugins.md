# Local command plugins

Plugin configuration is available in the next-release source. The published
0.1.0 package does not load or execute plugins. The next-release source loads definitions, presents typed input/review forms
and runs explicitly selected commands through the owned process services.

Plugins are trusted local programs running with your user privileges. They can
read files, use inherited credentials, contact services and change a cluster.
KubeRich does not sandbox them or infer safety from an executable's name.
Only install definitions you have reviewed.

## Explicit configuration

Add the independently versioned `plugins` extension to your preferences:

```yaml
schema_version: 1
plugins:
  schema_version: 1
  commands:
    inspect-pod:
      description: Inspect the selected pod using a local tool
      command: kubectl
      args:
        - --kubeconfig=${KUBECONFIG}
        - --context=${CONTEXT}
        - --namespace=${NAMESPACE}
        - get
        - pod
        - ${NAME}
        - -o=json
      scopes: [v1/pods]
      shortcut: a
      mode: capture
      confirm: true
      dangerous: false
      trusted_read_only: true
      timeout: 30
      output_limit: 65536
```

Run `kuberich --config /absolute/path/config.yaml config check` to validate every
configured context without running any plugin, loading Kubernetes credentials,
or changing the file. `kuberich info` remains usable when a plugin path is broken.

The optional `locations` list names up to eight user-selected files/directories.
Relative paths resolve from the containing preference file, never the terminal's
current directory. A directory loads only its immediate `.yaml` and `.yml` files
in sorted order. There is no default directory search, recursion, installation
from resource annotations, or current-directory registration. Final-component
symbolic links, special files, missing configured paths and invalid YAML fail
closed. Parent-directory symlinks are subject to your operating system's ordinary
path resolution; keep configured directories under your control.

Each external file uses this wrapper:

```yaml
schema_version: 1
plugins:
  schema_version: 1
  commands:
    local-inspector:
      command: my-inspector
      args: ["${CONTEXT}"]
```

External files cannot introduce more locations or context layers. A layer loads
at most 16 files and 64 commands; each file is at most 64 KiB. Directories contain
at most 128 entries. YAML aliases and duplicate mapping keys are rejected. A
duplicate plugin name within a layer is an error. A context layer deliberately
replaces a same-named global definition in full:

```yaml
plugins:
  schema_version: 1
  locations: [plugins]
  contexts:
    demo-local:
      locations: [plugins-for-demo]
      commands:
        local-inspector:
          command: demo-inspector
          args: ["${CONTEXT}"]
```

Up to 128 context layers are supported. Context names are exact local names.
Changing the active context cannot change a previously captured invocation.
When `config migrate` moves legacy preferences, it validates the plugin schema
and makes file locations and inline working directories absolute against the
original file. Migration retains the same configured programs and directories,
keeps the source unchanged and refuses an invalid definition before writing.

## Definition fields

| Field | Contract |
| --- | --- |
| `command` | Required literal executable name/path; no variable or shell parsing |
| `description` | Literal help text; defaults to the plugin name |
| `args` | At most 255 separate nonempty arguments; each at most 8,192 characters |
| `environment` | At most 64 explicit string overrides on the captured inherited environment |
| `directory` | Absolute path or path relative to the definition file; defaults to its directory |
| `scopes` | `['*']` by default, or exact `v1/pods` / `apps/v1/deployments` identifiers |
| `shortcut` | Optional single ASCII letter/digit or `ctrl+`/`alt+` letter |
| `override` | False by default; must be true to replace an existing resource action/navigation key |
| `mode` | `capture` by default, `foreground` for terminal interaction, or `background` |
| `confirm` | True by default; explicit local trust decision before execution |
| `dangerous` | True by default; dangerous definitions always require review and are blocked read-only |
| `trusted_read_only` | False by default; only explicit true plus `dangerous: false` permits read-only use |
| `inputs` | At most 16 named, validated scalar input definitions |
| `timeout` | Positive finite seconds, at most 86,400; defaults to 300 |
| `output_limit` | Combined captured stdout/stderr bytes, 1,024–1,048,576; defaults to 65,536 |

Plugin names start with a lowercase ASCII letter followed by up to 63 lowercase
letters, digits, underscores or hyphens. Unknown fields fail validation rather
than being ignored. Applicable plugins must have different shortcuts even if
`override` is true. Quit, interruption, suspension and clipboard safety keys
cannot be replaced. Non-resource screens and text inputs retain their own keys.

The executable and working directory are captured separately from arguments.
Spaces, semicolons and dollar signs in selected names remain literal argument
content. An explicitly configured shell such as `sh -c` remains local shell code:
pass values as positional arguments rather than embedding them into its script.

## Captured variables

Use `$NAME` or `${NAME}` inside each argument/environment value. Expansion runs
once. Inserted text is never parsed again, and `$$` produces a literal dollar.
Missing, malformed, control-containing or oversized values fail before execution.
An optional empty input cannot occupy an entire argv entry, because process
arguments must remain nonempty; use a prefixed value or an environment variable.

| Variable | Source |
| --- | --- |
| `CONTEXT` | Captured session's exact context name |
| `CLUSTER`, `USER`, `FILTER` | Explicitly captured view values, when available |
| `KUBECONFIG` | Private prepared connection path supplied by the invocation owner |
| `RESOURCE`, `GROUP`, `VERSION`, `NAMESPACE` | Captured view scope; a selected row supplies its exact namespace |
| `NAME`, `CONTAINER` | Captured selected resource/container; container is empty outside a captured container |
| `COL-HEADER` | Explicitly captured uppercase column identifier, such as `${COL-NAME}` |
| `INPUT_NAME` | Validated named input; uppercase with hyphens changed to underscores |

`KUBECONFIG` and `KUBERICH_` environment overrides are reserved for the captured
session. A context/UID change invalidates resource-bound work. Scope and local
guards cannot make an external tool's server-side operations atomic.

## Typed inputs and cancellation

```yaml
inputs:
  - name: count
    label: Number of lines
    type: number
    default: 100
  - name: previous
    type: bool
    default: false
  - name: format
    type: dropdown
    options: [json, yaml]
    default: json
  - name: note
    type: string
    required: false
```

Inputs are required by default. Types are `string`, finite `number`, `bool`
(`true`/`false`) and `dropdown` with unique configured choices. Defaults undergo
the same validation as submitted values. Unknown inputs and colliding normalized
names are rejected. Cancellation produces no executable request. Inputs and
expanded command values must not enter diagnostics or exception representations.

## Execution modes and output

Use `:plugins` to list applicable commands, or `:plugin NAME` to open a specific
command. Tab completes configured names after `plugin `. Configured shortcuts
work while a root resource table owns focus; text inputs and embedded pod shells
retain their keys. A plugin override replaces that resource shortcut, and root
help lists the effective plugin keys. The form defaults to Cancel. Review
validates typed values; Run is a separate explicit action. Changing a value
invalidates the previous review, and a review can run only once.

A connected context is required. An empty resource view can run commands that
need only context/scope values; `NAME`, container and column values require an
actual selected row. A selected row is captured before asynchronous loading and
checked again by GET and UID before starting. Guards cannot make a later external
program's server operations atomic.

The local contexts list has no Kubernetes resource scope or plugin hotkeys.
Explicit `:plugins` / `:plugin NAME` there can review global commands against the
currently connected context; highlighting another context does not connect it or
supply a resource `NAME`. Resource-specific commands wait until their matching
API view is ready. Shortcut validation uses the namespace table's own navigation
profile for namespace-scoped/global commands, including custom namespace keys.

- `capture`: waits for the one-shot command and shows status, exit code and bounded
  output. Cancel stops and drains the process group before returning.
- `background`: stays owned after Back closes the form. Use `:pluginjobs`, Enter
  for its completed output, or Stop selected. Output is collected until completion
  rather than streamed; there are at most four active jobs and 32 retained jobs.
- `foreground`: deliberately suspends Textual and gives the native terminal to
  the local executable. Exit/interruption restores the interface. This does not
  change the embedded pod/container shell. It requires a real terminal and its
  direct output is outside captured-output redaction and byte limits.

Captured stdout and stderr share the configured cumulative byte limit; overflow
terminates the owned group and reports Output Limit. Timeout, nonzero exit,
signal, cancellation and start refusal have distinct visible states. Background
waiter cancellation does not detach a job. Scope/UID invalidation, context/retry
replacement and application exit cancel and drain owned work. Private credential
files stay available until processes stop and are then removed.

Each command gets a private, single-context mode-0600 kubeconfig under the owned
mode-0700 session directory. KubeRich sets `KUBECONFIG`, `KUBERICH_CONTEXT` and the
captured `KUBERICH_NAMESPACE`; it does not reload the ambient current context.
Explicit plugin cwd/environment do not alter the original authentication helper's
cwd, frozen environment or relative files. A private credential launcher retains
those separately and forwards client-go's fresh `KUBERNETES_EXEC_INFO`. Native
archives dispatch this launcher internally without an external Python install.

Read-only mode refuses an unclassified or dangerous command before helper lookup
or input preparation. Running one requires both `trusted_read_only: true` and
`dangerous: false`; that is your explicit trust decision, not inferred safety.
Both GUI entry routes still use Review and Run. At the service boundary,
`confirm: true` or `dangerous: true` always requires explicit confirmation.
`--command 'plugin NAME'` is refused before connection/authentication; execution
requires interactive review.

Captured output uses credential-pattern redaction, known captured token/input
value masking and terminal-control escaping. Display is bounded to 16,384
characters with an explicit truncation marker; retained sanitized text is at most
65,536 characters. Raw output is never logged or included in job representations.
No remote OSC sequence can become a clipboard operation. Arbitrary plugin output
can contain information KubeRich cannot recognize as sensitive; review the local
program and avoid asking it to print secrets.

K9s configuration is not currently accepted as a drop-in format. A tested field,
variable and bundled-workflow compatibility guide follows the execution work.
