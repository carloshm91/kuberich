# Local processes and terminal handoff

S03 #31 implements the shared process service and native terminal adapter.
S04 #32 uses it for [selected-container shells](container-shell.md).
Plugins, manifest editing and managed port-forward views retain their own tasks.

## Captured commands

`domain/processes.py` captures an immutable argument vector, explicit working
directory, environment, process mode and effect purpose before any await.
The kubectl exec builder captures context, namespace, pod, container and session
UID. It passes individual flags and an explicit `--` boundary before the shell
arguments. It never interpolates a resource into a shell command string.

A single kubeconfig uses an explicit absolute `--kubeconfig` flag. Multiple
files use a captured absolute `KUBECONFIG` list, preserving kubectl's merge
semantics; neither mode follows later ambient environment changes. The editor
builder separates configured arguments from the captured absolute filename
with `--`. Editor configurations are argument sequences, not shell expressions.

Effect purposes map to the shared exec, attach, mutation or plugin policy.
Read-only mode refuses every currently supported external-process purpose
before executable lookup, including direct service invocation. Authentication
helpers retain their separate existing login contract. A resource-bound command
requires a current-target guard, checked before lookup, after lookup and after
startup. These guards do not create an atomic Kubernetes UID precondition.

## Modes and lifecycle

| Mode | API | Contract |
| --- | --- | --- |
| Captured | `ProcessRunner.capture` | No terminal stdin; separately retained stdout/stderr; default 30-second timeout |
| Background | `ProcessRunner.background` | Owned session handle; bounded output and optional timeout; explicit close or runner shutdown |
| Foreground | `terminal_handoff` | Public Textual suspension, actual terminal descriptors and POSIX foreground process-group ownership |

Captured/background output defaults to **1 MiB combined** stdout/stderr, with
configurable service limits of 1 byte through 8 MiB. Exceeding the limit ends
the process with an explicit output-limit outcome. Exact-limit output can
finish successfully. Results distinguish success, nonzero exit, signal exit,
timeout, output limit, pipe failure and owner cancellation, retaining the real
return code. Raw captured bytes are private API data: consumers must redact and
escape them before display/export. Command/environment/result reprs expose no
credentials; service errors omit arguments and child output.

Each child has an owned process group. Cleanup sends continue/termination,
allows a short grace period, then kills remaining group members and closes the
transport. It runs even when the leader exits while descendants retain pipes.
Explicit background `wait` cancellation does not discard ownership: close
the session or runner. Captured/foreground caller cancellation drains cleanup
before propagating. Startup and executable-resolution work are owned through
cancellation; runner shutdown waits for in-progress launches and all sessions.
The application closes its injected runner on unmount.

## Terminal restoration

The native Linux/macOS adapter refuses nonterminals and a terminal owned by
another foreground group. Inside `App.suspend`, it records the original
foreground group and TTY attributes, hands the foreground group to the child,
and resumes a child stopped by an early read. Input, Ctrl+C and SIGWINCH reach
that group through the actual terminal; there is no embedded emulator.

After the child ends, the adapter restores the parent group and exact attributes
before Textual resumes. Concurrent handoffs are refused before suspension.
The pinned Textual 8.2.8 context resumes after its yield rather than in a finally
block: the wrapper catches failures/cancellation inside that context, exits it
normally, then propagates the failure. Requalify this on Textual upgrades.
SIGTERM during handoff requests owned cancellation and exits the app with 143
only after terminal restoration and Textual resumption. Its previous signal
handler is restored. Uncatchable termination cannot provide orderly restoration.

The foreground child is explicitly invoked local code with the user's privileges
and direct terminal access. The app does not sandbox it. Descendants that
deliberately detach from the owned process group are outside this group's cleanup
contract; future plugin configuration must retain that local trust boundary.
This foundation checkpoint records its local-process scope. S04 adds the CLI
shell shortcut and actual Kubernetes exec evidence; cloud and remote SSH/tmux
qualification remain separate.

## Trial and references

Developers can reproduce the owned local-process and native-PTY behavior without
a cluster:

```sh
uv run pytest tests/unit/test_processes.py tests/contract/test_processes.py tests/unit/test_terminal_lease.py tests/ui/test_handoff.py tests/terminal/test_handoff.py
```

See [measured S03 acceptance evidence](acceptance/S03.md) for the qualified
interpreters, coverage gates, installed-wheel trial and platform limits.

See [Textual suspension](https://textual.textualize.io/api/app/#textual.app.App.suspend),
[asyncio subprocess protocols](https://docs.python.org/3.12/library/asyncio-protocol.html#subprocess-protocols)
and [POSIX foreground groups](https://docs.python.org/3.12/library/os.html#os.tcsetpgrp).
