# Terminal preview

Run `uv run kubetrol` or `uv run python -m kubetrol` in an interactive terminal.
The current development build opens the workspace directly, without a splash
delay. It loads a local kubeconfig catalogue before the UI, then authenticates and
discovers namespaces in an owned background session. Without a selected context
it stays disconnected. A connected scope now synchronizes pods and shows the
live count, pod rows and stale/error status. See the [pod table](pod-table.md)
for column semantics and typed sorting.
See [context sessions](context-sessions.md) for flags, credentials, states and bounds.
See [active resource views](resource-views.md) for freshness, switching and cleanup.

The workspace has a resource region, filter and command inputs, status and
available-key hints. Context/namespace selectors are scrollable and maintain
literal names. Filtering/completion, details, logs and shell are subsequent tasks.

## Controls

| Control | Current behavior |
| --- | --- |
| `/` outside an input | Focus the filter |
| `:` outside an input | Focus the command input |
| `Enter` in the filter | Keep the filter text and return to the table |
| `Enter` in the command | Submit help/quit or `ctx [NAME]` / `ns [NAME or *]` |
| F2 / F3 | Choose context / namespace |
| F4 | Retry the selected connection |
| F5 | Read the full connection message in a scrollable dialog |
| `?` outside an input, or F1 anywhere | Open scrollable keyboard help |
| PageUp/PageDown, Home/End in help | Scroll its body using the keyboard |
| `Esc` in help | Close help and restore the previous focus |
| `Esc` in an input | Cancel command text and return to the table; retain filter text |
| `Esc` in the table | Clear the filter and restore the current connection status |
| `Tab` / `Shift+Tab` | Move keyboard focus |
| Click | Focus an input or select a table row when rows exist |
| Left/right arrows in the table | Scroll columns horizontally in a narrow window |
| `q` outside inputs | Quit |
| Ctrl+Q or Ctrl+C | Quit, including while editing an input or reading help |

The filter input is available; actual filtering ships in B03 #27. Context commands
connect explicitly; namespace commands record scope. Unknown commands show a
concise unavailable message. Both inputs are limited to 256 characters and support Unicode text
and terminal paste. Typing `q`, `/`, `:` or `?` inside an input inserts text;
F1 remains available for help.

## Size and appearance

Layouts are tested from 40 columns by 12 rows through 160 by 50. Below 70 columns,
context and namespace indicators stack vertically; below 16 rows, secondary
preview copy and the application header are hidden to preserve data rows and controls. Help has its own
scrollable body and accessible Back button. Smaller sizes are not qualified.

`--headless` hides the application header, `--logoless` hides its brand, and
`--crumbsless` hides the context/namespace scope bar. These invocation-only flags
preserve filter/command inputs, status and key hints through resize. Initial
`--command help` (or `-c help`) opens the help dialog; `--command quit` exits
cleanly. Other initial commands return unavailable until resource routing ships.

The configured `theme` selects a built-in Textual theme, such as `textual-dark`,
`textual-light` or `nord`. An unregistered theme fails safely with exit 2 before
opening the UI. `NO_COLOR` selects the framework's monochrome mode. The
`read_only` preference, overridden by `--readonly` or `--write`, appears in the
header and at the start of the status. Shared command decisions refuse mutation,
shell, attach and unclassified plugins in read-only mode. These operations are
unavailable in write mode too: this preview has no cluster effects. Actual future
services must use the guard before any effect. Explicit launch refresh is
unavailable; stored refresh preferences await the cluster services.
See [preferences](configuration.md) for file and environment configuration.

## Exit and diagnostics

Normal quit restores terminal attributes, the previous screen, cursor visibility,
mouse/focus reporting and bracketed-paste mode, then returns exit 0. Ctrl+C
inside this UI is a normal quit; an interrupted non-UI operation returns 130.
A runtime UI failure also restores the terminal and returns exit 1 with an
owned message. Its diagnostic log records exception type/frame locations without
exception values, source text or locals.

Launching the UI with redirected stdin or stdout fails immediately with exit 2
and an interactive-terminal hint. `info`, `config check`, help and version remain
usable without a terminal. No Kubernetes connection is inferred from TTY access.

Pilot tests cover launch visibility/initial commands, shared read-only guards,
navigation, mouse focus/selection, resize, input, help, themes
and error cleanup. Two checked-in geometry snapshots guard normal/compact
layouts; tests export actual workspace/help SVGs as CI artifacts. Real PTY tests
exercise quit, command bursts, Unicode paste, resize and failure restoration,
including the wheel's console and module entry points outside the checkout.
SSH and tmux qualification belong to later terminal tickets.
