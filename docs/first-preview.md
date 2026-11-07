# Status

KubeRich 0.3.0 is published on [PyPI](https://pypi.org/project/kuberich/0.3.0/),
[GitHub Releases](https://github.com/carloshm91/kuberich/releases/tag/v0.3.0) and
[Homebrew](https://github.com/kuberich/homebrew-tap), including prebuilt
Homebrew bottles on the supported targets.

Choose one installation method:

```sh
brew install kuberich/tap/kuberich
# Or, with Python 3.12–3.14:
uv tool install --python 3.12 kuberich
kuberich --version
```

Read [Install](installation.md) for Homebrew, pipx, standalone downloads,
upgrades and removal. The [quick start](quickstart.md) explains choosing your
context and namespace and starting in read-only mode.

The published release includes resource browsing, logs, shells, file transfers,
port forwarding, workload changes, themes, navigation preferences and local
plugins. Version 0.3.0 adds reliability fixes, collection limits and clearer task
guides. See the [0.3.0 release notes](release-notes/0.3.0.md) for the changes.
Existing 0.2.0 preferences load unchanged; use `kuberich` instead of the
warning-producing `kubetrol` alias.

Real EKS, AKS and GKE cluster trials remain separate from local testing. Follow
[contexts and authentication](context-sessions.md) for provider prerequisites.

## Resource metrics in development source

Development source for the next 0.4.0 phase adds read-only current CPU/memory
metrics to Pod, workload, Node and container views. It distinguishes missing APIs, permission
denial, no sample, stale samples and measured zero. See
[current metrics](resource-workspace.md#current-cpu-and-memory-metrics) for units,
percentages and allocation limits. This work is not part of installed 0.3.0.

Development source also adds the native [cluster overview](cluster-overview.md)
with health/capacity summaries, exact resource drill-downs and optional configured
Prometheus-compatible history. Shift+M opens selected resource/container charts
with CPU, memory, network and filesystem source states and 15m–24h ranges. Its source states distinguish missing, denied,
partial and stale data; it does not install a metrics backend. These capabilities
remain unreleased work for 0.4.0.

Development source adds [resource relationships](resource-relationships.md):
`:xray` follows owners, selectors, endpoints and placement; `:usedby` finds
supported configuration, storage and identity declarations. UID replacement and
incomplete source scans remain explicit. These views are not in installed 0.3.0.

Development source also adds [permission inspection](authorization.md). Use
`:rbac` to browse observed subjects, bindings and roles, or
`:can-i list pods --all-namespaces` to ask the API server about your current
identity. Both commands were exercised in an owned local-cluster trial. Missing
review/list privileges and incomplete who-can evidence remain explicit; these
informational views do not enable guarded operations. They are unreleased work
for 0.4.0 and are not part of installed 0.3.0.

Development source also keeps container-validation notices visible during table
refreshes and finishes closing log views when a refresh deadline overlaps
shutdown. A controlled shutdown check requires the first close request to finish
and release the log reader and lease. Cumulative 0.4.0 verification remains in
progress; installed channels still provide 0.3.0.

In a development checkout, the verified version command is:

```sh
uv run kuberich --version
# kuberich 0.4.0
```

Development source adds [failure diagnostics](cluster-diagnostics.md).
Use `:diagnostics` for the selected namespace or `:diagnose` for a captured Pod
or supported workload. Findings retain conditions, events, source gaps and
guarded resource/container-log links. The optional `:popeye` command runs only
an explicitly configured tool; native refresh and history never rerun it.
External reports keep their name-only identity limits. These views are not part
of installed 0.3.0.
