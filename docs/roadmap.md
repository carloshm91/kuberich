# Product roadmap

KubeRich is an independent terminal application inspired by K9s, built with
Python and Textual. The plan covers a broad Kubernetes operator workflow;
feature parity is tracked by delivered behavior, never inferred from a keybinding
or a placeholder screen.

## Milestones

| Milestone | Usable outcome |
| --- | --- |
| v0.0.1 | Internal core checkpoint: contexts/namespaces, live pods, filters, details, logs, exec and local distribution candidates |
| v0.1.0 | First qualified public phase: workload operations, delivered generic/aggregate views and embedded history; standard resource families, edit/diff, scale/restart/rollback, delete/jobs, port-forward, standalone binaries |
| v0.2.0 | Extensibility: generic CRDs, configurable views/keys/themes, external plugins, multi-container logs, explicit secret handling |
| v0.3.0 | Observability: metrics, cluster overview, resource relationships, RBAC analysis, guided troubleshooting, sanitized exports, Helm, local manifests and image scans |
| v0.4.0 | Advanced operations: node shell, cordon/drain, ephemeral debugging, service benchmarks, policy/quota exploration |
| v0.5.0 | Extended delivery: Windows, shell completion, OCI image and tested distribution recipes |
| v1.0.0 | Stable product: all feature checkpoints, supported API/terminal/platform matrix, compatibility, performance, install and full capability qualification |
| Later: documentation website | Expanded, versioned MkDocs documentation after the initial qualified product |

The maintainer requested usable qualified 0.x phases on 2026-10-09, beginning
with 0.1.0 and superseding the earlier first-public-1.0-only policy. Each selected
phase requires its own gate, all prior phase gates, transitive features and
tracked launch/feedback issues. Unknown minor lines need a reviewed mapping.
0.x compatible fixes use patches; intentional breaking changes need reviewed
minor/migration notes. 1.0 retains stable compatibility and capability audit.
No delivery dates or speculative patch releases are invented. See
[release policy](releases.md) for exact gate/approval rules.

## Public launch preparation

The maintainer approved opening the Apache-2.0 source repository in #155 on
2026-10-08. The separate GitHub project remains private. The first public product
is planned at qualified 0.1.0; packages are not available yet.
Prepare a simple landing page and initial documentation before that product
launch. The landing page should explain the product
and show its actual terminal interface; initial documentation should cover
verified installation, a quick start, supported features, and known limitations.
This launch material does not wait for the expanded documentation milestone.

The chosen name is **KubeRich**, with `kuberich` as the CLI and distribution
name. The maintainer confirmed purchasing `kuberich.com` on 2026-10-08.
[The focused migration and name review #149](https://github.com/carloshm91/kuberich/issues/149)
records pronunciation, namespace observations, existing commercial uses and the
unverified trademark-search boundary; the maintainer does not require trademark
investigation as a migration prerequisite. The reviewed identity migration #149 is delivered; source opening #155 is
complete. Product publication remains separately qualified.

The proposed address structure is `kuberich.com` for the landing page and
`docs.kuberich.com` for documentation. [Initial launch material #150](https://github.com/carloshm91/kuberich/issues/150)
is prepared locally before #89; expanded versioned documentation remains
#90/#91 after the installable product. Domain ownership is maintainer-confirmed;
development landing/docs provider hosts are published and verified under #166;
custom-domain and exact-candidate public launch remain separate #89 work. DNS
changes, hosting publication and repository visibility changes require explicit
maintainer authorization. There is no automatic
publication deadline.

## Delivery policy

The [backlog](backlog.md) lists epics, implementation tasks, blockers, and the
recommended order. Work on one implementation task at a time. Preserve every feature dependency and required PR check. Complete the dedicated
phase/cumulative engineering qualification before publication; deferral does not
complete a gate. #89 owns first public-channel activation and verification.
Actual upgrades are required separately from fresh installs.

The initial planning/preparation task can be closed when the repository,
documentation, GitHub backlog, project, and protections are in place. That does
not complete any application feature or justify a release tag.

The exhaustive audit and source inventory live in [k9s-parity.md](k9s-parity.md).
The table below is an overview, not the full feature list.

## Capability map

| Capability | Target | Acceptance emphasis |
| --- | --- | --- |
| Context and namespace switching | 0.0.1 | No kubeconfig mutation or late data from a previous context |
| Live resource browsing | 0.0.1 | Correct list/watch recovery, stable selection, typed sorting |
| Keyboard/mouse navigation and scrolling | 0.0.1 | Predictable focus, narrow-terminal behavior, useful key hints |
| Resource YAML, events, and details | 0.0.1 | Accurate data, redacted sensitive fields, explicit permission errors |
| Current/previous container logs | 0.0.1 | Bounded buffering, pause/follow, container selection, cancellation |
| Interactive shell | 0.0.1 | Full-terminal handoff, explicit target, reliable restoration |
| Port-forward and editing | 0.1.0 | Owned process lifecycle, diff/validation/conflict handling |
| Workload mutations | 0.1.0 | Read-only mode, target confirmation, clear partial/uncertain outcomes |
| Core workload/network/storage families | 0.1.0 | Resource-specific actions and meaningful columns |
| Generic discovery and CRDs | 0.2.0 | Namespaced/cluster-scoped resources and server-provided columns |
| Themes, aliases, hotkeys, custom columns | 0.2.0 | Validated configuration and accessible display |
| External command plugins | 0.2.0 | Scope/argument/environment contract and explicit execution |
| Metrics, overview, and relationships | 0.3.0 | Unavailable is distinct from zero; bounded queries |
| RBAC and troubleshooting | 0.3.0 | Explain evidence, permissions, and uncertainty |
| Node shell/drain/debug and benchmarks | 0.4.0 | Explicit scope, cleanup, disruption handling, bounded load |
| Stability | 1.0.0 | Audited support claims, migrations, parity inventory, performance evidence |

## Deliberate boundaries

No Textual Web, hosted backend, mandatory account, telemetry, or AI service is
required for the product. The shell supports an embedded terminal and an explicit native-terminal handoff. Windows binaries, distribution
repositories such as apt/rpm, and Homebrew/core submission are
tracked in v0.5.0 after the initial supported channels are reliable. No future work is advertised
as an implemented capability.

## Execution order

Follow the phased topological execution order in [backlog.json](backlog.json), including tracked
preview refinements. The product implementation is already in progress; select
the next unblocked issue rather than restarting completed bootstrap work.
