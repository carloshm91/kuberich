# Navigate and search

Use the command and filter bars to move between views without leaving the
workspace. Press `?` in a table for its current keys. Letters stay literal while
an input has focus; Escape returns focus to the view.

## Open a view

Press `:`, type a command, and press Enter. For example, `:pods`, `:deploy`,
`:ns`, and `:ctx` open their tables. `:pods demo-apps` selects that namespace;
`:pods *` selects all namespaces. The names in this guide are fictional.

The [generated command and key reference](cli-reference.md) lists registered
aliases and defaults. [Resource reference](resource-reference.md) lists standard
resource aliases. For a discovered resource, use
`:resource NAME.GROUP/VERSION` or an unambiguous discovered alias. A cluster-scoped
resource does not accept a namespace argument.

At launch, `--command 'pods demo-apps'` selects a starting view. Commands that need
a selected row or confirmation are unavailable at launch.

## Accept a suggestion

The command bar shows one suggested suffix on the same line. Tab accepts it for
editing. Up/Down cycle up to eight candidates; Enter then accepts and submits the
selected candidate once. Enter without arrow selection submits what you typed,
so bare `:ns` opens namespaces and `:ctx` opens contexts.

Suggestions come from loaded commands, configured aliases, contexts, and cached
resource and namespace names. Typing a suggestion makes no API or authentication
request. An unavailable namespace can still be entered explicitly. Escape clears
the command input. Moving the cursor away from its end hides the suffix.

Alt+Up/Alt+Down recall previous commands and filters separately. Histories keep
up to 32 entries for this session. `:!!` repeats the last accepted command through
its normal checks and review; it never confirms a write or plugin automatically.

## Move through a table

Use arrows or `j`/`k`, `g`/Shift+G for first/last, and Ctrl+B/Ctrl+F for pages.
In tables, `J` moves half a page down and Ctrl+U half a page up. `h`/Alt+L scroll
horizontally. Home/End move horizontally; Ctrl+Home/Ctrl+End select first/last rows.
A capital letter is one uppercase key; Vim counts and multi-key grammar are not
implemented. Resource and namespace `s`/Shift+S cycle or reverse typed sorting.

Container `s` opens a shell. Resource `l` opens logs and Ctrl+D opens deletion
review in write mode. Logs and text documents use their independent movement
keys. Keys depend on the focused view; the embedded shell passes them to the
remote program. [Configuration](configuration.md) explains additional key bindings.

## Filter resources

Press `/`, enter one query family, then Enter to focus the table. Escape in the
table clears the filter. Filters run locally over the rows already read; they
do not narrow the API request or grant access to hidden resources.

| Query | Matching rule |
| --- | --- |
| `api` | Case-insensitive literal substring |
| `re:api\|worker` | Unicode regular expression |
| `!re:api\|worker` | Inverse regular expression |
| `fuzzy:apwrk` | Characters occurring in order |
| `label:app=api,tier in (frontend,worker),!debug` | Label terms combined with AND |
| `field:metadata.name=demo-api` | Supported field equality |

Label terms support equality, inequality, `in`, `notin`, existence, and absence.
Field terms support equality and inequality for metadata name/namespace, Pod
phase/node/scheduler/hostNetwork, Node unschedulable, and Job successful count.
Arbitrary JSON paths, annotations, and Secret data are excluded.

Queries accept up to 256 characters and eight selector terms. Regex matching has
a 50 ms total budget; metadata filters have 250 ms. Invalid or timed-out filters
show an error and all rows, never a misleading partial result. Sorting remains
unchanged. Age is excluded from ordinary resource text matching.

`:errors` shows observable failures or unready resources. Unknown health is counted
separately; a resource without known conditions is not assumed healthy.

## Inspect a resource

On a selected row, `d` opens details, `y` YAML, and `e` events. These are read
snapshots with redacted values. `/` searches text, `n`/Shift+N move between matches,
and Escape returns. `m` toggles managed fields where offered. ConfigMap and Secret
values have a separate [deliberate reveal workflow](editing.md#inspect-configuration-data).

`:wide` temporarily expands available columns. `:views` changes columns, widths,
alignment, and sort; Apply affects this session, while Global or Context saves
preferences explicitly. A hidden field may still be used in sorting or filtering.
Hiding a column is not a confidentiality control.

## Mark rows and copy

Space marks a resource; Shift+Up/Shift+Down extend a range. `:mark`, `:range`,
`:selectall`, and `:selectnone` provide command alternatives. Up to 100 UIDs can be
marked. Marks disappear with rows or scope changes, and replacement objects do
not inherit them. `:deletebatch` reviews marked rows when marks exist.

`:copy` copies selected names, `:copyns` namespaces, and `:copytext` table text.
Ctrl+Y copies the selected name in the root table. Copy is always explicit.
Clipboard limits and SSH/tmux setup are in [troubleshooting](troubleshooting.md#clipboard).

## Return and adjust the workspace

Alt+Left/Alt+Right or `:back`/`:forward` restore the previous/next view, context,
namespace, filter, sorting, selection, and viewport. History keeps up to 32 states
per direction and is not saved across launches.

`:headless` hides shortcuts and the logo, `:crumbsless` hides identity and the trail,
and `:fullscreen` hides headers, trails, and frame borders. Command, search, and
status remain available. These controls do not save preferences.

In nested containers, inspection, and log views, `:` uses that view's command bar.
Accepted scope changes close the old reads before switching. Escape leaves an
input before going back. Help restores the preceding focus.

## Save favorite namespaces and jumps

`:favorite add demo-apps` and `:favorite remove demo-apps` save names under the
current context. `:favorites` filters the namespace table to them; `:ns` shows all
namespaces. Favorites do not create rows or grant namespace-list permission.

A configured `:jump` opens a related resource view with a filter from the selected
row. If several match, use `:jump NAME`. Templates read fields; they run no code.
See [configuration](configuration.md#define-a-resource-jump) for an example.
