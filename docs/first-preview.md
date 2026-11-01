# Status

KubeRich 0.2.0 is published on [PyPI](https://pypi.org/project/kuberich/0.2.0/),
[GitHub Releases](https://github.com/carloshm91/kuberich/releases/tag/v0.2.0) and
[Homebrew](https://github.com/kuberich/homebrew-tap).

Choose one installation method:

```sh
brew install kuberich/tap/kuberich
# Or, with Python 3.12–3.14:
uv tool install --python 3.12 kuberich
kuberich --version
```

Read [Install](installation.md) for standalone downloads, upgrades and removal.
The [quick start](quickstart.md) explains choosing your context and namespace
and starting in read-only mode.

The published release includes resource browsing, logs, shells, file transfers,
port forwarding, workload changes, themes, navigation preferences and local
plugins. See the [0.2.0 release notes](release-notes/0.2.0.md) for the changes
and the [quick-start guide](quickstart.md) for tasks and configuration.

The 0.3.0 development phase focuses on reliability, startup, maintainability and
documentation. It is not a published release. A source checkout can contain
changes that are absent from the installed 0.2.0 package.

Real EKS, AKS and GKE cluster trials remain separate from local testing. Follow
[contexts and authentication](context-sessions.md) for provider prerequisites.
