# Configuration reference

Generated from preference defaults and parser declarations for source version `SOURCE_VERSION`.

Use [configuration](configuration.md) for examples, precedence, reload, and saving.
`NAME` and `RESOURCE` denote your mapping keys; `[]` denotes a list item.

## Root fields

The current root `schema_version` is `1`.

| Field | Default | Environment |
| --- | --- | --- |
| `theme` | `"k9s"` | `KUBERICH_THEME` |
| `refresh_seconds` | `2.0` | `KUBERICH_REFRESH` |
| `read_only` | `false` | `KUBERICH_READONLY` |
| `log_level` | `"WARNING"` | `KUBERICH_LOG_LEVEL` |
| `log_file` | `null` | `KUBERICH_LOG_FILE` |
| `shell` | `["sh"]` |  |

## Extension fields

These names come from the current validators, including optional fields absent
from empty defaults. A missing value without a fallback may be required or
nullable; the parser still validates it. A null fallback is not permission to supply null.

| Path | When omitted |
| --- | --- |
| `appearance.check_updates` | false |
| `appearance.contexts` | {} |
| `appearance.full_gvr_titles` | false |
| `appearance.schema_version` | 1 |
| `appearance.themes` | {} |
| `appearance.themes.NAME.accent` | No explicit fallback; see task guide |
| `appearance.themes.NAME.background` | No explicit fallback; see task guide |
| `appearance.themes.NAME.dark` | true |
| `appearance.themes.NAME.error` | No explicit fallback; see task guide |
| `appearance.themes.NAME.foreground` | No explicit fallback; see task guide |
| `appearance.themes.NAME.panel` | No explicit fallback; see task guide |
| `appearance.themes.NAME.primary` | No explicit fallback; see task guide |
| `appearance.themes.NAME.secondary` | No explicit fallback; see task guide |
| `appearance.themes.NAME.success` | No explicit fallback; see task guide |
| `appearance.themes.NAME.surface` | No explicit fallback; see task guide |
| `appearance.themes.NAME.warning` | No explicit fallback; see task guide |
| `context_settings.contexts` | {} |
| `context_settings.contexts.NAME.read_only` | No explicit fallback; see task guide |
| `context_settings.contexts.NAME.refresh_seconds` | null (before validation) |
| `context_settings.schema_version` | 1 |
| `forwarding.auto_annotations` | false |
| `forwarding.contexts` | {} |
| `forwarding.contexts.NAME.auto_annotations` | false |
| `forwarding.contexts.NAME.presets` | {} |
| `forwarding.presets` | {} |
| `forwarding.presets.NAME.address` | "127.0.0.1" |
| `forwarding.presets.NAME.ports` | null (before validation) |
| `forwarding.presets.NAME.retries` | 0 |
| `forwarding.presets.NAME.transport` | "auto" |
| `forwarding.schema_version` | 1 |
| `jumps.definitions` | {} |
| `jumps.definitions.NAME.description` | "" |
| `jumps.definitions.NAME.fields` | No explicit fallback; see task guide |
| `jumps.definitions.NAME.labels` | No explicit fallback; see task guide |
| `jumps.definitions.NAME.namespace` | No explicit fallback; see task guide |
| `jumps.definitions.NAME.source` | No explicit fallback; see task guide |
| `jumps.definitions.NAME.target` | No explicit fallback; see task guide |
| `jumps.schema_version` | 1 |
| `navigation.aliases` | {} |
| `navigation.contexts` | {} |
| `navigation.contexts.NAME.views` | {} |
| `navigation.favorites` | {} |
| `navigation.keys` | {} |
| `navigation.mouse` | false |
| `navigation.schema_version` | 0 |
| `navigation.views` | {} |
| `navigation.views.RESOURCE.columns` | null (before validation) |
| `navigation.views.RESOURCE.columns[].alignment` | "auto" |
| `navigation.views.RESOURCE.columns[].key` | null (before validation) |
| `navigation.views.RESOURCE.columns[].width` | null (before validation) |
| `navigation.views.RESOURCE.printer_signature` | null (before validation) |
| `navigation.views.RESOURCE.sort` | {} |
| `navigation.views.RESOURCE.sort.descending` | false |
| `navigation.views.RESOURCE.sort.key` | "name" |
| `plugins.commands` | No explicit fallback; see task guide |
| `plugins.commands.NAME.args` | [] |
| `plugins.commands.NAME.command` | null (before validation) |
| `plugins.commands.NAME.confirm` | true |
| `plugins.commands.NAME.dangerous` | true |
| `plugins.commands.NAME.description` | Entry name |
| `plugins.commands.NAME.directory` | Definition directory |
| `plugins.commands.NAME.environment` | {} |
| `plugins.commands.NAME.inputs` | [] |
| `plugins.commands.NAME.inputs[].default` | null (before validation) |
| `plugins.commands.NAME.inputs[].label` | Entry name |
| `plugins.commands.NAME.inputs[].name` | null (before validation) |
| `plugins.commands.NAME.inputs[].options` | [] |
| `plugins.commands.NAME.inputs[].required` | true |
| `plugins.commands.NAME.inputs[].type` | "string" |
| `plugins.commands.NAME.mode` | "capture" |
| `plugins.commands.NAME.output_limit` | 65536 |
| `plugins.commands.NAME.override` | false |
| `plugins.commands.NAME.scopes` | ["*"] |
| `plugins.commands.NAME.shortcut` | null (before validation) |
| `plugins.commands.NAME.timeout` | 300 |
| `plugins.commands.NAME.trusted_read_only` | false |
| `plugins.contexts` | {} |
| `plugins.contexts.NAME.commands` | {} |
| `plugins.contexts.NAME.locations` | [] |
| `plugins.locations` | No explicit fallback; see task guide |
| `plugins.schema_version` | null (before validation) |

The root accepts these versioned extensions: `appearance`, `context_settings`, `forwarding`, `jumps`, `navigation`, `plugins`.
Key profiles/actions come from the [key reference](cli-reference.md#additional-navigation-defaults).
Theme colors and plugin definitions are validated as described in their task guides.
