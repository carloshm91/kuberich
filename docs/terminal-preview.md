# Terminal preview

Run `uv run kubetrol` or `uv run python -m kubetrol` in an interactive terminal.
The current development build opens the workspace directly, without a splash
delay. It shows the selected context and namespace as `—`, the connection as
`Disconnected`, and an empty resource table. Startup does not load kubeconfig,
run credential helpers or connect to Kubernetes.

The workspace has a resource region, filter and command inputs, status and
available-key hints. This is the first UI checkpoint; context selection, live
resources, details, logs, shell and resource commands are upcoming tasks.

## Controls

| Control | Current behavior |
| --- | --- |
| `/` outside an input | Focus the filter |
| `:` outside an input | Focus the command input |
| `Enter` in the filter | Keep the filter text and return to the table |
| `Enter` in the command | Submit `help` or `quit`; aliases `?`, `q` and `exit` also work |
| `?` outside an input, or F1 anywhere | Open scrollable keyboard help |
| PageUp/PageDown, Home/End in help | Scroll its body using the keyboard |
| `Esc` in help | Close help and restore the previous focus |
| `Esc` in an input | Cancel command text and return to the table; retain filter text |
| `Esc` in the table | Clear the filter and reset the disconnected status |
| `Tab` / `Shift+Tab` | Move keyboard focus |
| Click | Focus an input or select a table row when rows exist |
| Left/right arrows in the table | Scroll columns horizontally in a narrow window |
| `q` outside inputs | Quit |
| Ctrl+Q or Ctrl+C | Quit, including while editing an input or reading help |

An active filter reports that no resources are available while disconnected.
Unknown commands show a concise unavailable message. Neither input contacts a
cluster. Both inputs are limited to 256 characters and support Unicode text
and terminal paste. Typing `q`, `/`, `:` or `?` inside an input inserts text;
F1 remains available for help.

## Size and appearance

Layouts are tested from 40 columns by 12 rows through 160 by 50. Below 70 columns,
context and namespace indicators stack vertically; below 16 rows, secondary
preview copy is hidden to preserve the table and controls. Help has its own
scrollable body and accessible Back button. Smaller sizes are not qualified.

The configured `theme` selects a built-in Textual theme, such as `textual-dark`,
`textual-light` or `nord`. An unregistered theme fails safely with exit 2 before
opening the UI. `NO_COLOR` selects the framework's monochrome mode. The
`read_only` preference appears in the header; resource mutations do not exist
in this preview. Refresh settings will be consumed by the cluster services.
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

Pilot tests cover navigation, mouse focus/selection, resize, input, help, themes
and error cleanup. Two checked-in geometry snapshots guard normal/compact
layouts; tests export actual workspace/help SVGs as CI artifacts. Real PTY tests
exercise quit, command bursts, Unicode paste, resize and failure restoration,
including the wheel's console and module entry points outside the checkout.
SSH and tmux qualification belong to later terminal tickets.
