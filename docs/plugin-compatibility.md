# Plugin compatibility and original examples

This guide describes the next-release source. Published **0.1.0 does not load or
execute plugins**. KubeRich has an independent, versioned schema: a K9s file is
not a drop-in configuration file, and there is no automatic importer.

The comparison fixes K9s **v0.51.0**, commit
`558caafe7ba067467de46b320cc22ef11fef9c34`. Its pinned inventory contains **50
files: 48 YAML manifests with 108 commands and two executable shell helpers**.
This is a complete classification of that inventory, not a claim that all its
programs work in KubeRich or that an unverifiable paid catalogue is covered.

Read [configuration, trust and process ownership](plugins.md) first. Plugins run
as your user without a sandbox. The examples below are original definitions;
upstream shell programs are neither installed nor executed by our tests.

## Fields: keep, translate or reject

The authoritative upstream field definitions and defaults are in the
[pinned plugin model](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/internal/config/plugin.go).
Unknown KubeRich fields fail validation; there is no silent compatibility mode.

| K9s field or structure | KubeRich contract |
| --- | --- |
| `plugins: NAME: ...` | Translate to root `schema_version: 1`, then `plugins: {schema_version: 1, commands: ...}`. Only explicitly configured locations load. |
| `command` | Same literal executable concept. No variable expansion in the executable, implicit shell, installation or executable discovery during `config check`. |
| `description` | Supported as literal text. Terminal controls and markup are not interpreted. |
| `args` | Supported as separate **strings**, with bounded one-pass interpolation. Quote numeric YAML entries such as `"50"`. Shell statements remain shell code if you explicitly choose a shell. |
| `scopes` | Translate aliases such as `po`/`pods` to an exact served identifier such as `v1/pods`; `all` becomes `'*'`. Group/version is explicit, including CRD plurals with hyphens. Virtual `containers`, `helm` and `history` views are not root API scopes. |
| `shortCut` | Rename to `shortcut`. Translate `Shift-H` to `H` or `Ctrl-A` to `ctrl+a` only where the terminal and safety/key profile permit it. Function keys, chords and reserved safety keys are not plugin shortcuts. |
| `override` | Supported only as explicit key replacement. Scope conflicts, duplicate effective shortcuts and reserved safety keys still fail. |
| `confirm` | Recognized, with different defaults/interaction: KubeRich defaults true; its form always requires an explicit Run after review. K9s defaults to confirmation when inputs exist, otherwise false. |
| `dangerous` | Recognized, but KubeRich defaults true. Dangerous commands always require confirmation and cannot run read-only. No executable is inferred safe by name. |
| `background` | Replace with `mode: background` for an owned job. For interactive terminal use choose `mode: foreground`; the default `capture` is a separate bounded one-shot mode. This is a deliberate choice, not a boolean rename preserving all behavior. |
| `overwriteOutput` | Unsupported; reject it. KubeRich retains bounded per-job output and status rather than replacing a shared upstream output area. |
| `pipes` | Unsupported; reject it. Write and review a separate local program/script, with literal positional arguments, if a pipeline is needed. |
| `inputs` | The four type names (`string`, `number`, `bool`, `dropdown`) are recognized. Names must use the KubeRich lowercase identifier grammar; defaults/options are validated. Set `required` explicitly: KubeRich defaults true; the upstream model's omitted bool defaults false. Typed boolean defaults or `"true"`/`"false"` are accepted. |
| `directory`, `environment`, `timeout`, `output_limit`, `trusted_read_only` | KubeRich-specific explicit controls. Paths resolve from the definition file; read-only use needs `dangerous: false` **and** `trusted_read_only: true`. Do not infer that classification from an upstream flag. |

Definitions remain local trusted code even when `trusted_read_only` is true.
That setting permits invocation in the UI; it cannot stop a program writing files,
ignoring a kubeconfig or contacting another service.

## Variables and shell syntax

The comparison uses the pinned
[common environment](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/internal/view/helpers.go),
[resource table environment](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/internal/view/table.go),
[container environment](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/internal/view/container.go)
and [substitution implementation](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/internal/view/env.go).

| Upstream value | KubeRich mapping and limits |
| --- | --- |
| `$CONTEXT`, `$CLUSTER`, `$USER` | Same uppercase names when captured. These are connection aliases, not a promise about an external service's authenticated identity. |
| `$KUBECONFIG` | Same spelling, different ownership: the invocation receives a private, single-context prepared file, not the caller's ambient source path. It exists only while owned work needs it. |
| `$NAMESPACE`, `$NAME` | Selected **root API resource** namespace/name. Cluster-scoped resources have an empty namespace. Empty argv entries are rejected; choose a separate cluster-scoped recipe instead of an empty namespace flag. |
| `$RESOURCE_GROUP`, `$RESOURCE_VERSION`, `$RESOURCE_NAME` | Translate to `${GROUP}`, `${VERSION}`, `${RESOURCE}`. These are the actual captured GVR components, not aliases or an assumed preferred version. |
| `$FILTER` | Same spelling, different fallback: KubeRich captures the root filter text and leaves it empty when no filter exists. K9s falls back to a selected path/name. Use a required input when an external tool needs a selector. |
| `$COL-NAME`, other `$COL-...` | Only available captured **visible** columns, normalized to uppercase portable identifiers. Upstream hidden headers and punctuation do not imply the same column exists. Missing columns fail closed. |
| `$INPUT_NAME` | Validated input values, uppercase with hyphens changed to underscores. An inserted value is never parsed as another template. |
| `$POD`, container `$NAME` | No drop-in mapping. In K9s container views, NAME is the container and POD is its parent. Root plugin invocation in KubeRich uses the Pod as NAME; use an explicit container input, as below. There are no plugin hotkeys in the container picker. |
| `$GROUPS` | Unsupported; it is not a captured KubeRich plugin variable. Supply a reviewed explicit input/environment value if the external program needs groups. |
| `$!FLAG`, `${!FLAG}` | Upstream **boolean inversion**, not escaping. Unsupported; use a typed boolean for the desired state. That is set-state behavior, not a race-free toggle. |
| Lowercase variables, unknown names, `${NAME:-fallback}`, `${GROUP:+...}`, arithmetic and command substitution | Unsupported in KubeRich templates; fail before execution. Separate shell code into a reviewed file and pass captured values as positional arguments. |
| Literal dollar | Use `$$`. For example, `$$HOME` passes literal `$HOME`; it does not read the ambient environment. Escaped `$$!NAME` is literal text, not inversion. |

Substitution is not shell quoting and does not validate a destination language
such as JSON, LogQL or a CLI's regex dialect. A safe argument vector can still
contain an unsafe query. Prefer structured tools or validated dropdown values
when inserting data into those formats. The PVC translation fixture uses an
explicit quantity allowlist rather than unrestricted JSON interpolation.

## Three original workflows

Each example is a complete external-file wrapper and declares `kubectl` as its
only **local** executable. Install a compatible kubectl separately. Review and
copy the files into a directory you control, then add that directory explicitly
to the existing preference file. Relative locations resolve from that file:

```yaml
schema_version: 1
plugins:
  schema_version: 1
  locations: [plugins]
```

This example expects a sibling `plugins` directory; it does not search your
checkout or current directory. Keep existing preferences and extensions when
merging this configuration. Validate without authenticating or starting a tool:

```sh
kuberich --config /absolute/path/config.yaml config check
```

Connect to the intended context/namespace, select a Pod, and invoke a name with
`:plugin NAME`. The form defaults to Cancel; Review validates values, then Run
starts the command. Cancel starts no program and discards any prepared review. See the complete
[example files](https://github.com/carloshm91/kuberich/tree/main/examples/plugins).

| Example | Invocation and behavior | Prerequisites and limits |
| --- | --- | --- |
| [Inspect Pod](https://github.com/carloshm91/kuberich/blob/main/examples/plugins/inspect-pod.yaml) | `:plugin inspect-pod` captures `kubectl get pod NAME --output=json` with explicit kubeconfig/context/namespace. | Pod GET permission; 30-second timeout, 64-KiB combined output. Explicit non-dangerous/read-only classification. Arbitrary values may exceed recognizable credential redaction; review output handling. |
| [Interactive Pod shell](https://github.com/carloshm91/kuberich/blob/main/examples/plugins/pod-shell.yaml) | `:plugin pod-shell` asks for the exact container and runs literal `kubectl exec --stdin --tty --container=... NAME -- sh`. | Write mode, pods/exec permission, a container containing `sh`, and a real terminal. This **local foreground plugin** uses native handoff and restores the UI; ordinary built-in Pod shells remain embedded. Direct foreground output cannot receive capture redaction/byte limits. Timeout is one hour. |
| [Collect Pod events](https://github.com/carloshm91/kuberich/blob/main/examples/plugins/collect-pod-events.yaml) | `:plugin collect-pod-events` starts an owned background `kubectl get events --output=json`, filtered to kind Pod and the selected name in its namespace. | Event list permission. Name/kind filtering does not identify a UID atomically; the plugin's captured Pod UID guard invalidates replaced targets. Output appears at completion, not as a live log stream; Stop may discard in-flight capture. Timeout is five minutes; 64-KiB output stops the group on overflow. |

Use `:pluginjobs` to inspect or Stop background work. Closing its form keeps an
owned background job alive; scope/UID invalidation, context replacement or exit
stops and drains it. Private connection files are removed after processes stop.
Missing programs, bad permissions/cwd, denied/stale targets, timeouts, nonzero
exits, signals and output overflow produce visible failure states. No failure
triggers an automatic retry of an external side effect. `config check` validates
the manifest but deliberately does not prove that a program is installed, that
its flags are compatible or that Kubernetes permissions allow execution.

## What the translation tests establish

There are **18 original argv adaptation fixtures**, including Argo workflow
commands, selected Application patches, one duplication scope, desired-state
CronJob/Spark suspension, KubeVirt migration arguments, Pod log follow, six Loki
root-row queries, Stern with an explicit selector, bounded PVC quantities and a
restricted Deployment finalizer patch. Their
[fixtures](https://github.com/carloshm91/kuberich/blob/main/tests/fixtures/plugins/translations.json)
record the changed semantics beside each definition and exact expected argv.

These fixtures prove schema/input/scope/literal expansion and conservative trust
classification against synthetic resources. They do **not** run Argo, Loki,
Stern, KubeVirt, Spark, storage controllers or their services. Served CRDs and
external CLI versions must match your installation. Shell/PowerShell recipes,
virtual views and legacy helpers are explicitly classified below, not presented
as tested translations. No automated converter attempts to repair their code.

The three original examples additionally execute harmless owned kubectl stand-ins
with private synthetic connection files. Tests cover capture, background Stop,
read-only refusal, cancellation and actual interactive terminal input/restoration.
Downloaded upstream code and the maintainer's clusters are never test inputs.

## Complete pinned workflow census

Each source link fixes the reviewed commit. The machine-readable
[census](https://github.com/carloshm91/kuberich/blob/main/docs/plugin-compatibility.json)
records all 108 command names, field/variable spellings, classifications,
translation references, original Git blob IDs, byte lengths and SHA-256 digests.
Those digests identify the reviewed source bytes; they are not a claim about a
later upstream revision. The two extensionless files are executable helpers,
not malformed YAML manifests.

**argv** means only the named synthetic argument contract is tested;
**rewrite** needs a separately reviewed program/definition; **view** depends on
an unavailable virtual view; **legacy** is deliberately not translated.
Dependencies below include the primary programs and important platform/service
requirements. Shell recipes also use ordinary shell utilities. Alternatives are
no-fee local/native inspection paths or separately installed CLIs, with the
stated functional limits. External software retains its own license; hosting,
cloud/model services, credentials and privileged operations may have costs or
requirements. None is automatically installed or required for KubeRich itself.

| Pinned source and commands | Classification | External dependencies | Free alternative and review limits |
| --- | --- | --- | --- |
| [ai-incident-investigation.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/ai-incident-investigation.yaml) · `holmesgpt`, `custom-holmesgpt` | 2 rewrite | bash, holmes CLI, configured model/provider, editor for custom questions | Read details/events/logs and investigate manually with kubectl. External model requests may disclose cluster data and may incur provider charges; review scripts and provider terms. |
| [argo-rollouts-powershell.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/argo-rollouts-powershell.yaml) · `argo-rollouts-get`, `argo-rollouts-watch`, `argo-rollouts-promote`, `argo-rollouts-restart` | 4 rewrite | PowerShell, kubectl, Argo Rollouts kubectl extension/controller | Inspect rollout CRDs with the generic browser or kubectl. PowerShell statements and ReadKey are not literal argv; use reviewed platform-specific scripts. |
| [argo-rollouts.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/argo-rollouts.yaml) · `argo-rollouts-get`, `argo-rollouts-watch`, `argo-rollouts-promote`, `argo-rollouts-restart` | 4 rewrite | bash, kubectl, Argo Rollouts extension/controller, less | Inspect rollout CRDs; use the separately installed Rollouts CLI for its actions. Pipelines and shell interpolation need a rewrite; select the actual served Rollout GVR. |
| [argo-workflows.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/argo-workflows.yaml) · `view-workflow`, `watch-workflow`, `terminate-workflow`, `submit-from` | 2 rewrite, 2 argv | sh, argo CLI/controller, watch for watch-workflow | Browse workflow CRDs and inspect their YAML/events. CLI authentication/options and installed CRD versions must be verified; shell watch recipes need separate scripts. |
| [argocd.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/argocd.yaml) · `argocd`, `refresh-apps`, `disable-auto-sync`, `enable-auto-sync` | 2 rewrite, 2 argv | argocd CLI/server/login, kubectl, bash | Browse Application CRDs and review YAML changes with kubectl. An Argo CD server login is a separate identity; KUBECONFIG does not constrain a server-side argocd app sync. |
| [blame.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/blame.yaml) · `blame` | 1 rewrite | sh, kubectl-blame, less | Inspect managedFields in YAML; that is not a full blame history. External ownership rendering and paging require the external tool. |
| [carvel.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/carvel.yaml) · `kapp-inspect`, `kctrl-app-status`, `kctrl-app-pause`, `kctrl-app-kick` | 4 rewrite | bash, kapp, kctrl, Carvel controllers, less | Inspect Carvel CRDs/YAML and use the separately installed Carvel tools. Shell export/pipes need reviewed scripts; pause/kick change controller state. |
| [cert-manager.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/cert-manager.yaml) · `cert-status`, `cert-renew`, `secret-inspect` | 3 rewrite | bash, cmctl, cert-manager, less | Inspect Certificate CRDs/events; use cmctl explicitly for renew/inspection. Secret inspection discloses certificate content; renew changes state. |
| [crd-wizard.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/crd-wizard.yaml) · `crd-wizard` | 1 rewrite | bash, crd-wizard TUI | Browse discovered CRDs and inspect/edit their YAML. Requires an available KIND column and an external TUI; literal argv must replace the shell command. |
| [crossplane.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/crossplane.yaml) · `crossplane-trace`, `crossplane-watch` | 2 rewrite | sh, crossplane CLI/controllers, less, viddy for watch | Browse Crossplane CRDs and inspect their status/YAML. Conditional namespace handling, external watch and group-qualified kinds require reviewed scripts. |
| [current-ctx-terminal.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/current-ctx-terminal.yaml) · `open-terminal` | 1 rewrite | /usr/bin/sh, bash, kubectl | Use explicit kubectl --kubeconfig/--context flags for each command. Upstream use-context writes configuration; never run it against the caller configuration. A private config is not a shell sandbox. |
| [debug-container.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/debug-container.yaml) · `debug` | 1 view | bash, kubectl debug, permitted debug image/profile | Use reviewed kubectl debug; built-in shells connect to existing containers only. Virtual containers scope and POD/NAME meanings differ; privileged debug creation is not a native capability. |
| [dive.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/dive.yaml) · `dive` | 1 view | dive, supported local/container image backend | Inspect declared image references; use dive separately for image layers. Virtual container selection and IMAGE column are unavailable to root plugin hotkeys; image-layer analysis remains external. |
| [dup.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/dup.yaml) · `dup`, `dup_edit`, `dup_debug_pods`, `dup_debug_deploy`, `dup_debug_sts`, `dup_debug_cronjob`, `dup_debug_jobs` | 7 rewrite | bash, kubectl, kubectl-dup extension | Review an exported manifest and apply a deliberately edited copy with kubectl. Duplication/debug actions create resources; never infer read-only from the missing dangerous flag. |
| [duplik8s.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/duplik8s.yaml) · `duplicate` | 1 argv | kubectl, duplik8s kubectl-duplicate extension | Review/export a manifest and create an explicitly named copy with kubectl. Short resource aliases must become exact GVR scopes; the external extension still needs installation. |
| [eks-node-viewer.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/eks-node-viewer.yaml) · `eks-node-viewer` | 1 rewrite | bash, kubectl, jq, eks-node-viewer, AWS configuration/credentials | Inspect nodes and declared resources with kubectl; AWS billing views remain external. Do not scrape private ExecCredential launchers for AWS_PROFILE/region; configure the external AWS tool explicitly. AWS services may charge. |
| [external-secrets.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/external-secrets.yaml) · `refresh-external-secrets`, `refresh-push-secrets` | 2 rewrite | bash, kubectl, date, External Secrets controllers | Inspect ExternalSecret/PushSecret CRDs and explicitly annotate with kubectl. Timestamp command substitution and controller-specific API versions need review; reconciliation changes state. |
| [flux.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/flux.yaml) · `toggle-helmrelease`, `toggle-kustomization`, `reconcile-git`, `reconcile-hr`, `reconcile-helm-repo`, `reconcile-oci-repo`, `reconcile-ks`, `reconcile-ir`, `reconcile-iua`, `toggle-rset`, `toggle-inputprovider`, `reconcile-rset`, `reconcile-inputprovider`, `reconcile-fluxinstance`, `trace`, `get-suspended-helmreleases`, `get-suspended-kustomizations` | 17 rewrite | bash/sh, kubectl, flux, flux-operator, controllers, less, jq/tail/awk | Browse Flux CRDs/YAML and run the installed Flux CLI explicitly. Toggle/trace scripts perform lookups, conditionals and writes; select the actual served API groups/versions. |
| [get-all-namespace-resources.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/get-all-namespace-resources.yaml) · `get-all-resources-by-selected-namespace`, `get-all-resources-in-current-namespace` | 2 rewrite | sh, kubectl, less | Browse a selected resource family or enumerate/list with kubectl api-resources. Loops, suppressed failures and many API calls are not a single native all-resource view; retain explicit scope and errors. |
| [get-all.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/get-all.yaml) · `get-all-namespace`, `get-all-other` | 2 rewrite | sh, kubectl-get-all extension, less | Use kubectl api-resources and explicit resource-family listings. External enumeration and paging require the extension; namespace NAME differs from a resource namespace. |
| [helm-default-values.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/helm-default-values.yaml) · `helm-default-values` | 1 view | sh, helm, kubectl, grep/cut/tr, yq, base64, gunzip, jq, less | Use helm show values or helm get values with explicit release/context. Virtual Helm rows and release-secret decoding are unsupported; yq dialect and secret handling require review. |
| [helm-diff.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/helm-diff.yaml) · `helm-diff-previous`, `helm-diff-current` | 2 view | bash, helm, helm-diff extension, grep/cut/tr, less | Use helm history/get values; diff retained manifests with ordinary diff. Virtual Helm/history rows, revision arithmetic and release-name parsing are not available. |
| [helm-purge.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/helm-purge.yaml) · `helm-purge` | 1 legacy | kubectl-purge helper, Helm 2, Tiller, BSD xargs -J | Plan a reviewed migration to Helm 3 and use its supported uninstall command. Legacy Helm 2/Tiller purge is not translated or certified; do not execute the unquoted helper. |
| [helm-values.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/helm-values.yaml) · `helm-values` | 1 view | sh, helm, less | Use helm get values with explicit release, namespace and kube context. Virtual Helm rows are unsupported; provide an explicit release input to a separately reviewed definition. |
| [job-suspend.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/job-suspend.yaml) · `toggleCronjob` | 1 argv | kubectl, batch/v1 CronJob API | Use the built-in reviewed CronJob suspend/resume operation. Replace boolean inversion with an explicit desired boolean; this is set-state, not a toggle. |
| [k3d-root-shell.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/k3d-root-shell.yaml) · `k3d-root-shell` | 1 view | bash, kubectl, jq, Docker, k3d node containers, less | Use an existing pod shell; review node/container-runtime administration separately. Virtual container scope, runtime IDs and Docker root access are external and highly privileged. |
| [keda-toggle.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/keda-toggle.yaml) · `toggle-keda` | 1 rewrite | bash, kubectl, grep, KEDA controller | Inspect KEDA CRDs; review an explicit annotation change with kubectl. overwriteOutput is unsupported; conditional pause mutation needs a separately reviewed script. |
| [kube-metrics.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/kube-metrics.yaml) · `kube-metrics-pod` | 1 rewrite | sh, kube-metrics external tool and its metrics backend | Use kubectl top where Metrics Server/RBAC permit; unavailable metrics are not zero. External metrics aggregation is not native; explicitly pin the tool connection instead of relying on ambient defaults. |
| [kubectl/kubectl-purge](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/kubectl/kubectl-purge) · executable helper | legacy | bash, kubectl, Helm 2/Tiller, grep/cut, BSD xargs -J | Review migration to Helm 3 before using helm uninstall. Executable helper, not YAML. Legacy purge, unquoted substitutions and BSD-only xargs are not supported recipes. |
| [kubectl-get-in-shell.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/kubectl-get-in-shell.yaml) · `kubectl-get-cmd` | 1 rewrite | bash, kubectl, less | Use resource details/YAML or compose an explicit kubectl get argument vector. Printing shell text is not execution safety; shell conditionals/formatting require a reviewed script. |
| [kubectl-plugins/kubectl-jq](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/kubectl-plugins/kubectl-jq) · executable helper | rewrite | bash, kubectl, jq | Use kubectl logs with jq explicitly, or bounded native log viewing. Executable helper, not YAML; replace unquoted arguments and review raw terminal/color output. |
| [liveMigration.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/liveMigration.yaml) · `liveMigration` | 1 argv | virtctl, compatible KubeVirt controller/CRDs and migration permissions | Inspect KubeVirt CRDs; run installed virtctl deliberately for migration. Migration is an external effectful operation; the fixture tests arguments, not a real migration. |
| [log-bunyan.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/log-bunyan.yaml) · `bunyanlogsp`, `bunyanlogsd`, `bunyanlogss` | 3 rewrite | bash, kubectl, Node.js/bunyan | Use bounded native logs or kubectl logs and a separately installed JSON formatter. Pipelines and an interactive shell are not automatically translated; service/deployment log selection is external. |
| [log-full.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/log-full.yaml) · `raw-logs-follow`, `log-less`, `log-less-container` | 1 rewrite, 1 argv, 1 view | kubectl, bash/less for pager variants | Use native bounded logs or aggregate logs for active Pods/workloads. Container pager scope needs an explicit container input; foreground output is outside capture bounds/redaction. |
| [log-jq.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/log-jq.yaml) · `jqlogs` | 1 rewrite | kubectl-jq helper, bash, kubectl, jq | Use native log viewing or reviewed kubectl logs piped to jq. External helper remains required; its original unquoted shell recipe is not bundled. |
| [log-loki.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/log-loki.yaml) · `loki-container`, `loki-container-raw`, `loki-pods`, `loki-pods-raw`, `loki-node`, `loki-node-raw`, `loki-ns`, `loki-ns-raw` | 6 argv, 2 view | logcli, Loki server/credentials and its retained logs | Use native current-container logs; those do not replace Loki history/query services. Loki is a separately configured service/identity. Root-row fixtures test query argv only; container virtual scopes are unavailable. |
| [log-stern.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/log-stern.yaml) · `stern` | 1 argv | stern, Kubernetes log permissions | Use native Pod/workload aggregate logs with its documented reader limit. Quote numeric argv; use an explicit selector input because empty FILTER has no selected-name fallback. |
| [node-root-shell.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/node-root-shell.yaml) · `node-root-shell` | 1 rewrite | bash, kubectl, privileged Pod admission, nsenter, host shell | Inspect node details/YAML; review node debugging separately. The pinned script reads $1 without passing a selected host, uses an old image and privileged host namespaces; no automatic translation. |
| [openssl.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/openssl.yaml) · `secret-openssl-ca`, `secret-openssl-tls` | 2 rewrite | bash, kubectl, base64, openssl storeutl, less | Explicitly reveal the intended Secret key, then inspect a certificate with local OpenSSL. Certificate decoding is external and discloses Secret content; compatible OpenSSL commands need verification. |
| [pvc-debug-container.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/pvc-debug-container.yaml) · `pvc-shell` | 1 rewrite | sh, kubectl, head, permitted debug image and PVC access | Inspect PVC/Pod details and use a reviewed temporary Pod manifest with kubectl. Resource creation, RWO scheduling, heredocs, waits and cleanup require a reviewed script; not a native debug session. |
| [pvc-resize.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/pvc-resize.yaml) · `resize-pvc` | 1 argv | kubectl, expandable StorageClass/CSI driver and resize permissions | Review a PVC storage request change with kubectl; observe actual driver/controller status. A quantity allowlist replaces free-form JSON interpolation. No real storage expansion is certified by argv fixtures. |
| [remove-finalizers.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/remove-finalizers.yaml) · `remove_finalizers` | 1 argv | kubectl, target-resource patch permissions | Use the built-in deliberate finalizer workflow where supported, or a reviewed kubectl patch. Removing finalizers can bypass cleanup. The fixture is deliberately restricted to apps/v1 Deployments rather than global scope. |
| [resource-recommendations.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/resource-recommendations.yaml) · `krr`, `krr-ns` | 2 rewrite | bash, kubectl, awk, krr, supported Prometheus/backend | Inspect requests/limits; use separately configured kubectl top/metrics tools for observations. Recommendations remain external; the pinned namespace recipe uses RESOURCE_NAME rather than selected NAME and needs correction. |
| [rm-ns.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/rm-ns.yaml) · `rm-ns` | 1 rewrite | sh, kubectl, jq, namespace finalize permissions | Use reviewed ordinary namespace deletion and investigate finalizers first. Force-finalize is destructive; shell pipelines and missing explicit scope must be rewritten, never run blindly. |
| [spark-operator.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/spark-operator.yaml) · `toggleScheduledSparkApp` | 1 argv | kubectl, Spark Operator CRDs/controller | Inspect scheduled Spark CRDs and explicitly set suspend with kubectl. Rename the mixed-case command and replace inversion with an explicit desired boolean; verify the served GVR. |
| [start-alpine.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/start-alpine.yaml) · `start-alpine-pod` | 1 rewrite | bash, kubectl, permitted image and workload create/exec permissions | Use an existing container shell or review an explicit temporary Pod manifest. Embedded manifest creation/exec and cleanup are not a native debug workflow; a reviewed external script is needed. |
| [szero.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/szero.yaml) · `szero-down`, `szero-up` | 2 rewrite | sh, szero and workload scale permissions | Use reviewed per-workload scaling; record desired replica counts yourself. Namespace-wide down/up state storage and restoration belong to the external tool, not native scaling. |
| [trace-dns.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/trace-dns.yaml) · `trace-dns` | 1 view | bash, kubectl debug, Inspektor Gadget image/eBPF support, awk/cut, privileged node access | Inspect DNS-related events/logs; perform packet tracing with a separately reviewed diagnostic tool. Shell arithmetic/variables, virtual container scope and privileged debug Pods require review; no native DNS/eBPF tracing claim. |
| [vector-dev-top.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/vector-dev-top.yaml) · `vector-top`, `vector-top-container` | 1 rewrite, 1 view | sh, kubectl, a Vector container with vector executable/API enabled | Use native logs; Vector throughput statistics require Vector itself. Pod recipe can be rewritten as literal exec; virtual-container variant needs an explicit container input. |
| [watch-events.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/watch-events.yaml) · `watch-events` | 1 rewrite | sh, kubectl events/watch permissions | Use native related-event snapshots or the original background example in this guide. Shell conditional resource-group construction is not copied; the original example deliberately scopes to Pod events. |
