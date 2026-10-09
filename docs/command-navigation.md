# Commands, filtering and navigation

The development terminal has live pod and namespace views. Selected pods support [inspection](resource-inspection.md),
[logs](log-viewer.md) and [embedded shells](container-shell.md); other resource
tables are described in [standard resources](standard-resources.md).

## Commands

Press `:` outside an input, type a command and press Enter. The same parser and
read-only policy handle `--command` / `-c` at launch. Arguments preserve casing.

| Command | Behavior |
| --- | --- |
| `po`, `pod`, `pods` | Focus the available pod view |
| `po NAMESPACE`, `po *` | Select a pod namespace or all namespaces |
| `ctx`, `context`, `contexts` | Open the local context workspace table |
| `ctx NAME` | Connect directly to that context |
| `ns`, `namespace`, `namespaces` | Open the live namespace workspace table |
| `ns NAME`, `ns *` | Select that namespace or all namespaces |
| `shell`, `exec` | Open the selected pod’s container picker; `s`/`x` launches its shell |
| `attach` | Choose a running container; `a` connects to its existing main process |
| `upload`, `download` | Choose a container; `u`/`d` opens explicit copy review |
| `status`, `retry` | Open connection details / reconnect |
| `resource NAME[.GROUP][/VERSION] [NAMESPACE or *]` | Browse a discovered API family or an explicit served version |
| `refresh` | Renew discovery and the selected resource watch on the current client |
| `columns`, `columns cN ...`, `columns default`, `columns none` | Inspect/configure transient generic server columns |
| `back`, `forward` | Restore the previous / next navigation state |
| `help`, `?` | Show actual keyboard actions and limits |
| `quit`, `q`, `exit` | Exit and restore the terminal |

For example, `uv run kuberich --context YOUR_CONTEXT --command 'po YOUR_NAMESPACE'`
connects once and starts the requested pod scope without first watching another
namespace. `--command 'ctx NAME'` selects that context before authentication.
Unsupported commands report unavailable; they never display a substitute table.
Inspection commands remain usable in read-only mode. Embedded shells are available
in write mode; startup `--command shell`/`exec` is refused because a deliberately
selected pod is required. Attach and copies also require interactive selection;
see [attach and file transfer](container-attach-copy.md). Guarded mutations have
their own review workflows; plugins remain a later task.
The shared policy rejects effectful commands in read-only mode.

## Completion

The dedicated `:` bar shows the selected prefix match as an inline suggested
suffix in muted italic styling. Up/Down cycle up to eight local candidates;
there is no dropdown. The suffix is display text until accepted. Tab accepts it
for editing; Enter after Up/Down accepts and submits the selected candidate once.
Enter without arrow selection submits the typed text, so bare `:ns` opens the
namespace table and `:ctx` opens the context picker. Editing the query, leaving
the input or changing scope discards prior arrow selection. Matching ignores
case; the accepted context name retains its original case. At 40×12 the native
one-line input scrolls horizontally with its cursor.
Inputs/candidates are bounded to 256 characters; only the suffix that fits in the
remaining input width is visible. Empty input retains its placeholder. Suggestions
never resize the bar or cover resources. Right moves the editing cursor rather
than accepting a completion.

Candidates come from local command aliases, the current client's discovered
resource catalogue, the loaded kubeconfig catalogue and
the active session's namespace cache. Typing, selecting and accepting suggestions
does not authenticate or make API requests. A context switch immediately drops
the old namespace candidates. When namespace listing is denied, only the known
current namespace and `*` are suggested; enter a permitted namespace directly.
Disconnected/connecting sessions have no namespace suggestions.

Tab moves focus when no candidate applies. Shift+Tab always moves focus backward.
Moving the input cursor away from its end hides suggestions; returning to the end
restores applicable candidates. Escape leaves the input and clears command text;
filter text remains until Escape in the table. Help restores the prior focus.

## Filters

Press `/` outside an input. Plain text performs case-insensitive literal matching
across namespace, name, readiness, status and restart count. `re:PATTERN` selects
case-insensitive Unicode regex matching with the `regex` package's VERSION1
dialect. For example, `api` finds matching names and `re:api|worker` matches either.
Age is excluded because it changes continuously. These are local filters over
the current snapshot, rather than server-side label/field selectors.

Filtering updates while typing and continues through live pod changes. Enter
returns to the table; Escape there clears the filter. Status reports visible/total
counts. A valid filter with no matches shows **No pods match this filter**.
Invalid or excessive regex patterns show a clear error and all current pods;
they never masquerade as a successfully empty scope.

Queries are limited to 256 characters. Matching runs off the UI loop, with a total
50 ms regex budget per snapshot; a timeout discards partial results and reports
the error. The engine releases the GIL during matching and supports an actual
match timeout. Cancellation awaits the owned worker. Scope/query identity guards
reject late results; rapid input coalesces into the latest render request.
Fuzzy/inverse matching, label/field selectors and saved filter history are B07.
Maximum-workload latency and memory qualification remain Q01, rather than a
performance claim from these bounds.

## Navigation history

Alt+Left / Alt+Right, or `:back` / `:forward`, restore context, namespace, filter,
sort direction/column, selected pod UID and viewport. History retains at most 32
states in each direction for this invocation. New manual navigation clears the
forward stack. Missing/deleted UIDs use the table's deterministic row fallback.
History can return from a failed context; authentication/read failures remain
visible. Restoring a context owns a new connection and cancels the previous watch.
Only the matching revision can restore a saved viewport. History is not persisted,
and namespace favorites/last-command recall remain B07.

## Verification

```sh
uv run pytest tests/unit/test_navigation.py tests/unit/test_filtering.py tests/ui/test_navigation.py
uv run pytest tests/terminal/test_navigation.py tests/packaging/test_distribution.py
```

The command grammar and deterministic navigation domain enforce 100% line/branch
coverage. Pilot exercises actual loopback HTTP sessions, input focus, cached
literal completions, no keystroke I/O, small screens, stale scopes, filter errors,
history restoration and exit during a blocked owned worker. Real PTYs exercise
rapid Tab/Enter input, filters, scope commands, history, resize and terminal
restoration. The same trial runs against freshly installed console/module entry
points outside the checkout. Disposable-kind qualification exercises real regex
filtering, namespace completion and restored selection/sorting.

Sources: [Textual Input](https://textual.textualize.io/widgets/input/),
[bindings](https://textual.textualize.io/guide/input/#bindings),
[queued callbacks](https://textual.textualize.io/api/message_pump/#textual.message_pump.MessagePump.call_later),
[regex timeout and threading](https://pypi.org/project/regex/).

Measured delivery evidence and unavailable platform checks:
[B03 acceptance](acceptance/B03.md).

Namespaces share these filter bounds for name/status. See [workspace layout, live namespaces and Escape routes](resource-workspace.md).
