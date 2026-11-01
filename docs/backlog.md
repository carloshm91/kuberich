# Backlog and implementation order

[Open the GitHub project](https://github.com/users/carloshm91/projects/3).

The plan has **15 epics and 124 tasks**. GitHub issues are the live
status source; this file is the planning map, built from [backlog.json](backlog.json).

Work on one implementation task at a time. Pick the first unblocked task in the
earliest unfinished milestone, following `delivery.execution_order`.

## Current maintainer priority

On 2026-10-19 the maintainer approved a revised phase plan
([#221](https://github.com/carloshm91/kuberich/issues/221)) and authorized finishing v0.2.0 in this order:
**#221 → #63 → #64 → #193 → #65**. #124 moved to v0.8.0. Publishing any
artifact, tag or website still needs explicit approval. After #65, the v0.3.0
foundations and documentation work starts before any new feature family.

## Release phases

| Public line | Gate (plus every earlier gate) | Phase scope |
| --- | --- | --- |
| 0.1.x | D06 #51 | Core workspace; also #53, #54 and #123 |
| 0.2.x | D07 #65 | Extensibility; also Homebrew bottles #193 |
| 0.3.x | D16 #230 | Foundations and documentation; also #189, #208 and dependency refresh #270 |
| 0.4.x | D08 #75 | Observability and metrics |
| 0.5.x | D09 #82 | Operations, Helm and manifests |
| 0.6.x | D17 #242 | Multi-cluster workspace |
| 0.7.x | D18 #248 | Extensions, security center and AI |
| 0.8.x | D11 #86 | Platforms (Windows) and accessibility; also #124 |
| 0.9.x | D19 #253 | Release candidate |
| 1.0.x | Q06 #88 | Stable release and K9s/Lens parity audit |

D10 #89 owns first public activation; patches and later phases require it
closed. Common launch issues #149/#150/#154/#155/#157/#162/#166 stay required.
Q07 #81 is closed as not planned and is not a prerequisite. See the
[release policy](releases.md).

## Epics

| Issue | Outcome | Completion milestone |
| --- | --- | --- |
| [E01 #1](https://github.com/carloshm91/kuberich/issues/1) | Project foundation and enforced quality | v0.0.1 |
| [E02 #2](https://github.com/carloshm91/kuberich/issues/2) | Kubernetes sessions, discovery, and live state | v0.2.0 |
| [E03 #3](https://github.com/carloshm91/kuberich/issues/3) | Terminal resource browsing and navigation | v0.2.0 |
| [E04 #4](https://github.com/carloshm91/kuberich/issues/4) | Logs and interactive sessions | v0.2.0 |
| [E05 #5](https://github.com/carloshm91/kuberich/issues/5) | Safe workload and configuration operations | v0.5.0 |
| [E06 #6](https://github.com/carloshm91/kuberich/issues/6) | Themes, configuration, and plugins | v0.2.0 |
| [E07 #7](https://github.com/carloshm91/kuberich/issues/7) | Observability and troubleshooting | v0.4.0 |
| [E08 #8](https://github.com/carloshm91/kuberich/issues/8) | Advanced cluster operations | v0.5.0 |
| [E09 #9](https://github.com/carloshm91/kuberich/issues/9) | Packaging, installation, and release delivery | v1.0.0 |
| [E10 #10](https://github.com/carloshm91/kuberich/issues/10) | Integration, performance, and compatibility qualification | v1.0.0 |
| [E11 #11](https://github.com/carloshm91/kuberich/issues/11) | User documentation and contribution experience | v0.9.0 |
| [E12 #12](https://github.com/carloshm91/kuberich/issues/12) | Extended platforms, accessibility and ecosystem delivery | v0.8.0 |
| [E13 #254](https://github.com/carloshm91/kuberich/issues/254) | Foundations and engineering quality | v0.3.0 |
| [E14 #255](https://github.com/carloshm91/kuberich/issues/255) | Multi-cluster workspace beyond Lens | v0.6.0 |
| [E15 #256](https://github.com/carloshm91/kuberich/issues/256) | Ecosystem and intelligence | v0.7.0 |

## v0.0.1

Core engineering foundation: live pods, navigation, details, logs, exec and qualified local installation. No public 0.0.1 release is promised; first public activation is 0.1.0 under D10.

| Issue | Task | Blocked by |
| --- | --- | --- |
| [F00 #13](https://github.com/carloshm91/kuberich/issues/13) | Prepare repository governance and the complete implementation backlog | None |
| [F01 #14](https://github.com/carloshm91/kuberich/issues/14) | Bootstrap the installable Python package and developer toolchain | [F00 #13](https://github.com/carloshm91/kuberich/issues/13) |
| [F02 #15](https://github.com/carloshm91/kuberich/issues/15) | Enforce independent coverage and required application CI gates | [F01 #14](https://github.com/carloshm91/kuberich/issues/14) |
| [F03 #16](https://github.com/carloshm91/kuberich/issues/16) | Implement validated configuration and sanitized diagnostics | [F02 #15](https://github.com/carloshm91/kuberich/issues/15) |
| [B01 #17](https://github.com/carloshm91/kuberich/issues/17) | Build the Textual application shell and responsive layout | [F02 #15](https://github.com/carloshm91/kuberich/issues/15), [F03 #16](https://github.com/carloshm91/kuberich/issues/16) |
| [F04 #18](https://github.com/carloshm91/kuberich/issues/18) | Define and test Kubernetes, plugin, and terminal trust boundaries | [F02 #15](https://github.com/carloshm91/kuberich/issues/15) |
| [C01 #20](https://github.com/carloshm91/kuberich/issues/20) | Create isolated kubeconfig and context sessions | [F03 #16](https://github.com/carloshm91/kuberich/issues/16), [F04 #18](https://github.com/carloshm91/kuberich/issues/18) |
| [F05 #19](https://github.com/carloshm91/kuberich/issues/19) | Implement the complete launch CLI and diagnostic command contract | [F03 #16](https://github.com/carloshm91/kuberich/issues/16), [F04 #18](https://github.com/carloshm91/kuberich/issues/18), [C01 #20](https://github.com/carloshm91/kuberich/issues/20) |
| [C06 #21](https://github.com/carloshm91/kuberich/issues/21) | Qualify EKS authentication and credential refresh | [C01 #20](https://github.com/carloshm91/kuberich/issues/20), [F05 #19](https://github.com/carloshm91/kuberich/issues/19) |
| [C07 #22](https://github.com/carloshm91/kuberich/issues/22) | Qualify AKS Entra and Azure kubelogin authentication | [C01 #20](https://github.com/carloshm91/kuberich/issues/20), [F05 #19](https://github.com/carloshm91/kuberich/issues/19) |
| [C02 #23](https://github.com/carloshm91/kuberich/issues/23) | Implement API discovery and consistent paginated resource listing | [C01 #20](https://github.com/carloshm91/kuberich/issues/20) |
| [C03 #24](https://github.com/carloshm91/kuberich/issues/24) | Implement resilient list-watch synchronization | [C02 #23](https://github.com/carloshm91/kuberich/issues/23) |
| [C04 #25](https://github.com/carloshm91/kuberich/issues/25) | Own session cancellation and reject stale-context updates | [C03 #24](https://github.com/carloshm91/kuberich/issues/24) |
| [B02 #26](https://github.com/carloshm91/kuberich/issues/26) | Implement the live pod table with stable selection and typed sorting | [B01 #17](https://github.com/carloshm91/kuberich/issues/17), [C04 #25](https://github.com/carloshm91/kuberich/issues/25) |
| [B03 #27](https://github.com/carloshm91/kuberich/issues/27) | Add resource commands, filtering, namespace shortcuts, and help | [B02 #26](https://github.com/carloshm91/kuberich/issues/26) |
| [B04 #28](https://github.com/carloshm91/kuberich/issues/28) | Show YAML, resource details, and related events | [B03 #27](https://github.com/carloshm91/kuberich/issues/27), [C02 #23](https://github.com/carloshm91/kuberich/issues/23), [F04 #18](https://github.com/carloshm91/kuberich/issues/18) |
| [S01 #29](https://github.com/carloshm91/kuberich/issues/29) | Implement cancellable current and previous container log streams | [C04 #25](https://github.com/carloshm91/kuberich/issues/25) |
| [S02 #30](https://github.com/carloshm91/kuberich/issues/30) | Build the log viewer with pause, follow, search, and bounded scrolling | [S01 #29](https://github.com/carloshm91/kuberich/issues/29), [B03 #27](https://github.com/carloshm91/kuberich/issues/27), [F04 #18](https://github.com/carloshm91/kuberich/issues/18) |
| [S03 #31](https://github.com/carloshm91/kuberich/issues/31) | Implement explicit-target subprocess and terminal handoff services | [F04 #18](https://github.com/carloshm91/kuberich/issues/18), [C01 #20](https://github.com/carloshm91/kuberich/issues/20), [F05 #19](https://github.com/carloshm91/kuberich/issues/19) |
| [S04 #32](https://github.com/carloshm91/kuberich/issues/32) | Provide interactive exec with container selection and reliable return | [S03 #31](https://github.com/carloshm91/kuberich/issues/31), [B02 #26](https://github.com/carloshm91/kuberich/issues/26) |
| [Q02 #33](https://github.com/carloshm91/kuberich/issues/33) | Verify real terminal, SSH, tmux and shell restoration behavior | [B03 #27](https://github.com/carloshm91/kuberich/issues/27), [S02 #30](https://github.com/carloshm91/kuberich/issues/30), [S04 #32](https://github.com/carloshm91/kuberich/issues/32) |
| [D01 #34](https://github.com/carloshm91/kuberich/issues/34) | Build and verify wheel and source distribution artifacts | [F02 #15](https://github.com/carloshm91/kuberich/issues/15) |
| [Q04 #35](https://github.com/carloshm91/kuberich/issues/35) | Add dependency security, license, SBOM and provenance checks | [D01 #34](https://github.com/carloshm91/kuberich/issues/34), [F04 #18](https://github.com/carloshm91/kuberich/issues/18) |
| [D02 #36](https://github.com/carloshm91/kuberich/issues/36) | Create the approved immutable release pipeline and PyPI publishing | [D01 #34](https://github.com/carloshm91/kuberich/issues/34), [Q04 #35](https://github.com/carloshm91/kuberich/issues/35) |
| [D03 #37](https://github.com/carloshm91/kuberich/issues/37) | Create and test the Homebrew tap and formula delivery | [D01 #34](https://github.com/carloshm91/kuberich/issues/34), [D02 #36](https://github.com/carloshm91/kuberich/issues/36) |
| [Q01 #38](https://github.com/carloshm91/kuberich/issues/38) | Build the disposable Kubernetes integration and API fault suite | [C04 #25](https://github.com/carloshm91/kuberich/issues/25), [B04 #28](https://github.com/carloshm91/kuberich/issues/28), [S04 #32](https://github.com/carloshm91/kuberich/issues/32), [S02 #30](https://github.com/carloshm91/kuberich/issues/30), [C06 #21](https://github.com/carloshm91/kuberich/issues/21), [C07 #22](https://github.com/carloshm91/kuberich/issues/22) |
| [W01 #39](https://github.com/carloshm91/kuberich/issues/39) | Write and validate the first-user installation and trial guide | [B04 #28](https://github.com/carloshm91/kuberich/issues/28), [S04 #32](https://github.com/carloshm91/kuberich/issues/32), [S02 #30](https://github.com/carloshm91/kuberich/issues/30), [D03 #37](https://github.com/carloshm91/kuberich/issues/37), [C06 #21](https://github.com/carloshm91/kuberich/issues/21), [C07 #22](https://github.com/carloshm91/kuberich/issues/22) |
| [D04 #40](https://github.com/carloshm91/kuberich/issues/40) | Qualify the core terminal engineering checkpoint | [F00 #13](https://github.com/carloshm91/kuberich/issues/13), [F01 #14](https://github.com/carloshm91/kuberich/issues/14), [F02 #15](https://github.com/carloshm91/kuberich/issues/15), [F03 #16](https://github.com/carloshm91/kuberich/issues/16), [F04 #18](https://github.com/carloshm91/kuberich/issues/18), [C01 #20](https://github.com/carloshm91/kuberich/issues/20), [C02 #23](https://github.com/carloshm91/kuberich/issues/23), [C03 #24](https://github.com/carloshm91/kuberich/issues/24), [C04 #25](https://github.com/carloshm91/kuberich/issues/25), [B01 #17](https://github.com/carloshm91/kuberich/issues/17), [B02 #26](https://github.com/carloshm91/kuberich/issues/26), [B03 #27](https://github.com/carloshm91/kuberich/issues/27), [B04 #28](https://github.com/carloshm91/kuberich/issues/28), [S01 #29](https://github.com/carloshm91/kuberich/issues/29), [S02 #30](https://github.com/carloshm91/kuberich/issues/30), [S03 #31](https://github.com/carloshm91/kuberich/issues/31), [S04 #32](https://github.com/carloshm91/kuberich/issues/32), [F05 #19](https://github.com/carloshm91/kuberich/issues/19), [C06 #21](https://github.com/carloshm91/kuberich/issues/21), [C07 #22](https://github.com/carloshm91/kuberich/issues/22), [D01 #34](https://github.com/carloshm91/kuberich/issues/34), [D02 #36](https://github.com/carloshm91/kuberich/issues/36), [D03 #37](https://github.com/carloshm91/kuberich/issues/37), [Q01 #38](https://github.com/carloshm91/kuberich/issues/38), [Q02 #33](https://github.com/carloshm91/kuberich/issues/33), [Q04 #35](https://github.com/carloshm91/kuberich/issues/35), [W01 #39](https://github.com/carloshm91/kuberich/issues/39) |

## v0.1.0

Standard resource families, safe workload mutations, editing, port forwarding, standalone executables, and performance qualification. First usable public phase after core/workload, standalone, performance and terminal-history qualification; activation remains owner-reviewed D10.

| Issue | Task | Blocked by |
| --- | --- | --- |
| [B05 #41](https://github.com/carloshm91/kuberich/issues/41) | Add standard workload, networking, and storage resource views | [B04 #28](https://github.com/carloshm91/kuberich/issues/28), [C02 #23](https://github.com/carloshm91/kuberich/issues/23) |
| [S05 #42](https://github.com/carloshm91/kuberich/issues/42) | Manage port-forward sessions and their lifecycle | [S03 #31](https://github.com/carloshm91/kuberich/issues/31), [S04 #32](https://github.com/carloshm91/kuberich/issues/32) |
| [M01 #43](https://github.com/carloshm91/kuberich/issues/43) | Create guarded mutation services and read-only mode | [C04 #25](https://github.com/carloshm91/kuberich/issues/25), [F04 #18](https://github.com/carloshm91/kuberich/issues/18), [B04 #28](https://github.com/carloshm91/kuberich/issues/28) |
| [M02 #44](https://github.com/carloshm91/kuberich/issues/44) | Edit manifests with preview, validation, and conflict handling | [M01 #43](https://github.com/carloshm91/kuberich/issues/43), [S03 #31](https://github.com/carloshm91/kuberich/issues/31) |
| [M03 #45](https://github.com/carloshm91/kuberich/issues/45) | Implement scale and rollout operations | [M01 #43](https://github.com/carloshm91/kuberich/issues/43), [B05 #41](https://github.com/carloshm91/kuberich/issues/41) |
| [M04 #46](https://github.com/carloshm91/kuberich/issues/46) | Implement deletion and Job/CronJob operations | [M01 #43](https://github.com/carloshm91/kuberich/issues/43), [B05 #41](https://github.com/carloshm91/kuberich/issues/41) |
| [C08 #47](https://github.com/carloshm91/kuberich/issues/47) | Qualify generic kubeconfig, GKE, OIDC, proxy and authentication transport | [C06 #21](https://github.com/carloshm91/kuberich/issues/21), [C07 #22](https://github.com/carloshm91/kuberich/issues/22), [S04 #32](https://github.com/carloshm91/kuberich/issues/32) |
| [S07 #48](https://github.com/carloshm91/kuberich/issues/48) | Attach to containers and transfer files with explicit targets | [S04 #32](https://github.com/carloshm91/kuberich/issues/32), [M01 #43](https://github.com/carloshm91/kuberich/issues/43), [C08 #47](https://github.com/carloshm91/kuberich/issues/47) |
| [D05 #49](https://github.com/carloshm91/kuberich/issues/49) | Build and qualify standalone Linux and macOS executables | [D01 #34](https://github.com/carloshm91/kuberich/issues/34), [Q02 #33](https://github.com/carloshm91/kuberich/issues/33) |
| [Q03 #50](https://github.com/carloshm91/kuberich/issues/50) | Measure large-cluster responsiveness and sustained memory behavior | [Q01 #38](https://github.com/carloshm91/kuberich/issues/38), [S05 #42](https://github.com/carloshm91/kuberich/issues/42) |
| [D06 #51](https://github.com/carloshm91/kuberich/issues/51) | Qualify the workload operations engineering checkpoint | [B05 #41](https://github.com/carloshm91/kuberich/issues/41), [S05 #42](https://github.com/carloshm91/kuberich/issues/42), [M01 #43](https://github.com/carloshm91/kuberich/issues/43), [M02 #44](https://github.com/carloshm91/kuberich/issues/44), [M03 #45](https://github.com/carloshm91/kuberich/issues/45), [M04 #46](https://github.com/carloshm91/kuberich/issues/46), [C08 #47](https://github.com/carloshm91/kuberich/issues/47), [S07 #48](https://github.com/carloshm91/kuberich/issues/48), [D05 #49](https://github.com/carloshm91/kuberich/issues/49), [Q03 #50](https://github.com/carloshm91/kuberich/issues/50), [D04 #40](https://github.com/carloshm91/kuberich/issues/40) |
| [D10 #89](https://github.com/carloshm91/kuberich/issues/89) | Prepare phased releases and publish the first qualified 0.1.0 product | [D06 #51](https://github.com/carloshm91/kuberich/issues/51) |

## v0.2.0

Configurable themes, navigation/resource views, external plugins, deliberate configuration/secret workflows, context and completed-pod cleanup, custom-resource jumps and verified Homebrew bottles. Retains generic CRDs and aggregate logs from 0.1.0.

| Issue | Task | Blocked by |
| --- | --- | --- |
| [C05 #52](https://github.com/carloshm91/kuberich/issues/52) | Support dynamic custom resource discovery and version selection | [C02 #23](https://github.com/carloshm91/kuberich/issues/23), [B05 #41](https://github.com/carloshm91/kuberich/issues/41) |
| [B06 #53](https://github.com/carloshm91/kuberich/issues/53) | Deliver generic CRD tables and configurable resource columns | [C05 #52](https://github.com/carloshm91/kuberich/issues/52), [B05 #41](https://github.com/carloshm91/kuberich/issues/41) |
| [S06 #54](https://github.com/carloshm91/kuberich/issues/54) | Add aggregated logs and structured-output controls | [S02 #30](https://github.com/carloshm91/kuberich/issues/30), [B05 #41](https://github.com/carloshm91/kuberich/issues/41) |
| [M05 #55](https://github.com/carloshm91/kuberich/issues/55) | Add deliberate ConfigMap and Secret inspection/editing | [M02 #44](https://github.com/carloshm91/kuberich/issues/44), [B05 #41](https://github.com/carloshm91/kuberich/issues/41) |
| [U01 #56](https://github.com/carloshm91/kuberich/issues/56) | Implement configurable themes and accessible terminal presentation | [B03 #27](https://github.com/carloshm91/kuberich/issues/27), [F03 #16](https://github.com/carloshm91/kuberich/issues/16) |
| [U02 #57](https://github.com/carloshm91/kuberich/issues/57) | Configure hotkeys, aliases, and resource views | [U01 #56](https://github.com/carloshm91/kuberich/issues/56), [B06 #53](https://github.com/carloshm91/kuberich/issues/53) |
| [U03 #58](https://github.com/carloshm91/kuberich/issues/58) | Define and load the external plugin contract | [S03 #31](https://github.com/carloshm91/kuberich/issues/31), [U02 #57](https://github.com/carloshm91/kuberich/issues/57), [F04 #18](https://github.com/carloshm91/kuberich/issues/18) |
| [U04 #59](https://github.com/carloshm91/kuberich/issues/59) | Execute plugins with bounded output and owned process cleanup | [U03 #58](https://github.com/carloshm91/kuberich/issues/58), [M01 #43](https://github.com/carloshm91/kuberich/issues/43) |
| [U05 #60](https://github.com/carloshm91/kuberich/issues/60) | Document and test plugin compatibility and example workflows | [U04 #59](https://github.com/carloshm91/kuberich/issues/59) |
| [B07 #61](https://github.com/carloshm91/kuberich/issues/61) | Complete navigation, filtering, scrolling and remote clipboard behavior | [B05 #41](https://github.com/carloshm91/kuberich/issues/41), [U02 #57](https://github.com/carloshm91/kuberich/issues/57), [Q02 #33](https://github.com/carloshm91/kuberich/issues/33) |
| [S08 #62](https://github.com/carloshm91/kuberich/issues/62) | Implement FastForward presets and port-forward transport compatibility | [S05 #42](https://github.com/carloshm91/kuberich/issues/42), [C08 #47](https://github.com/carloshm91/kuberich/issues/47) |
| [M08 #63](https://github.com/carloshm91/kuberich/issues/63) | Manage local context names and completed-pod cleanup | [C01 #20](https://github.com/carloshm91/kuberich/issues/20), [M01 #43](https://github.com/carloshm91/kuberich/issues/43), [B05 #41](https://github.com/carloshm91/kuberich/issues/41) |
| [U06 #64](https://github.com/carloshm91/kuberich/issues/64) | Implement custom resource jumps and reactive configuration | [U02 #57](https://github.com/carloshm91/kuberich/issues/57), [C05 #52](https://github.com/carloshm91/kuberich/issues/52) |
| [D07 #65](https://github.com/carloshm91/kuberich/issues/65) | Qualify the extensibility engineering checkpoint | [C05 #52](https://github.com/carloshm91/kuberich/issues/52), [B06 #53](https://github.com/carloshm91/kuberich/issues/53), [S06 #54](https://github.com/carloshm91/kuberich/issues/54), [M05 #55](https://github.com/carloshm91/kuberich/issues/55), [U01 #56](https://github.com/carloshm91/kuberich/issues/56), [U02 #57](https://github.com/carloshm91/kuberich/issues/57), [U03 #58](https://github.com/carloshm91/kuberich/issues/58), [U04 #59](https://github.com/carloshm91/kuberich/issues/59), [U05 #60](https://github.com/carloshm91/kuberich/issues/60), [B07 #61](https://github.com/carloshm91/kuberich/issues/61), [S08 #62](https://github.com/carloshm91/kuberich/issues/62), [M08 #63](https://github.com/carloshm91/kuberich/issues/63), [U06 #64](https://github.com/carloshm91/kuberich/issues/64), [D06 #51](https://github.com/carloshm91/kuberich/issues/51) |

## v0.3.0

Foundations and quality: decompose the application shell, decouple tests, remove private framework dependencies, degrade gracefully on large clusters, enforce a startup budget, reach kubeconfig parity with kubectl, add error boundaries and fast test tiers, and rewrite the documentation. No new feature families.

| Issue | Task | Blocked by |
| --- | --- | --- |
| [Q10 #209](https://github.com/carloshm91/kuberich/issues/209) | Add fast, parallel test tiers | None |
| [Q09 #210](https://github.com/carloshm91/kuberich/issues/210) | Decouple UI tests from private application state | [Q10 #209](https://github.com/carloshm91/kuberich/issues/209) |
| [Q08 #211](https://github.com/carloshm91/kuberich/issues/211) | Decompose KubeRichApp into view controllers and a declarative command registry | [Q09 #210](https://github.com/carloshm91/kuberich/issues/210) |
| [Q11 #212](https://github.com/carloshm91/kuberich/issues/212) | Remove private Textual API dependencies and relax the exact pin | [Q08 #211](https://github.com/carloshm91/kuberich/issues/211) |
| [Q12 #213](https://github.com/carloshm91/kuberich/issues/213) | Degrade gracefully for collections beyond 10,000 resources | None |
| [Q13 #214](https://github.com/carloshm91/kuberich/issues/214) | Enforce a startup-time budget with lazy imports | None |
| [Q14 #215](https://github.com/carloshm91/kuberich/issues/215) | Reach kubeconfig compatibility parity with kubectl | None |
| [Q15 #216](https://github.com/carloshm91/kuberich/issues/216) | Add per-view error boundaries and a redacted bug-report bundle | None |
| [Q16 #217](https://github.com/carloshm91/kuberich/issues/217) | Strengthen critical-module tests with property-based and mutation testing | None |
| [Q17 #218](https://github.com/carloshm91/kuberich/issues/218) | Replace manual phase qualification with one reproducible command | None |
| [Q18 #219](https://github.com/carloshm91/kuberich/issues/219) | Remove the legacy kubetrol identity | None |
| [Q19 #220](https://github.com/carloshm91/kuberich/issues/220) | Support the Wayland clipboard | None |
| [D15 #221](https://github.com/carloshm91/kuberich/issues/221) | Register the revised 0.3–0.9 phase plan in the release policy | None |
| [W04 #222](https://github.com/carloshm91/kuberich/issues/222) | Define the documentation structure and a plain-language style guide | None |
| [W05 #223](https://github.com/carloshm91/kuberich/issues/223) | Rewrite the README as a concise product page | [W04 #222](https://github.com/carloshm91/kuberich/issues/222) |
| [W06 #224](https://github.com/carloshm91/kuberich/issues/224) | Consolidate user guides into a small task-based set with generated reference | [W04 #222](https://github.com/carloshm91/kuberich/issues/222) |
| [W07 #225](https://github.com/carloshm91/kuberich/issues/225) | Replace architecture.md with a short overview and ADRs | [W04 #222](https://github.com/carloshm91/kuberich/issues/222) |
| [W08 #226](https://github.com/carloshm91/kuberich/issues/226) | Move acceptance evidence and history out of the documentation tree | [W04 #222](https://github.com/carloshm91/kuberich/issues/222) |
| [W09 #227](https://github.com/carloshm91/kuberich/issues/227) | Rewrite the changelog and release notes for users | [W04 #222](https://github.com/carloshm91/kuberich/issues/222) |
| [W10 #228](https://github.com/carloshm91/kuberich/issues/228) | Reduce AGENTS.md, CONTRIBUTING.md and issue templates to current essentials | [W04 #222](https://github.com/carloshm91/kuberich/issues/222) |
| [W11 #229](https://github.com/carloshm91/kuberich/issues/229) | Add documentation quality checks: prose lint, links and page budgets | [W04 #222](https://github.com/carloshm91/kuberich/issues/222) |
| [D16 #230](https://github.com/carloshm91/kuberich/issues/230) | Qualify the foundations checkpoint | [Q08 #211](https://github.com/carloshm91/kuberich/issues/211), [Q09 #210](https://github.com/carloshm91/kuberich/issues/210), [Q10 #209](https://github.com/carloshm91/kuberich/issues/209), [Q11 #212](https://github.com/carloshm91/kuberich/issues/212), [Q12 #213](https://github.com/carloshm91/kuberich/issues/213), [Q13 #214](https://github.com/carloshm91/kuberich/issues/214), [Q14 #215](https://github.com/carloshm91/kuberich/issues/215), [Q15 #216](https://github.com/carloshm91/kuberich/issues/216), [Q16 #217](https://github.com/carloshm91/kuberich/issues/217), [Q17 #218](https://github.com/carloshm91/kuberich/issues/218), [Q18 #219](https://github.com/carloshm91/kuberich/issues/219), [Q19 #220](https://github.com/carloshm91/kuberich/issues/220), [D15 #221](https://github.com/carloshm91/kuberich/issues/221), [W04 #222](https://github.com/carloshm91/kuberich/issues/222), [W05 #223](https://github.com/carloshm91/kuberich/issues/223), [W06 #224](https://github.com/carloshm91/kuberich/issues/224), [W07 #225](https://github.com/carloshm91/kuberich/issues/225), [W08 #226](https://github.com/carloshm91/kuberich/issues/226), [W09 #227](https://github.com/carloshm91/kuberich/issues/227), [W10 #228](https://github.com/carloshm91/kuberich/issues/228), [W11 #229](https://github.com/carloshm91/kuberich/issues/229), [D07 #65](https://github.com/carloshm91/kuberich/issues/65) |

Dependency refresh [#270](https://github.com/carloshm91/kuberich/issues/270) is also
a required extra for this phase and its qualifier. It covers the development,
standalone-build and deployment-tool lockfiles.

## v0.4.0

Observability: metrics-server and Prometheus metrics with terminal charts, cluster overview, relationships, RBAC analysis, diagnostics, sanitized exports, curated views for every remaining Lens resource family and container environment inspection. Requires its qualifier and every earlier phase.

| Issue | Task | Blocked by |
| --- | --- | --- |
| [O01 #68](https://github.com/carloshm91/kuberich/issues/68) | Collect and present resource metrics with explicit availability | [C04 #25](https://github.com/carloshm91/kuberich/issues/25), [B05 #41](https://github.com/carloshm91/kuberich/issues/41) |
| [O02 #69](https://github.com/carloshm91/kuberich/issues/69) | Build a cluster pulse overview and CPU/memory drill-downs | [O01 #68](https://github.com/carloshm91/kuberich/issues/68), [B05 #41](https://github.com/carloshm91/kuberich/issues/41) |
| [O03 #70](https://github.com/carloshm91/kuberich/issues/70) | Build XRay-style relationships and resource references | [B05 #41](https://github.com/carloshm91/kuberich/issues/41), [C05 #52](https://github.com/carloshm91/kuberich/issues/52), [U06 #64](https://github.com/carloshm91/kuberich/issues/64) |
| [O04 #71](https://github.com/carloshm91/kuberich/issues/71) | Explain effective RBAC and subject/resource permissions | [C02 #23](https://github.com/carloshm91/kuberich/issues/23), [M01 #43](https://github.com/carloshm91/kuberich/issues/43) |
| [O05 #72](https://github.com/carloshm91/kuberich/issues/72) | Integrate cluster diagnostics and Popeye-style reports | [S06 #54](https://github.com/carloshm91/kuberich/issues/54), [O03 #70](https://github.com/carloshm91/kuberich/issues/70), [O04 #71](https://github.com/carloshm91/kuberich/issues/71) |
| [O06 #73](https://github.com/carloshm91/kuberich/issues/73) | Save, browse and share redacted resource and diagnostic exports | [O05 #72](https://github.com/carloshm91/kuberich/issues/72), [M05 #55](https://github.com/carloshm91/kuberich/issues/55) |
| [O07 #74](https://github.com/carloshm91/kuberich/issues/74) | Inspect container environments, images and configuration sources | [O03 #70](https://github.com/carloshm91/kuberich/issues/70), [M05 #55](https://github.com/carloshm91/kuberich/issues/55), [U04 #59](https://github.com/carloshm91/kuberich/issues/59) |
| [O08 #231](https://github.com/carloshm91/kuberich/issues/231) | Show Prometheus-compatible historical metrics with terminal charts | [O01 #68](https://github.com/carloshm91/kuberich/issues/68) |
| [O09 #232](https://github.com/carloshm91/kuberich/issues/232) | Add curated views for every remaining Lens resource family | None |
| [D08 #75](https://github.com/carloshm91/kuberich/issues/75) | Qualify the observability engineering checkpoint | [O01 #68](https://github.com/carloshm91/kuberich/issues/68), [O02 #69](https://github.com/carloshm91/kuberich/issues/69), [O03 #70](https://github.com/carloshm91/kuberich/issues/70), [O04 #71](https://github.com/carloshm91/kuberich/issues/71), [O05 #72](https://github.com/carloshm91/kuberich/issues/72), [O06 #73](https://github.com/carloshm91/kuberich/issues/73), [O07 #74](https://github.com/carloshm91/kuberich/issues/74), [O08 #231](https://github.com/carloshm91/kuberich/issues/231), [O09 #232](https://github.com/carloshm91/kuberich/issues/232), [D07 #65](https://github.com/carloshm91/kuberich/issues/65), [D16 #230](https://github.com/carloshm91/kuberich/issues/230) |

## v0.5.0

Operations: full Helm lifecycle, local manifests and Kustomize, resource templates, node shell, cordon/drain, ephemeral debugging, HTTP benchmarks and policy/quota/admission exploration. Requires its qualifier and every earlier phase.

| Issue | Task | Blocked by |
| --- | --- | --- |
| [M06 #66](https://github.com/carloshm91/kuberich/issues/66) | Browse, inspect and roll back Helm releases | [M01 #43](https://github.com/carloshm91/kuberich/issues/43), [C08 #47](https://github.com/carloshm91/kuberich/issues/47), [B05 #41](https://github.com/carloshm91/kuberich/issues/41) |
| [M07 #67](https://github.com/carloshm91/kuberich/issues/67) | Browse local manifests and apply/delete with Kustomize awareness | [M02 #44](https://github.com/carloshm91/kuberich/issues/44), [C08 #47](https://github.com/carloshm91/kuberich/issues/47) |
| [A01 #76](https://github.com/carloshm91/kuberich/issues/76) | Open controlled node-shell diagnostic sessions | [S04 #32](https://github.com/carloshm91/kuberich/issues/32), [M01 #43](https://github.com/carloshm91/kuberich/issues/43), [O04 #71](https://github.com/carloshm91/kuberich/issues/71) |
| [A02 #77](https://github.com/carloshm91/kuberich/issues/77) | Cordon, drain and uncordon nodes with disruption awareness | [A01 #76](https://github.com/carloshm91/kuberich/issues/76), [M01 #43](https://github.com/carloshm91/kuberich/issues/43) |
| [A03 #78](https://github.com/carloshm91/kuberich/issues/78) | Launch ephemeral container debugging sessions | [S04 #32](https://github.com/carloshm91/kuberich/issues/32), [M01 #43](https://github.com/carloshm91/kuberich/issues/43), [B05 #41](https://github.com/carloshm91/kuberich/issues/41) |
| [A04 #79](https://github.com/carloshm91/kuberich/issues/79) | Run bounded HTTP benchmarks through selected services and forwards | [S08 #62](https://github.com/carloshm91/kuberich/issues/62), [O01 #68](https://github.com/carloshm91/kuberich/issues/68) |
| [A05 #80](https://github.com/carloshm91/kuberich/issues/80) | Explore policy, quota, admission and scheduling resources | [B06 #53](https://github.com/carloshm91/kuberich/issues/53), [O04 #71](https://github.com/carloshm91/kuberich/issues/71) |
| [Q07 #81](https://github.com/carloshm91/kuberich/issues/81) | Investigate publicly documented K9sAlpha additions (closed: not planned) | [F00 #13](https://github.com/carloshm91/kuberich/issues/13) |
| [M09 #233](https://github.com/carloshm91/kuberich/issues/233) | Install, upgrade and uninstall Helm charts from repositories | [M06 #66](https://github.com/carloshm91/kuberich/issues/66) |
| [M10 #234](https://github.com/carloshm91/kuberich/issues/234) | Create resources from templates with server-side dry run | None |
| [D09 #82](https://github.com/carloshm91/kuberich/issues/82) | Qualify the advanced operations engineering checkpoint | [M06 #66](https://github.com/carloshm91/kuberich/issues/66), [M07 #67](https://github.com/carloshm91/kuberich/issues/67), [M09 #233](https://github.com/carloshm91/kuberich/issues/233), [M10 #234](https://github.com/carloshm91/kuberich/issues/234), [A01 #76](https://github.com/carloshm91/kuberich/issues/76), [A02 #77](https://github.com/carloshm91/kuberich/issues/77), [A03 #78](https://github.com/carloshm91/kuberich/issues/78), [A04 #79](https://github.com/carloshm91/kuberich/issues/79), [A05 #80](https://github.com/carloshm91/kuberich/issues/80), [D08 #75](https://github.com/carloshm91/kuberich/issues/75) |

## v0.6.0

Multi-cluster workspace: cluster catalog and pinned hotbar, multi-cluster views, context-scoped local terminals, cloud cluster discovery, curated CRD and GitOps packs, change timeline and diffs, native exec/port-forward transport. Requires its qualifier and every earlier phase.

| Issue | Task | Blocked by |
| --- | --- | --- |
| [L01 #235](https://github.com/carloshm91/kuberich/issues/235) | Build a cluster catalog with a pinned hotbar | None |
| [L02 #236](https://github.com/carloshm91/kuberich/issues/236) | Open context-scoped local terminal tabs | None |
| [L03 #237](https://github.com/carloshm91/kuberich/issues/237) | Show one resource kind across multiple clusters | [L01 #235](https://github.com/carloshm91/kuberich/issues/235) |
| [L04 #238](https://github.com/carloshm91/kuberich/issues/238) | Discover EKS, AKS and GKE clusters from local cloud CLIs | [L01 #235](https://github.com/carloshm91/kuberich/issues/235) |
| [L05 #239](https://github.com/carloshm91/kuberich/issues/239) | Ship curated resource packs for GitOps and popular CRDs | None |
| [L06 #240](https://github.com/carloshm91/kuberich/issues/240) | Add a resource change timeline and revision diffs | None |
| [L07 #241](https://github.com/carloshm91/kuberich/issues/241) | Implement native exec, attach, port-forward and copy over WebSocket | None |
| [D17 #242](https://github.com/carloshm91/kuberich/issues/242) | Qualify the multi-cluster workspace checkpoint | [L01 #235](https://github.com/carloshm91/kuberich/issues/235), [L02 #236](https://github.com/carloshm91/kuberich/issues/236), [L03 #237](https://github.com/carloshm91/kuberich/issues/237), [L04 #238](https://github.com/carloshm91/kuberich/issues/238), [L05 #239](https://github.com/carloshm91/kuberich/issues/239), [L06 #240](https://github.com/carloshm91/kuberich/issues/240), [L07 #241](https://github.com/carloshm91/kuberich/issues/241), [D09 #82](https://github.com/carloshm91/kuberich/issues/82) |

## v0.7.0

Ecosystem and intelligence: stable in-process Python extension API, extension index, security center, read-only MCP server and opt-in bring-your-own AI assistant. Requires its qualifier and every earlier phase.

| Issue | Task | Blocked by |
| --- | --- | --- |
| [X01 #243](https://github.com/carloshm91/kuberich/issues/243) | Provide a stable in-process Python extension API | [Q08 #211](https://github.com/carloshm91/kuberich/issues/211) |
| [X02 #244](https://github.com/carloshm91/kuberich/issues/244) | Add an extension index with pinned, verified installation | [X01 #243](https://github.com/carloshm91/kuberich/issues/243) |
| [X03 #245](https://github.com/carloshm91/kuberich/issues/245) | Build a security center for image, configuration and RBAC risk | [O04 #71](https://github.com/carloshm91/kuberich/issues/71), [O05 #72](https://github.com/carloshm91/kuberich/issues/72), [O07 #74](https://github.com/carloshm91/kuberich/issues/74) |
| [X04 #246](https://github.com/carloshm91/kuberich/issues/246) | Expose a read-only MCP server for the active session | None |
| [X05 #247](https://github.com/carloshm91/kuberich/issues/247) | Add an opt-in bring-your-own AI assistant panel | [X04 #246](https://github.com/carloshm91/kuberich/issues/246) |
| [D18 #248](https://github.com/carloshm91/kuberich/issues/248) | Qualify the ecosystem and intelligence checkpoint | [X01 #243](https://github.com/carloshm91/kuberich/issues/243), [X02 #244](https://github.com/carloshm91/kuberich/issues/244), [X03 #245](https://github.com/carloshm91/kuberich/issues/245), [X04 #246](https://github.com/carloshm91/kuberich/issues/246), [X05 #247](https://github.com/carloshm91/kuberich/issues/247), [D17 #242](https://github.com/carloshm91/kuberich/issues/242) |

## v0.8.0

Platforms and accessibility: Windows terminal and packaged installation, shell completion, OCI image, distribution recipes, advanced embedded-terminal input and accessibility. Requires its qualifier and every earlier phase.

| Issue | Task | Blocked by |
| --- | --- | --- |
| [D12 #83](https://github.com/carloshm91/kuberich/issues/83) | Qualify Windows terminal operation and packaged installation | [D05 #49](https://github.com/carloshm91/kuberich/issues/49), [S07 #48](https://github.com/carloshm91/kuberich/issues/48), [U05 #60](https://github.com/carloshm91/kuberich/issues/60), [Q02 #33](https://github.com/carloshm91/kuberich/issues/33) |
| [D13 #84](https://github.com/carloshm91/kuberich/issues/84) | Provide shell completion and an OCI terminal container image | [F05 #19](https://github.com/carloshm91/kuberich/issues/19), [D05 #49](https://github.com/carloshm91/kuberich/issues/49) |
| [D14 #85](https://github.com/carloshm91/kuberich/issues/85) | Prepare Linux/BSD/macOS package recipes and channel ownership | [D05 #49](https://github.com/carloshm91/kuberich/issues/49), [D03 #37](https://github.com/carloshm91/kuberich/issues/37) |
| [U07 #249](https://github.com/carloshm91/kuberich/issues/249) | Make the interface accessible | None |
| [D11 #86](https://github.com/carloshm91/kuberich/issues/86) | Qualify the extended platform engineering checkpoint | [D12 #83](https://github.com/carloshm91/kuberich/issues/83), [D13 #84](https://github.com/carloshm91/kuberich/issues/84), [D14 #85](https://github.com/carloshm91/kuberich/issues/85), [U07 #249](https://github.com/carloshm91/kuberich/issues/249), [D09 #82](https://github.com/carloshm91/kuberich/issues/82), [D18 #248](https://github.com/carloshm91/kuberich/issues/248) |

## v0.9.0

Release candidate: configuration and extension API freeze, compatibility matrix, versioned documentation, K9s and Lens parity dry run and stabilization. Requires its qualifier and every earlier phase.

| Issue | Task | Blocked by |
| --- | --- | --- |
| [Q05 #87](https://github.com/carloshm91/kuberich/issues/87) | Qualify Kubernetes, credential, config and platform compatibility | [Q01 #38](https://github.com/carloshm91/kuberich/issues/38), [C05 #52](https://github.com/carloshm91/kuberich/issues/52), [U05 #60](https://github.com/carloshm91/kuberich/issues/60), [Q03 #50](https://github.com/carloshm91/kuberich/issues/50), [D11 #86](https://github.com/carloshm91/kuberich/issues/86) |
| [W02 #90](https://github.com/carloshm91/kuberich/issues/90) | Build versioned documentation on the existing site generator | [D10 #89](https://github.com/carloshm91/kuberich/issues/89), [W01 #39](https://github.com/carloshm91/kuberich/issues/39), [W04 #222](https://github.com/carloshm91/kuberich/issues/222), [W05 #223](https://github.com/carloshm91/kuberich/issues/223), [W06 #224](https://github.com/carloshm91/kuberich/issues/224), [W07 #225](https://github.com/carloshm91/kuberich/issues/225), [W08 #226](https://github.com/carloshm91/kuberich/issues/226), [W09 #227](https://github.com/carloshm91/kuberich/issues/227), [W10 #228](https://github.com/carloshm91/kuberich/issues/228), [W11 #229](https://github.com/carloshm91/kuberich/issues/229) |
| [W03 #91](https://github.com/carloshm91/kuberich/issues/91) | Deploy and maintain the versioned documentation website | [W02 #90](https://github.com/carloshm91/kuberich/issues/90) |
| [Q20 #250](https://github.com/carloshm91/kuberich/issues/250) | Freeze configuration schema v1 with migrations and a deprecation policy | None |
| [Q21 #251](https://github.com/carloshm91/kuberich/issues/251) | Freeze the extension API and plugin manifest with compatibility tests | [X01 #243](https://github.com/carloshm91/kuberich/issues/243) |
| [Q22 #252](https://github.com/carloshm91/kuberich/issues/252) | Run a K9s and Lens parity dry run and file every gap | None |
| [D19 #253](https://github.com/carloshm91/kuberich/issues/253) | Qualify the 1.0 release candidate | [Q20 #250](https://github.com/carloshm91/kuberich/issues/250), [Q21 #251](https://github.com/carloshm91/kuberich/issues/251), [Q22 #252](https://github.com/carloshm91/kuberich/issues/252), [Q05 #87](https://github.com/carloshm91/kuberich/issues/87), [W02 #90](https://github.com/carloshm91/kuberich/issues/90), [W03 #91](https://github.com/carloshm91/kuberich/issues/91), [D11 #86](https://github.com/carloshm91/kuberich/issues/86) |

## v1.0.0

Stable release: every phase complete, including Windows; stable configuration and extension contracts; evidence-backed Kubernetes and platform compatibility; audited capability parity with K9s and Lens (open source and publicly documented Pro features), with every difference documented.

| Issue | Task | Blocked by |
| --- | --- | --- |
| [Q06 #88](https://github.com/carloshm91/kuberich/issues/88) | Audit complete feature parity and resolve every remaining gap | [Q05 #87](https://github.com/carloshm91/kuberich/issues/87), [D11 #86](https://github.com/carloshm91/kuberich/issues/86), [Q22 #252](https://github.com/carloshm91/kuberich/issues/252), [D19 #253](https://github.com/carloshm91/kuberich/issues/253) |

Each task has scope, acceptance criteria and verification in its issue and
[backlog.json](backlog.json). Qualification dependencies remain explicit in that
graph; phase readiness adds cumulative gates and tracked launch/feedback extras.
Native parent/dependency links and epic checklists mirror the reviewed scope.

The initial F00 completion is repository preparation, not an application release.
The first product task is [F01 #14](https://github.com/carloshm91/kuberich/issues/14).

See [coverage policy](quality.md), [release procedure](releases.md), and
[capability audit](k9s-parity.md).

## Preview feedback follow-up

[#115](https://github.com/carloshm91/kuberich/issues/115) corrects arrow/Enter
command completion and adds pod → container → log Enter navigation in v0.0.1.
It is a focused follow-up to B03/B04/S02, before the next exec checkpoint.
GitHub records its current status and measured acceptance evidence.

## Brand and public launch preparation

[#149](https://github.com/carloshm91/kuberich/issues/149) records the independent
KubeRich name review and the focused private repository/package/CLI/configuration
migration. The canonical checkout command is `kuberich`; the previous `kubetrol`
console alias and preference compatibility are documented in [configuration](configuration.md).
[#150](https://github.com/carloshm91/kuberich/issues/150) prepares the initial
landing page and documentation before public launch. Both provide local launch
preparation evidence; final public-launch requirements belong to #89, and expanded versioned documentation remains #90/#91. GitHub tracks
their acceptance criteria and current status. Neither ticket authorizes visibility,
domain/DNS, hosting publication, ownership transfer or public distribution changes.

## History

On 2026-10-09 the maintainer explicitly requested publishing the development
landing and initial docs before the product release. [#166](https://github.com/carloshm91/kuberich/issues/166)
owns a protected manual GitHub Actions deployment and actual HTTPS verification
on two Cloudflare Pages provider hosts, temporarily preceding the committed B06
#53 foundation. Custom domains/DNS and `www` are deferred; application artifacts,
tags and each public candidate's website regeneration/qualification remain #89. Expanded and
versioned documentation remains #90/#91. This dated exception supersedes only
the earlier prohibition on independently publishing the development website.

The dated changes below explain completed preview work. They do not supersede
the current phased execution and publication policy above.

After C01 and its preview correction (#102), prioritize the path to the first
pod view: **C02 → C03 → C04 → B02 → B03**. This delivery order takes precedence
over the remaining v0.0.1 table order below, preserves every prerequisite, and
keeps one implementation issue in progress. The maintainer authorized advancing
toward visible pods and Tab completion during the first context trial.
Advanced F05 connection overrides and cloud qualification remain open; resource
commands, refresh and effectful-operation integration stay with their owners.
C02 delivers discovery and complete resource snapshots; B02 delivers the visible
live table. Do not label namespace selection as an implemented pod browser.

The C04 trial exposed misleading idle-watch retries and preview text. Focused
[correction #107](https://github.com/carloshm91/kuberich/issues/107) precedes B02;
it repairs renewal/status behavior and does not supply table rows.

After B03/B04/S02 and preview feedback #115, continue **S03 → S04** for the
native container shell checkpoint. S03's F05 dependency means its already-merged
stage-1 shared command/read-only policy, not the still-open advanced connection
overrides. GitHub #31 records this readiness clarification; F05 stays open.

The maintainer's shell-screen feedback [#119](https://github.com/carloshm91/kuberich/issues/119)
adds a focused clean-screen/target-heading correction after S04 and before
resuming the remaining F05 connection options. It preserved native handoff.

The clarified feedback [#121](https://github.com/carloshm91/kuberich/issues/121)
now prioritizes a real embedded shell inside Textual. It supersedes the earlier
initial-scope terminal-emulator exclusion and precedes the remaining F05 work.
S03/S04 are its closed prerequisites; Q02 retains platform/terminal qualification.
Additional feedback tasks [#123](https://github.com/carloshm91/kuberich/issues/123)
(v0.1.0 bounded terminal history/search/copy) and
[#124](https://github.com/carloshm91/kuberich/issues/124)
(mouse/keyboard protocol compatibility, now v0.8.0) follow it; they are outside the
original planning inventory.

The maintainer's screenshot feedback prioritizes
[#125](https://github.com/carloshm91/kuberich/issues/125) after the embedded shell:
shared K9s-inspired workspace, top inputs, default `k9s` theme, Escape trails and
a live namespace table. It precedes remaining F05 work and is outside the original
inventory. U01/B07 retain broader theme/update/navigation contracts; O01/O02
retain metrics and cluster overview.

The next maintainer preview correction
[#127](https://github.com/carloshm91/kuberich/issues/127) prioritizes stable frame/
header geometry and a dedicated inline command suggestion bar without a dropdown.
It follows #125 before remaining F05 work; the previous temporary dropdown
preference in B07 is superseded. Wider B07 requirements remain open.

The next maintainer feedback [#129](https://github.com/carloshm91/kuberich/issues/129)
prioritizes a bordered command bar, local contexts as a normal workspace table,
and captured container status/specification columns before remaining F05 work.
It is independently unblocked after #127. Live container refresh, metrics and
ephemeral debugging remain separate work; the release process remains #36/#40.

Maintainer refinement [#132](https://github.com/carloshm91/kuberich/issues/132)
prioritizes an original responsive `ktrol` header logo after #19, before provider
qualification. It is independently unblocked; the CLI remains `kuberich` and
the broader U01 theme/update-notice requirements stay separate.
