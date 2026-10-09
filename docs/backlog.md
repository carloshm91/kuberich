# Backlog and implementation order

[Open the GitHub project](https://github.com/users/carloshm91/projects/3).

The plan has **12 epics and 79 actionable tasks**.
GitHub issues are the live status source; this file is the planning map.

Work on one implementation task at a time. Follow the feature-first execution
policy below, choosing the first unblocked task in the earliest unfinished
feature milestone. The 0.x labels group engineering scope and do not schedule publication. F00 prepares the repository;
F01 starts the product. B01 is deliberately early so the maintainer can try the
first terminal window before the full first release. See [preview checkpoints](first-preview.md).

F05 has a local launch-contract checkpoint before C01, with precise unavailable
errors for absent behaviors. Its connection integration phase requires C01; keep
F05 open while that work is pending. This prevents closing a connection contract
from parser tests alone. See [current CLI behavior](k9s-cli.md).

## Current maintainer priority

#155 opened the Apache-2.0 source; the separate GitHub project stays private.
#157 / #158 restored required native verification, and #46 / #159 delivered
resource operations with all required checks passing. #154 reconciles the first
public product release at **1.0.0**; development metadata remains `0.0.1.dev0`.

1. Finish product features, continuing after #154 with C08 #47, S07 #48, then
   the unblocked feature tasks in `delivery.feature_order` in backlog.json.
   Include the remaining embedded keyboard/mouse refinement #124. Per-feature
   behavioral, independent coverage, PTY, packaging and owned-cluster checks
   continue; no intermediate manual maintainer trial is required.
2. Complete dedicated final qualification in `delivery.final_qualification_order`:
   D05 standalone builds before D12/D13/D14 Windows/completion/container/recipe
   qualification, Q03 performance, all six engineering checkpoints, Q05
   compatibility and Q06 capability audit. Preserve every real dependency.
   Deferral does not count as completion; unavailable native/provider evidence
   remains recorded and incomplete under the agreed certification scope.
3. D10 #89 owns first-product publication, protected main/environments,
   PyPI/TestPyPI ownership/OIDC, public tap/registries, immutable artifacts/tags,
   public installed-channel trials, and #150's exact-candidate initial site.
   Final-candidate website/docs verification follows product and final qualification;
   deploy approved reviewed bytes from GitHub Actions to Cloudflare Pages.
4. Expanded/versioned MkDocs and its deployment remain later W02 #90 / W03 #91.

On 2026-10-09 the maintainer explicitly authorized independent Astra website work
alongside the single active product issue. [#162](https://github.com/carloshm91/kuberich/issues/162)
refines the local landing/docs and generated references in an isolated branch.
This narrow preparation exception supersedes the earlier website sequence; it
adds no deployment or DNS authorization. #162 is a tracked readiness prerequisite
for #89 through `delivery.publication_extra_issues`. The product issue sequence,
full required checks and separately approved final publication remain unchanged.

D04 #40, D06 #51, D07 #65, D08 #75, D09 #82 and D11 #86 are engineering
qualification checkpoints. Their local installs, complete platform matrix,
security, artifact and terminal duties remain. They publish no 0.x package,
tag, release or site, and are not prerequisites for moving to the next feature.
Their dependencies still feed #89, so first publication cannot bypass them.

Identity migration #149 and local initial site preparation #150 are delivered;
#89 owns their final-candidate installation/site/publication requirements.
Continuous delivery now uses the configured hosted checks on the public source
repository, in addition to measured local verification. The old private-account
quota exception applies only while its recorded blocking condition exists.
Provider trials remain the maintainer's later opt-in certification in Q05 #87;
local/owned-cluster evidence never establishes real EKS/AKS/GKE certification.

## Historical delivery refinements

The dated changes below explain completed preview work. They do not supersede
the current feature-first execution and first-product publication policy above.

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
(v0.2.0 mouse/keyboard protocol compatibility) follow it; they are outside the
original 79-task planning inventory.

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

## Epics

| Issue | Outcome | Completion milestone |
| --- | --- | --- |
| [E01 #1](https://github.com/carloshm91/kuberich/issues/1) | Project foundation and enforced quality | v0.0.1 |
| [E02 #2](https://github.com/carloshm91/kuberich/issues/2) | Kubernetes sessions, discovery, and live state | v0.2.0 |
| [E03 #3](https://github.com/carloshm91/kuberich/issues/3) | Terminal resource browsing and navigation | v0.2.0 |
| [E04 #4](https://github.com/carloshm91/kuberich/issues/4) | Logs and interactive sessions | v0.2.0 |
| [E05 #5](https://github.com/carloshm91/kuberich/issues/5) | Safe workload and configuration operations | v0.3.0 |
| [E06 #6](https://github.com/carloshm91/kuberich/issues/6) | Themes, configuration, and plugins | v0.2.0 |
| [E07 #7](https://github.com/carloshm91/kuberich/issues/7) | Observability and troubleshooting | v0.3.0 |
| [E08 #8](https://github.com/carloshm91/kuberich/issues/8) | Advanced cluster operations | v0.4.0 |
| [E09 #9](https://github.com/carloshm91/kuberich/issues/9) | Packaging, installation, and release delivery | v1.0.0 |
| [E10 #10](https://github.com/carloshm91/kuberich/issues/10) | Integration, performance, and compatibility qualification | v1.0.0 |
| [E11 #11](https://github.com/carloshm91/kuberich/issues/11) | User documentation and contribution experience | Later: documentation website |
| [E12 #12](https://github.com/carloshm91/kuberich/issues/12) | Extended platforms and ecosystem delivery | v0.5.0 |

## v0.0.1

Core terminal engineering checkpoint: live pods, navigation, details, logs, exec and qualified local packages. Public PyPI/Homebrew activation belongs to #89.

| Issue | Task | Blocked by |
| --- | --- | --- |
| [F00 #13](https://github.com/carloshm91/kuberich/issues/13) | Prepare repository governance and the complete implementation backlog | None |
| [F01 #14](https://github.com/carloshm91/kuberich/issues/14) | Bootstrap the installable Python package and developer toolchain | [F00 #13](https://github.com/carloshm91/kuberich/issues/13) |
| [F02 #15](https://github.com/carloshm91/kuberich/issues/15) | Enforce independent coverage and required application CI gates | [F01 #14](https://github.com/carloshm91/kuberich/issues/14) |
| [F03 #16](https://github.com/carloshm91/kuberich/issues/16) | Implement validated configuration and sanitized diagnostics | [F02 #15](https://github.com/carloshm91/kuberich/issues/15) |
| [B01 #17](https://github.com/carloshm91/kuberich/issues/17) | Build the Textual application shell and responsive layout | [F02 #15](https://github.com/carloshm91/kuberich/issues/15), [F03 #16](https://github.com/carloshm91/kuberich/issues/16) |
| [F04 #18](https://github.com/carloshm91/kuberich/issues/18) | Define and test Kubernetes, plugin, and terminal trust boundaries | [F02 #15](https://github.com/carloshm91/kuberich/issues/15) |
| [F05 #19](https://github.com/carloshm91/kuberich/issues/19) | Implement the complete launch CLI and diagnostic command contract | [F03 #16](https://github.com/carloshm91/kuberich/issues/16), [F04 #18](https://github.com/carloshm91/kuberich/issues/18), [C01 #20](https://github.com/carloshm91/kuberich/issues/20) |
| [C01 #20](https://github.com/carloshm91/kuberich/issues/20) | Create isolated kubeconfig and context sessions | [F03 #16](https://github.com/carloshm91/kuberich/issues/16), [F04 #18](https://github.com/carloshm91/kuberich/issues/18) |
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

Standard resource families, safe workload mutations, editing, port forwarding, standalone executables, and performance qualification.

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

## v0.2.0

Generic CRDs, multi-container logs, themes, configurable navigation/views, and external command plugins.

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

Resource metrics, cluster overview, relationships, RBAC analysis, guided troubleshooting, and sanitized exports.

| Issue | Task | Blocked by |
| --- | --- | --- |
| [M06 #66](https://github.com/carloshm91/kuberich/issues/66) | Browse, inspect and roll back Helm releases | [M01 #43](https://github.com/carloshm91/kuberich/issues/43), [C08 #47](https://github.com/carloshm91/kuberich/issues/47), [B05 #41](https://github.com/carloshm91/kuberich/issues/41) |
| [M07 #67](https://github.com/carloshm91/kuberich/issues/67) | Browse local manifests and apply/delete with Kustomize awareness | [M02 #44](https://github.com/carloshm91/kuberich/issues/44), [C08 #47](https://github.com/carloshm91/kuberich/issues/47) |
| [O01 #68](https://github.com/carloshm91/kuberich/issues/68) | Collect and present resource metrics with explicit availability | [C04 #25](https://github.com/carloshm91/kuberich/issues/25), [B05 #41](https://github.com/carloshm91/kuberich/issues/41) |
| [O02 #69](https://github.com/carloshm91/kuberich/issues/69) | Build a cluster pulse overview and CPU/memory drill-downs | [O01 #68](https://github.com/carloshm91/kuberich/issues/68), [B05 #41](https://github.com/carloshm91/kuberich/issues/41) |
| [O03 #70](https://github.com/carloshm91/kuberich/issues/70) | Build XRay-style relationships and resource references | [B05 #41](https://github.com/carloshm91/kuberich/issues/41), [C05 #52](https://github.com/carloshm91/kuberich/issues/52), [U06 #64](https://github.com/carloshm91/kuberich/issues/64) |
| [O04 #71](https://github.com/carloshm91/kuberich/issues/71) | Explain effective RBAC and subject/resource permissions | [C02 #23](https://github.com/carloshm91/kuberich/issues/23), [M01 #43](https://github.com/carloshm91/kuberich/issues/43) |
| [O05 #72](https://github.com/carloshm91/kuberich/issues/72) | Integrate cluster diagnostics and Popeye-style reports | [S06 #54](https://github.com/carloshm91/kuberich/issues/54), [O03 #70](https://github.com/carloshm91/kuberich/issues/70), [O04 #71](https://github.com/carloshm91/kuberich/issues/71) |
| [O06 #73](https://github.com/carloshm91/kuberich/issues/73) | Save, browse and share redacted resource and diagnostic exports | [O05 #72](https://github.com/carloshm91/kuberich/issues/72), [M05 #55](https://github.com/carloshm91/kuberich/issues/55) |
| [O07 #74](https://github.com/carloshm91/kuberich/issues/74) | Inspect container environments and image vulnerabilities | [O03 #70](https://github.com/carloshm91/kuberich/issues/70), [M05 #55](https://github.com/carloshm91/kuberich/issues/55), [U04 #59](https://github.com/carloshm91/kuberich/issues/59) |
| [D08 #75](https://github.com/carloshm91/kuberich/issues/75) | Qualify the observability engineering checkpoint | [M06 #66](https://github.com/carloshm91/kuberich/issues/66), [M07 #67](https://github.com/carloshm91/kuberich/issues/67), [O01 #68](https://github.com/carloshm91/kuberich/issues/68), [O02 #69](https://github.com/carloshm91/kuberich/issues/69), [O03 #70](https://github.com/carloshm91/kuberich/issues/70), [O04 #71](https://github.com/carloshm91/kuberich/issues/71), [O05 #72](https://github.com/carloshm91/kuberich/issues/72), [O06 #73](https://github.com/carloshm91/kuberich/issues/73), [O07 #74](https://github.com/carloshm91/kuberich/issues/74), [D07 #65](https://github.com/carloshm91/kuberich/issues/65) |

## v0.4.0

Node operations, ephemeral debugging, HTTP benchmarks, and policy/quota exploration.

| Issue | Task | Blocked by |
| --- | --- | --- |
| [A01 #76](https://github.com/carloshm91/kuberich/issues/76) | Open controlled node-shell diagnostic sessions | [S04 #32](https://github.com/carloshm91/kuberich/issues/32), [M01 #43](https://github.com/carloshm91/kuberich/issues/43), [O04 #71](https://github.com/carloshm91/kuberich/issues/71) |
| [A02 #77](https://github.com/carloshm91/kuberich/issues/77) | Cordon, drain and uncordon nodes with disruption awareness | [A01 #76](https://github.com/carloshm91/kuberich/issues/76), [M01 #43](https://github.com/carloshm91/kuberich/issues/43) |
| [A03 #78](https://github.com/carloshm91/kuberich/issues/78) | Launch ephemeral container debugging sessions | [S04 #32](https://github.com/carloshm91/kuberich/issues/32), [M01 #43](https://github.com/carloshm91/kuberich/issues/43), [B05 #41](https://github.com/carloshm91/kuberich/issues/41) |
| [A04 #79](https://github.com/carloshm91/kuberich/issues/79) | Run bounded HTTP benchmarks through selected services and forwards | [S08 #62](https://github.com/carloshm91/kuberich/issues/62), [O01 #68](https://github.com/carloshm91/kuberich/issues/68) |
| [A05 #80](https://github.com/carloshm91/kuberich/issues/80) | Explore policy, quota, admission and scheduling resources | [B06 #53](https://github.com/carloshm91/kuberich/issues/53), [O04 #71](https://github.com/carloshm91/kuberich/issues/71) |
| [Q07 #81](https://github.com/carloshm91/kuberich/issues/81) | Investigate publicly documented K9sAlpha additions | [F00 #13](https://github.com/carloshm91/kuberich/issues/13) |
| [D09 #82](https://github.com/carloshm91/kuberich/issues/82) | Qualify the advanced operations engineering checkpoint | [A01 #76](https://github.com/carloshm91/kuberich/issues/76), [A02 #77](https://github.com/carloshm91/kuberich/issues/77), [A03 #78](https://github.com/carloshm91/kuberich/issues/78), [A04 #79](https://github.com/carloshm91/kuberich/issues/79), [A05 #80](https://github.com/carloshm91/kuberich/issues/80), [Q07 #81](https://github.com/carloshm91/kuberich/issues/81), [D08 #75](https://github.com/carloshm91/kuberich/issues/75) |

## v0.5.0

Extended delivery: Windows/PowerShell qualification, shell completion, OCI terminal image, and distribution-channel recipes.

| Issue | Task | Blocked by |
| --- | --- | --- |
| [D12 #83](https://github.com/carloshm91/kuberich/issues/83) | Qualify Windows terminal operation and packaged installation | [D05 #49](https://github.com/carloshm91/kuberich/issues/49), [S07 #48](https://github.com/carloshm91/kuberich/issues/48), [U05 #60](https://github.com/carloshm91/kuberich/issues/60), [Q02 #33](https://github.com/carloshm91/kuberich/issues/33) |
| [D13 #84](https://github.com/carloshm91/kuberich/issues/84) | Provide shell completion and an OCI terminal container image | [F05 #19](https://github.com/carloshm91/kuberich/issues/19), [D05 #49](https://github.com/carloshm91/kuberich/issues/49) |
| [D14 #85](https://github.com/carloshm91/kuberich/issues/85) | Prepare Linux/BSD/macOS package recipes and channel ownership | [D05 #49](https://github.com/carloshm91/kuberich/issues/49), [D03 #37](https://github.com/carloshm91/kuberich/issues/37) |
| [D11 #86](https://github.com/carloshm91/kuberich/issues/86) | Qualify the extended platform engineering checkpoint | [D12 #83](https://github.com/carloshm91/kuberich/issues/83), [D13 #84](https://github.com/carloshm91/kuberich/issues/84), [D14 #85](https://github.com/carloshm91/kuberich/issues/85), [D09 #82](https://github.com/carloshm91/kuberich/issues/82) |

## v1.0.0

Qualified compatibility, migration and support contracts, a complete capability audit, and a stable release.

| Issue | Task | Blocked by |
| --- | --- | --- |
| [Q05 #87](https://github.com/carloshm91/kuberich/issues/87) | Qualify Kubernetes, credential, config and platform compatibility | [Q01 #38](https://github.com/carloshm91/kuberich/issues/38), [C05 #52](https://github.com/carloshm91/kuberich/issues/52), [U05 #60](https://github.com/carloshm91/kuberich/issues/60), [Q03 #50](https://github.com/carloshm91/kuberich/issues/50), [D11 #86](https://github.com/carloshm91/kuberich/issues/86) |
| [Q06 #88](https://github.com/carloshm91/kuberich/issues/88) | Audit complete feature parity and resolve every remaining gap | [Q05 #87](https://github.com/carloshm91/kuberich/issues/87), [D11 #86](https://github.com/carloshm91/kuberich/issues/86) |
| [D10 #89](https://github.com/carloshm91/kuberich/issues/89) | Publish and verify the first qualified 1.0.0 product release | [Q05 #87](https://github.com/carloshm91/kuberich/issues/87), [Q06 #88](https://github.com/carloshm91/kuberich/issues/88), [D11 #86](https://github.com/carloshm91/kuberich/issues/86) |

## Later: documentation website

Expanded versioned MkDocs documentation after the first qualified 1.0.0 product, deployed through GitHub Actions to Cloudflare Pages.

| Issue | Task | Blocked by |
| --- | --- | --- |
| [W02 #90](https://github.com/carloshm91/kuberich/issues/90) | Build versioned MkDocs documentation after the usable product | [D10 #89](https://github.com/carloshm91/kuberich/issues/89), [W01 #39](https://github.com/carloshm91/kuberich/issues/39) |
| [W03 #91](https://github.com/carloshm91/kuberich/issues/91) | Deploy and maintain the versioned documentation website | [W02 #90](https://github.com/carloshm91/kuberich/issues/90) |

Each task has scope, acceptance criteria and verification in its issue and
[backlog.json](backlog.json). Each release gate depends on every task assigned
to that milestone, plus the previous release gate. Native parent/dependency links
and epic checklists mirror this graph.

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
