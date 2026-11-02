# Reactive preferences: U06 #64

This completes #64 after [resource jumps](resource-jumps.md). Preferences reload
while KubeRich runs, contexts can carry their own settings, palettes can use the
terminal background and titles can show the API version. It does not publish a
package or change the 0.1.0 distribution.

## Behavior

- The running app checks the preference file every two seconds. The file is
  read and validated off the event loop with the same checks as
  `kuberich config check`. A file is compared by device, inode, size and
  modification time, so an unchanged file is not parsed again.
- A valid change replaces the in-memory document in one step, then applies
  themes, aliases, column views, jumps, context settings, plugins, the shell and
  the refresh interval. The current view, filter and selection stay. A save
  made from the UI at the same moment wins; the reload is skipped.
- An invalid file keeps the last valid preferences and shows one warning per
  file version. A deleted file keeps the current preferences.
- Key binding and mouse changes are reported as needing a restart. Log settings
  also need a restart.
- `context_settings` (schema version 1) accepts `read_only: true` and
  `refresh_seconds` per context. `read_only: false` is refused. Precedence is
  command line and environment, then context, then file, then defaults. The
  shared access policy is tightened, never loosened: `--write` cannot lift a
  context's read-only setting, and a reload that turns `read_only` off keeps
  the running session read-only.
- `background`, `surface` and `panel` accept `'default'`, which uses the
  terminal's own background through Textual's ANSI default color. Contrast
  checks skip those colors.
- `appearance.full_gvr_titles: true` adds the API version to built-in view
  titles.
- Unknown fields are kept and named at startup, on reload and by
  `kuberich config check`. Names are escaped and at most eight are listed.

## Evidence

Focused local run (Linux, CPython 3.12.12, Textual 8.2.8):

```sh
uv run pytest tests/ui/test_live_preferences.py tests/unit/test_context_settings.py tests/unit/test_access_policy.py tests/unit/test_appearance.py tests/unit/test_cli_config.py --cov=kuberich --cov-branch
```

`config/context_settings.py`, `domain/appearance.py`, `services/access.py`,
`ui/config_check.py` and `ui/theme_catalog.py` are fully covered.
`ui/live_preferences.py` misses only its type-checking import.

The headless tests drive a real reload through the two-second poll, an invalid
file reported once, a deleted file, context switching with `:ctx`, flag and
environment precedence, a theme override kept on reload and a column view
applied to a live pod table served by a local test API.

Not verified: transparent backgrounds were checked through Textual's color
values, not by looking at a real transparent terminal window. No disposable
cluster run was added; reload does not talk to the cluster.
