# Architecture decision records

Start with the [architecture overview](../architecture.md). Each numbered record
explains one implemented decision, its consequences, and the main source modules.
The migration records describe source snapshot
`625086db1a75aab10ec28fe4d6440f7fb1d32849`; they do not certify new measurements.

Sections labeled **Current implementation notes** describe later source behavior.
They do not change the archived rationale, its source identity, or historical
qualification. The separate foundations decisions below keep their own status.

| Number | Decision |
| --- | --- |
| 0001 | [Build the terminal application with Python and Textual](0001-python-terminal-stack.md) |
| 0002 | [Keep domain decisions independent of terminal and SDK types](0002-dependency-direction.md) |
| 0003 | [Use a separate explicit connection for each selected context](0003-explicit-context-sessions.md) |
| 0004 | [Preserve the configured credential identity when delegating tools](0004-credential-helpers-and-delegation.md) |
| 0005 | [Resolve API identity through discovery and version-pinned layouts](0005-discovery-and-printer-schemas.md) |
| 0006 | [Keep collection snapshots consistent and watch versions opaque](0006-list-watch-continuity.md) |
| 0007 | [Publish only observations belonging to the current view](0007-active-view-generations.md) |
| 0008 | [Own external commands through one explicit process service](0008-external-process-ownership.md) |
| 0009 | [Lease and restore the native terminal for explicit foreground tools](0009-native-terminal-handoff.md) |
| 0010 | [Keep pod shells inside an owned embedded terminal](0010-embedded-container-terminal.md) |
| 0011 | [Separate log delivery, retained history, and viewport following](0011-single-container-log-streams.md) |
| 0012 | [Admit aggregate log sources through controller identity](0012-controller-owned-aggregate-logs.md) |
| 0013 | [Bind each resource change to one reviewed conditional request](0013-reviewed-conditional-writes.md) |
| 0014 | [Validate copied trees privately before destination publication](0014-reviewed-file-transfers.md) |
| 0015 | [Manage forwards as connection-owned TCP sessions](0015-managed-tcp-forwards.md) |
| 0016 | [Load and execute only explicitly configured local plugins](0016-explicit-local-plugins.md) |
| 0017 | [Keep local preferences versioned and explicit to save](0017-versioned-local-preferences.md) |
| 0018 | [Keep keyboard ownership and frame geometry predictable](0018-focused-input-and-workspace-geometry.md) |
| 0019 | [Pin saved navigation to actual resource and input contracts](0019-saved-resource-view-contracts.md) |
| 0020 | [Treat theme configuration as validated color data](0020-data-only-theme-palettes.md) |
| 0021 | [Make release discovery optional and non-executable](0021-opt-in-release-notices.md) |
| 0022 | [Redact ordinary views and require deliberate value disclosure](0022-default-redaction-and-explicit-disclosure.md) |
| 0023 | [Scope rendering caches to their application and widget owners](0023-widget-style-cache-ownership.md) |
| 0024 | [Reuse complete stylesheet parses without partial publication](0024-transactional-css-parse-reuse.md) |
| 0025 | [Release discarded native table cache rings promptly](0025-native-table-cache-retirement.md) |
| 0026 | [Bound projection and rendering work without changing its meaning](0026-incremental-rendering-and-cooperative-work.md) |
| 0027 | [Separate frozen loader state from external program environments](0027-frozen-runtime-delegation.md) |
| 0028 | [Migrate application identity without duplicating runtime packages](0028-identity-and-preference-migration.md) |
| 0029 | [Separate tested release preparation from artifact publication](0029-immutable-release-activation.md) |
| 0030 | [Use explicit disposable fixtures and preserve original failures](0030-owned-verification-fixtures.md) |
| 0031 | [Build standard Python artifacts with one explicit backend](0031-standard-python-packaging.md) |

## Current foundations decisions

The numbered migration records above preserve their source-era decisions. Later
implemented decisions are kept separately without rewriting that history:

| Record | Scope |
| --- | --- |
| [0032: Kubeconfig preparation](0032-kubeconfig-loader-contract.md) | Per-session credentials, Basic authentication, and explicit OIDC exec migration |
| [0033: Cluster overview and history](0033-cluster-overview-and-history.md) | Native summary routing, session-owned collection, exact predicates and explicit Prometheus backend scope |
| [0034: Resource relationships](0034-native-resource-relationships.md) | UID-based native graphs, explicit declaration evidence and per-root collection budgets |
| [0035: Authorization evidence](0035-authorization-evidence-and-reviews.md) | Fresh self-reviews, explicit RBAC completeness and independent question/header scope |
| [0036: Native and external diagnostics](0036-native-and-external-diagnostics.md) | Qualified failure evidence, exact root/header scope and one cancelled/drained native or external producer |
| [0037: Reviewed local artifacts](0037-reviewed-local-artifacts.md) | Frozen source provenance, explicit disclosure/file consent and offline saved-artifact browsing |
| [0038: Container configuration provenance](0038-container-configuration-provenance.md) | Value-free current-API snapshots, bounded dependency resolution and separate fresh disclosure intents |
| [0039: Context-owned metric history](0039-context-owned-metric-history.md) | Fixed measurements, independent backend credentials, historical identity gaps and finite per-connection ownership |
| [0040: Curated resource observations](0040-curated-resource-observations.md) | Exact schemas, literal navigation, observed/fresh identity, bounded details and separate Event aggregates |
| [0041: Helm release identity](0041-helm-release-identity.md) | Actual storage identity, explicit optional CLI contracts, owned disclosure/rollback and uncertain effects |
| [0042: Local manifest batches](0042-local-manifest-batches.md) | Anchored local sources, frozen builtin rendering, real named creation, guarded declarative updates and explicit partial outcomes |
| [0043: Owned node-shell sessions](0043-owned-node-shell-sessions.md) | Explicit privileged diagnostics, single-attempt creation, returned-UID cleanup and private recovery |
| [0044: Reviewed ephemeral debugging](0044-reviewed-ephemeral-debugging.md) | Exact irreversible addition reviews, independent remote state and retained local attach leases |
| [Application composition](app-composition.md) | Integrated typed views, command metadata, navigation and operation owners; remaining stable-release work stays explicit |

The composition record retains its existing filename; it is not renumbered into
the historical migration. Its source checkpoints are not release qualification.

## Add or change a decision

Copy the [template](0000-template.md), choose the next unused number, and give
one concrete decision a descriptive filename. Keep numbers stable. Record the
actual implementation or label a proposal explicitly; do not describe a planned
controller or adapter as already integrated. Explain a superseding decision
rather than silently rewriting the historical rationale.

Link relevant modules, limits, and verification policy. Keep run logs, test counts,
and release history in their engineering records. Update the document disposition
map and this index in the same change.

The [previous log](../internal/architecture-history/README.md) is preserved
exactly with per-section hashes and active destinations. Acceptance history is kept in the same internal area, outside public navigation.
