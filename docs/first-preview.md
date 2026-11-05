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
