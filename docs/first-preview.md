# Status

KubeRich 0.4.0 is published on [PyPI](https://pypi.org/project/kuberich/0.4.0/),
[GitHub Releases](https://github.com/carloshm91/kuberich/releases/tag/v0.4.0) and
the [Homebrew tap](https://github.com/kuberich/homebrew-tap), including prebuilt
bottles on its supported targets.

Install the current Python package with Python 3.12–3.14:

```sh
uv tool install --python 3.12 kuberich
kuberich --version
# kuberich 0.4.0
```

The version command was verified from the published package in an isolated
installation. Read [Install](installation.md) for Homebrew, pipx, standalone
downloads, upgrades and removal. The [quick start](quickstart.md) explains
choosing your context and namespace and starting in read-only mode.

Version 0.4.0 adds observability and investigation tools to the existing resource
browser, logs, shells, file transfers, port forwarding, workload changes,
themes, navigation preferences and local plugins:

- Read current CPU/memory usage, requests and limits in Pod, workload, Node and
  container tables. [Current metrics](resource-workspace.md#current-cpu-and-memory-metrics)
  distinguishes missing APIs, denied access, absent or stale samples and measured zero.
- Open the native [cluster overview](cluster-overview.md) for scoped health,
  capacity summaries and exact resource drill-downs. Shift+M opens supported
  resource/container charts with CPU, memory, network and filesystem source
  states and 15m–24h ranges. History needs an explicitly selected compatible
  backend; KubeRich does not install one.
- Follow owners, selectors, endpoints and placement with `:xray`, or inspect
  supported configuration, storage and identity declarations with `:usedby`.
  [Resource relationships](resource-relationships.md) keeps UID replacements
  and incomplete source scans explicit.
- Use `:rbac` for observed subjects, bindings and roles, or
  `:can-i list pods --all-namespaces` to ask the API server about your current
  identity. [Permission inspection](authorization.md) distinguishes missing
  privileges, incomplete evidence and unknown results. Informational views do
  not enable guarded operations.
- Open `:diagnostics` for the selected namespace or `:diagnose` for a captured
  Pod or supported workload. [Failure diagnostics](cluster-diagnostics.md)
  retains conditions, events, source gaps and guarded resource/log links.
  Optional `:popeye` runs only an explicitly configured tool.
- [Review and save local exports](exports.md), including redacted resource YAML,
  logs, diagnostics, screen text and support JSON. Browse saved files with `:exports`.
- [Inspect container configuration](log-viewer.md#inspect-container-environment-and-image-facts) with `e` from
  the container list. Environment sources, precedence and image facts are
  available while values remain hidden until a separate review.
- Browse additional curated resource families and filter or group Events. See
  [curated views](resource-workspace.md#curated-read-only-views) for scope and limits.

See the [0.4.0 release notes](release-notes/0.4.0.md) for fixes and known limits.
Existing preferences, legacy environment variables and log locations remain
supported. Version 0.4 removes the deprecated `kubetrol` command and Python shim;
use `kuberich` in scripts and launchers. Pipx users crossing from 0.3 need the
[one-time reinstall](installation.md#upgrade-from-03-to-04), with explicit
replacement of pinned 0.3 requirements. Upgrades leave preferences and kubeconfig
intact.

Real EKS, AKS and GKE cluster trials remain separate from local testing. Follow
[contexts and authentication](context-sessions.md) for provider prerequisites.
Startup and large-collection latency goals remain advisory during 0.x; this
release does not claim complete K9s parity or in-app Helm release management.

Development work for 0.5 adds a separate
[Helm workspace](workloads.md#browse-helm-releases-in-development-source), including
chart catalogs, values editing and separate install/upgrade/uninstall reviews, and a
[local manifest workflow](workloads.md#local-manifests-and-kustomize-in-development-source).
Final qualification of those development changes is still in progress. They are
not included in the published 0.4.0 packages.
