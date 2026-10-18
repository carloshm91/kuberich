# Local command plugins

Plugin configuration is available in the next-release source. The published
0.1.0 package does not load or execute plugins. This checkpoint validates and
captures definitions; the invocation UI and process execution are the next step.

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
| `NAME`, `NAMESPACE`, `RESOURCE`, `GROUP`, `VERSION`, `CONTAINER` | Captured selected resource/container; optional namespace/container can be empty |
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

The invocation owner will use the shared managed process runner: capture owns a
bounded one-shot command, background retains an owned cancellable session, and
foreground uses the deliberate terminal lifecycle. Timeout, output overflow,
exit status and cancellation must remain visible. A context switch or application
exit must drain resource-bound commands and private connection files.
These execution behaviors are not delivered by this configuration checkpoint.

Output must use the ordinary redaction and terminal-control escaping boundaries.
No remote OSC sequence can become a clipboard operation. Arbitrary plugin output
can contain information KubeRich cannot recognize as sensitive; review the local
program and avoid asking it to print secrets.

K9s configuration is not currently accepted as a drop-in format. A tested field,
variable and bundled-workflow compatibility guide follows the execution work.
