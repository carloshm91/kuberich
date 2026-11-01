# Open a shell or attach

Open an embedded terminal for a selected container. You need kubectl on PATH,
a trusted connection, pod read access, and `pods/exec` for a shell or `pods/attach`
for attachment. Read-only mode blocks both actions.

## Start a shell

1. Start with an explicit context and namespace in write mode:

   ```sh
   kuberich --context demo-lab --namespace demo-apps --write
   ```

2. Replace those fictional names with your intended scope. Select a pod and press
   Enter, or use `x`, `:shell`, or `:exec` to open its container table.
3. Check the container name and state. Press `s` or `x` on the intended container.

The shell opens full screen inside the Textual workspace. Its frame identifies
the context, namespace, pod, and container. The default command is `sh`; the image
must contain it. Configure another argument list in preferences if needed:

```yaml
schema_version: 1
shell: ["/bin/bash", "-l"]
```

Run `kuberich config check` after editing. Arguments are passed literally; shell
expressions are not interpreted by KubeRich. The setting applies to the next shell.
A startup `--command shell` is unavailable because a selected pod is required.

## Return without leaving the workspace

| Control | Result |
| --- | --- |
| `exit` or Ctrl+D | Exit the shell and return to containers |
| Ctrl+] | Close this local exec session and return |
| Ctrl+C | Interrupt the remote program |
| Ctrl+Q | Quit KubeRich and stop its local processes |

While the terminal is live, Escape, arrows, Tab, `q`, `:`, and `/` reach the remote
program. Full-screen editors and ANSI colors use the embedded emulator. Resizing
changes the remote terminal size. Escape after returning to containers restores
the preceding pod table and its selection.

## Review terminal history

Click **History**, or press Alt+PageUp/Shift+PageUp, to review a frozen copy of
normal-screen output. The remote program keeps running. Full-screen alternate
buffers do not enter normal-screen history.

- Arrows or `j`/`k`, page keys, and `g`/Shift+G move locally.
- `/` or Ctrl+F starts literal, case-insensitive search. Enter finds a match;
  `n`/Shift+N move through matches.
- `v` or Space starts/ends a row range. Shift-click can select a range when mouse
  reporting is enabled. `y` or Ctrl+Y copies selected whole rows explicitly.
- Enter, Escape, `q`, or **Live** returns to the running screen.

History keeps up to 1,000 scrolled rows; a frozen copy keeps its own rows while
live history advances. Search accepts 256 characters; copy accepts 64 KiB after
control escaping and recognized-credential redaction. Output can still contain
secrets the application cannot identify. Remote clipboard escape requests are
inert; no output copies automatically.

## Attach to an existing process

Use `:attach` on a pod, then `a` on a running container. Attach connects to its
existing main process. That process's stdin and TTY settings decide whether
interaction is possible; this action does not create a new shell.

Press Ctrl+P then Ctrl+Q to send kubectl's detach sequence. Ctrl+] closes the local
session. Ctrl+C reaches the existing process and can affect the workload.
Ctrl+Q alone quits KubeRich. Closing or detaching does not request pod deletion.

## Handle a failed or stale session

A deleted, replaced, completed, or deleting pod cannot start an old selection's
session. Select the pod again after a context or UID change. KubeRich checks the
pod before launch, but Kubernetes exec/attach targets names and has no atomic UID
precondition; replacement between the check and server request remains possible.

Exit 126/127 often means the configured image shell is missing. Check kubectl,
permissions, the selected container, and its state before trying again. An image
without a shell needs a suitable image; SSH is not required for pod exec.

The private kubectl connection file is deleted after return. The source kubeconfig
and current-context are unchanged. Local cleanup cannot promise termination of a
remote exec process after a lost connection. Raw interactive output is visible
in the terminal and is not copied into application diagnostic logs.

Mouse reporting, terminal graphics, and advanced keyboard protocols are not
implemented inside the remote emulator. For file movement, use
[file transfers](container-attach-copy.md).
