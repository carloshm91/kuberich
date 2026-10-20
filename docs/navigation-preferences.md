# Navigation, aliases and saved resource views

These preferences are implemented in the source checkout for the next release.
Published 0.1.0 packages do not include configurable navigation or persisted
column layouts. Existing configuration files continue to work.

## Navigation belongs to the focused view

Tables accept `j`/`k` for down/up, `g`/`G` for first/last, Ctrl+B/Ctrl+F for
pages, Ctrl+U for half a page up, `J` for half a page down, `h` for horizontal
left and Alt+L for horizontal right. Resource and namespace tables additionally
use `s`/`S` to cycle/reverse the sort. Sorting uses actual numbers, dates and
quantities, including when the sort field is hidden.

Arrows, Home/End, PageUp/PageDown and Ctrl+Home/Ctrl+End remain fixed fallbacks.
Home/End move horizontally; Ctrl+Home/Ctrl+End select the first/last row. The
additional navigation keys apply while the corresponding table or log body
has focus. Command, filter, search and editor inputs retain literal text and
their normal editing keys.

Logs use `l` for horizontal right and Ctrl+D for half a page down. In resource
tables, `l` opens logs and Ctrl+D opens the existing deletion review in write
mode; it does not execute a deletion. Read-only mode rejects that review.
In logs, `n`/`N` move between search matches; in the workspace `n` opens namespaces.
Ctrl+Y stays reserved for explicit copy in views that provide it. In container
tables, `s` continues to open a shell rather than sort. Remote shell input
continues to go to the embedded terminal.

Press `?` while a table has focus to see its effective navigation and fixed
actions. Resource help, log controls and applicable header shortcuts reflect
configured keys. Upper/lowercase keys remain distinct.

Next-release source also has an independent `text` profile for read-only
documents/help, explicit mouse opt-in, namespace favorites and bounded remote
copy. See the [complete interaction matrix](terminal-navigation.md).

## Configure keys and aliases

Use the preference file shown by `kuberich info`, or select one with `--config`.
The root schema remains version 1. The `navigation` section has its own version:

```yaml
schema_version: 1
navigation:
  schema_version: 1
  keys:
    resources:
      first: H
      last: K
      sort: u
      reverse_sort: U
    logs:
      first: H
      last: K
  aliases:
    work: pods
    lab: ctx demo-lab
    mywidgets: resource widgets.example.test/v1
```

The names and context in this example are fictional. Choose names from your own
intended context. `:work team` expands to `:pods team`. `:lab` already includes
an argument, so adding another argument is refused. Aliases also work with
`--command` when their target is a supported startup view. Cluster actions,
including aliases for them, require an interactive resource selection and the
same read-only policy as the original command. An alias never executes a shell
command, Python expression or variable substitution.

Supported key profiles are `table`, `resources`, `namespaces`, `contexts`,
`containers`, `data`, `themes`, `forwards`, `sources` and `logs`. `table` supplies
common table defaults; a more specific profile wins. Logs are independent.
Actions are `down`, `up`, `first`, `last`, `page_up`, `page_down`, `half_up`,
`half_down`, `left` and `right`. `sort` and `reverse_sort` apply to resources and
namespaces; their common defaults may be specified in `table`.

Keys use one ASCII letter/digit, `ctrl+` plus a lowercase letter, or `alt+` plus
a letter/digit. Chords such as `gg` and comma-separated keys are unsupported.
Native fallback, quit, input, help and actual per-view action keys are reserved.
Ctrl+M/J/I/H are refused because common terminals encode them as Enter, Tab or
Backspace. Duplicate effective keys or conflicts reject the navigation override
and retain working defaults. Run `kuberich config check` for the specific error.

Up to 64 aliases are accepted. Names use lowercase ASCII letters/digits,
underscores or hyphens, start with a letter and contain at most 32 characters.
Targets and supplied arguments are bounded to 256 characters. Built-in names,
cycles, ambiguous preset arguments and chains exceeding eight expansions are
refused. A name that collides with a discovered resource is not offered by
completion and produces a clear error; `:resource NAME.GROUP/VERSION` remains
available to select that resource explicitly. Completion uses the effective
aliases without making a request for each keystroke.

## Configure a resource view

Open `:views` in a Pod, namespace, standard-resource or discovered-resource table.
It lists the available field keys and the current selection. For columns, enter
space-separated `key[:width][:alignment]` entries, in display order. Omit a field
to hide it. Width is `auto` or an integer from 1 to 256; alignment is `auto`,
`left`, `center` or `right`. For example:

```text
name:24:left ready:8:center age:8
```

Choose a typed sort field separately and optionally select Descending. The sort
field can be hidden. The `name` column stays visible for stable identity;
all-namespace lists also retain `namespace` so equal names can be distinguished.
Widths and alignment affect display only. They do not convert typed sort values
into strings. Header clicks and effective sort keys change this session's sort.
Filters retain the typed row model, so hiding a field does not make its values
confidential or necessarily remove it from search. Pod/standard summaries remain
searchable, and a generic view's hidden sort field also participates. Generic
fields excluded from both display and sort are not projected into its filter.

- **Apply** updates this session only.
- **Global** explicitly saves the resource view for all contexts.
- **Context** explicitly saves it for the context named in the editor.
- **Back / Escape** closes without applying unsaved input.

A matching context preference takes precedence over a global preference, even
after a new global save. A save requested for a captured resource/context cannot
silently apply to another view. If its scope or server columns change before the
request, reopen the editor. A requested file save finishes before closing, also
during graceful exit. A save is refused if the file changed on disk since it
was loaded. KubeRich loads a valid change within two seconds; save again after
that. Saving preserves original settings, themes and unknown fields and never
persists runtime `--readonly`, connection or environment overrides.

Saved files and new preference directories use the existing private permissions.
Read-only cluster mode still permits local preference saves. Previewing, loading,
validating, scrolling and sorting do not silently write files. Invalid navigation
sections leave the original bytes intact and disable saves until corrected.
An inapplicable resource layout falls back to a valid global layout or defaults
with a visible explanation. `config check` validates known built-in fields
offline; discovered fields require the actual API's schema.

## Saved format and migration

Resources use `VERSION/RESOURCE` for the core API or `GROUP/VERSION/RESOURCE` for
a named API group. Views are pinned to the actual served version. A native view
and an explicit server-printer view of the same resource have separate keys:
server-printer keys begin with `server:`.

```yaml
schema_version: 1
navigation:
  schema_version: 1
  views:
    apps/v1/deployments:
      columns:
        - key: name
          width: 24
          alignment: left
        - key: ready
          width: 8
          alignment: right
      sort:
        key: desired
        descending: true
  contexts:
    demo-lab:
      views:
        v1/pods:
          columns:
            - key: name
            - key: age
          sort:
            key: restarts
            descending: true
```

The editor records a `printer_signature` for discovered resources. It fingerprints
ordered server column names, types, formats and priorities, without retaining
resource values. Positional `cN` references require this evidence. A changed
printer schema cannot reinterpret old positions under new labels. Old saved
preferences remain on disk while the view uses working defaults. Generic views
remain read-only; configuring columns does not enable cluster mutations.
`:columns` remains the session-only server-column shortcut.

A missing/zero navigation version is read as the earlier format: flat keys,
string columns, a widths mapping, string sort and a separate descending boolean.
It migrates in memory, including printer keys to their `server:` namespace.
The next explicit save writes navigation version 1. Loading and `config check`
do not rewrite it. Unknown future versions, duplicate migrated views and invalid
fields produce an error rather than discarding preferences. Legacy application
paths require `kuberich config migrate` before a save.

The existing 64 KiB file bound applies. There are at most 128 global resource
views, 128 context entries and 128 views per context; session view memory uses a
bounded cache. Views contain display preferences, not kubeconfig contents,
credentials or resource data. Saved column views, aliases and favorites apply
while KubeRich runs; key binding and mouse changes need a restart. See
[changing preferences](configuration.md#changing-preferences-while-kuberich-runs)
and [resource jumps](resource-jumps.md). Extended filters and Vim multi-key/count
commands remain separate work.

See [commands](command-navigation.md), [themes](themes.md),
[standard resources](standard-resources.md) and
[discovered resources](standard-resources.md#generic-discovered-resources).
