# Resource jumps: U06 #64

This adds configured jumps from a selected row to a related view. It does not
publish a package or change the 0.1.0 distribution. Reactive reload, per-context
overrides, transparent colors, full GVR titles and unsupported-field reporting
are covered in [reactive preferences](reactive-preferences.md).

## Behavior

- `domain/jumps.py` parses the versioned `jumps` extension strictly: at most 64
  named definitions, only known keys, `labels` or `fields` but not both, and
  source/target written as `VERSION/RESOURCE` or `GROUP/VERSION/RESOURCE`.
- Templates contain only field paths: dotted names and quoted keys. Filters,
  calls, indexes and any other expression are refused when the file is read.
  At most eight placeholders are allowed per value.
- Rendering reads from the manifest captured for the selected row. A missing
  field, a list or map where one value is needed, or a value with characters
  outside letters, digits, `.`, `_`, `-` and `/` refuses the jump. A whole
  label-map placeholder expands to sorted `key=value` pairs.
- The rendered namespace is validated as a namespace name. Cluster-scoped
  targets refuse a namespace template. Label and field results are validated by
  the same local selector parser as the filter box, including the field
  allowlist.
- `:jump` opens the only jump for the current view or lists the choices.
  `:jump NAME` picks one. Built-in views are used when the target is the served
  preferred version; other versions open the discovered view at that version.
  The filter is set after the view changes, so `:back` restores the previous
  view and its filter.
- `kuberich config check` validates jump definitions without connecting.

The filter runs on rows KubeRich already watches. It is not sent to the API
server as a selector.

## Evidence

Focused local run (Linux, CPython 3.12.12, Textual 8.2.8):

```sh
uv run pytest tests/unit/test_jumps.py tests/ui/test_jumps.py tests/unit/test_cli_config.py tests/unit/test_navigation.py --cov=kuberich --cov-branch
```

Result: 134 passed. `domain/jumps.py` 134/134 lines and 58/58 branches;
`config/jumps.py` 4/4 lines.

No disposable cluster run was added. Jumps only choose a view and fill the
local filter. View switching has kind coverage in the navigation checks; the
`label:` and `field:` filters are covered by unit and headless UI tests only.
