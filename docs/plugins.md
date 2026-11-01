# Run a local plugin

Configure a trusted local program, review its inputs, and run it against your
selected context. Plugins run with your user privileges. They can read files,
use credentials, contact services, and change resources; KubeRich does not sandbox
them or infer safety from an executable's name.

## Add a definition

Place a `plugins` extension in the preference file shown by `kuberich info`:

```yaml
schema_version: 1
plugins:
  schema_version: 1
  commands:
    inspect-pod:
      description: Read the selected pod using kubectl
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
      dangerous: false
      trusted_read_only: true
```

Run `kuberich config check` before using it. This validates definitions without
executing them or loading Kubernetes credentials. `command` is a literal executable
name/path. Each `args` entry is a separate argument; selected values are not
parsed as shell code. A deliberately configured `sh -c` remains your shell code:
pass inserted values positionally rather than embedding them in its script.

Definitions may also come from up to eight explicit files/directories in
`locations`. Relative paths resolve against their definition file. A directory
loads immediate `.yaml`/`.yml` files only. There is no automatic current-directory
search, recursive discovery, download, or annotation-based installation.
A context entry replaces a same-named global definition in full.

Each layer permits at most 16 files and 64 commands; a file is at most 64 KiB.
Duplicate names, unsafe YAML, missing paths, final-component symlinks, and special
files are refused. See the generated [configuration reference](config-reference.md)
for declared definition fields and defaults.

## Insert selected values

Use `$NAME` or `${NAME}` in an argument or explicit environment value. Expansion
runs once; `$$` produces a literal dollar. Missing or invalid values stop execution.

| Variable | Meaning |
| --- | --- |
| `CONTEXT`, `CLUSTER`, `USER` | Selected connection names, when available |
| `KUBECONFIG` | Private connection file prepared for this invocation |
| `RESOURCE`, `GROUP`, `VERSION`, `NAMESPACE` | Current API and scope |
| `NAME`, `CONTAINER` | Selected resource/container, when available |
| `FILTER` | Current filter, when available |
| `COL-HEADER` | Explicit selected column, such as `${COL-NAME}` |
| `INPUT_NAME` | Validated input name, uppercased with hyphens as underscores |

Environment overrides cannot replace reserved KUBECONFIG or KUBERICH_ values.
`NAME`, container, and column values need an actual selected row. Context-only
commands can run in an empty resource view. Highlighting a local context does
not connect it or provide a Kubernetes resource name.

## Ask for input

Add up to 16 `inputs` with types `string`, finite `number`, `bool`, or `dropdown`:

```yaml
inputs:
  - name: count
    type: number
    default: 100
  - name: format
    type: dropdown
    options: [json, yaml]
    default: json
```

Inputs are required unless `required: false`. Defaults use the same validation
as submitted values. Optional empty input cannot be an entire empty argv entry;
use a prefixed argument or environment value instead. Cancelling runs nothing.

## Review and run

Open `:plugins`, or `:plugin inspect-pod`. Tab completes configured plugin names.
Shortcuts apply in root resource tables; inputs and embedded shells keep their
own keys. A shortcut replacing a resource action needs `override: true`; safety
keys cannot be replaced. Help reports effective plugin shortcuts.

Check target identity and typed values, choose Review, then Run separately.
Cancel has default focus. Changing input invalidates Review; it can run once.
Plugins need an active connection and cannot execute as startup commands.
KubeRich rechecks a selected resource's UID before launch, but cannot make an
external tool's later server requests atomic.

## Choose how output appears

- `capture` waits for one command and shows its result and limited output.
- `background` continues after Back closes the form. `:pluginjobs` lists status;
  Enter opens output and Stop selected stops the job. Output is collected until
  completion rather than streamed. There are at most four active and 32 kept jobs.
- `foreground` temporarily gives the native terminal to the local executable,
  then restores the workspace. Its direct output is outside output redaction
  and byte limits; it does not change the embedded pod-shell behavior.

Default timeout is 300 seconds, up to 86,400. Combined stdout/stderr is limited
to 65,536 bytes by default and configurable from 1,024 to 1,048,576. Overflow stops
the process and reports Output Limit. Timeout, cancellation, nonzero exit, signal,
and start refusal have distinct results. Context replacement, target invalidation,
and exit stop the related local processes before private connection cleanup.

## Trust and read-only behavior

Definitions default to `dangerous: true`, `confirm: true`, and
`trusted_read_only: false`. Read-only mode permits a plugin only with both
`dangerous: false` and `trusted_read_only: true`. This is your trust decision,
not a sandbox or proof of a tool's behavior. Interactive Review and Run remain
separate even for a trusted read-only definition.

Collected output escapes terminal controls and masks recognized credentials and
known private input/token values. Display stops at 16,384 characters with a
notice; kept sanitized output is limited to 65,536 characters. Arbitrary program
output can contain secrets the application cannot recognize. Do not ask plugins
to print credentials.

K9s plugin YAML is not a drop-in format. Translate fields and variables explicitly
and check the resulting definition; unsupported fields fail validation rather
than silently executing with different behavior. External tool features remain
features of those tools, not native KubeRich operations.
