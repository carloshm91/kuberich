# Architecture decision records

Start with the [architecture overview](../architecture.md). Each numbered record
explains one implemented decision, its consequences, and the main source modules.
The migration records describe source snapshot
`625086db1a75aab10ec28fe4d6440f7fb1d32849`; they do not certify new measurements.

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
exactly with per-section hashes and active destinations. This migration does not
relocate the separate acceptance-history collection.
