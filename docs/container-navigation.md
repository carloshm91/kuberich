# Pod and container navigation

Select a connected pod and press Enter. A scrollable table shows the selected
pod’s regular and init containers, including pods with only one container.
Type labels distinguish App, Init and restartable init Sidecar containers.
Press Enter or `l` on a row to open that container’s logs directly.

Esc returns logs → containers → pods. Both tables retain their selection and
viewport. In logs, `c` still switches among all of this pod’s containers.
On the pod table, `l` keeps its direct shortcut: one container opens immediately,
multiple containers show the existing log picker. `d` opens resource details;
`y` and `e` open YAML and related events.

The container table supports arrows, PageUp/PageDown, `j/k` and `g/G` (Shift+G)
for first/last row. These letters remain log controls after opening logs.
The view fits 40×12 and 100×30 windows, with horizontal scrolling for long names.

This table uses names from the captured pod snapshot. Reopen it to refresh.
Live container status and ephemeral debug container browsing remain later work.
Read-only mode supports container navigation and logs. No kubeconfig or cluster
resource is modified by opening these views.

The captured target includes context, client generation, namespace and pod UID.
Changing scope or deleting/recreating the pod invalidates selection, including
while logs cover the container screen. The backend independently checks pod UID
and container membership before and after opening the log stream. Closing logs
cancels and awaits their owned tasks.

For command suggestions, type `:ns ` and a prefix, use Up/Down to choose, then
Enter to accept and submit once. Tab accepts without submitting. Plain Enter
keeps literal commands and the bare `:ns`/`:ctx` selectors. Editing, leaving the
input or changing scope discards prior arrow selection.

See [log controls](log-viewer.md), [commands](command-navigation.md),
[feedback #115](https://github.com/carloshm91/kubetrol/issues/115) and
[measured acceptance evidence](acceptance/enter-navigation.md).
