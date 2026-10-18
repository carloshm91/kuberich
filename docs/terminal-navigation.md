# Terminal navigation and remote clipboard

These features are in the source checkout for the next release. Published 0.1.0
packages retain their original behavior. No new account or hosted service is
required.

## Keys belong to the focused view

| View | Movement | First / last | Pages | Half pages | Horizontal | Other owners |
| --- | --- | --- | --- | --- | --- | --- |
| Resource and namespace tables | j / k | g / G | Ctrl+F / Ctrl+B | J / Ctrl+U | h / Alt+L | l logs; n namespaces; Ctrl+D deletion review; Ctrl+Y copy name |
| Context/container and other selectors | j / k | g / G | Ctrl+F / Ctrl+B | J / Ctrl+U | h / Alt+L | Container s/x shell, l logs, a attach, u/d transfer; selectors retain their actions |
| Details, YAML, events | j / k | g / G | Ctrl+F / Ctrl+B | Ctrl+D / Ctrl+U | h / l | y/d/e pages; m managed fields; n/N search matches; Ctrl+Y copy |
| Help | j / k | g / G | Ctrl+F / Ctrl+B | Ctrl+D / Ctrl+U | h / l | Escape returns to the prior view |
| Logs | j / k | g / G | Ctrl+F / Ctrl+B | Ctrl+D / Ctrl+U | h / l | n/N search; Ctrl+Y copy; existing follow/pause/window/source actions |
| Command, filter, search or editor input | Native editing | Native editing | Native editing | Native editing | Native editing | Printable letters stay literal; Tab in commands deliberately completes |
| Embedded shell | Remote program | Remote program | Remote program | Remote program | Remote program | Ctrl+] returns locally; Ctrl+Q quits; remote keys take precedence |

Capital `G` is one uppercase character. Neither Vim numeric counts nor a complete
Vim grammar is implemented. Arrows and PageUp/PageDown remain available.
Table Home/End move horizontally; Ctrl+Home/Ctrl+End and g/G select whole-view
edges. TextArea Home/End retain line boundaries; g/G move to document edges.
Configure the independent `text` profile, `logs` profile or table profiles in
[navigation preferences](navigation-preferences.md). Text and log profiles do
not inherit common table overrides.

## Command and filter recall

Alt+Up/Alt+Down recall at most 32 submitted entries and restore the unfinished
draft when moving forward past the latest entry. Command and root-filter
histories are separate and memory-only. Up/Down in the command bar keep their
existing suggestion-cycling behavior. `:!!` repeats the last accepted command
through normal policy, target checks and review; it never approves a mutation
or a local plugin automatically. Launch `--command` refuses these selection and
recall controls before authentication; use them interactively.

Alt+Left/Alt+Right and `:back`/`:forward` retain the separate scope/view history.

## Additional local filters

Use `/` to enter one filter family at a time:

| Query | Meaning |
| --- | --- |
| `api` | Case-insensitive literal substring of visible resource search fields |
| `re:api\|worker` | Unicode regular expression |
| `!re:api\|worker` | Inverse regular expression |
| `fuzzy:apwrk` | Case-insensitive ordered subsequence; retains normal table sorting |
| `label:app=api,tier in (frontend,worker),!debug` | Local label AND terms |
| `field:metadata.name=api` | Local allowlisted field equality |

Labels support `=`, `==`, `!=`, `in`, `notin`, existence and `!` absence. Missing
keys match inequality/notin and absence. At most eight terms and 256 query
characters are accepted. Field selectors accept equality/inequality only.

The deliberate field subset is metadata.name/namespace for API resources;
status.phase and spec.nodeName/schedulerName/hostNetwork for Pods;
spec.unschedulable for Nodes; and status.successful for Jobs (mapped to the API
status.succeeded value). Omitted booleans default to false; omitted Job succeeded
counts default to zero. Arbitrary JSON paths, annotations and Secret data are
excluded. These are filters over the owned snapshot, not server-side selectors
or a claim to implement every kubectl field selector. No per-keystroke API calls
are made. Plain/regex/fuzzy filters do not decode manifests. Metadata filtering
runs in an owned worker with a 250 ms total budget and a one-snapshot cache;
regular expressions retain their independent 50 ms total deadline. Invalid or
timed-out queries retain all rows with a visible error, never partial matches.

`:errors` toggles resources with observable failures or unready conditions.
Unknown health is omitted and counted separately; it is not presented as healthy.
Completed successful Pods remain successful despite historical restarts. A CRD
without understood health conditions can be unknown. This is a local observation,
not a replacement for alerts or provider-specific health evaluation.

## Wide columns and marked rows

`:wide` temporarily expands the current resource's available fields. Pods gain
Node, IP and QoS. Turning wide off restores the configured layout; the toggle
does not save or replace preferences. Typed sorting and stable UID selection
continue to apply.

Space toggles a visible resource mark. Shift+Up/Shift+Down extend a range in the
current filtered, sorted order. `:mark`, `:range`, `:selectall` and `:selectnone`
provide alternatives when terminal modifiers are unavailable. Selection is
bounded to 100 UIDs, pruned when rows disappear from the filter, and cleared on
scope changes. Same-name replacement objects never inherit an old UID's mark.
`:deletebatch` reviews the marked rows when marks exist, otherwise the bounded
visible rows as before. Existing confirmation, UID checks, default Cancel and
read-only restrictions remain in force.

## Namespace favorites

`:favorite add team-a` or `:favorite remove team-a` explicitly saves a namespace
under the captured context in the preference file. There are at most 64 names
per context and 128 contexts. No kubeconfig or cluster mutation is made.
`:favorites` shows the ordinary namespace workspace filtered to those favorites;
`:ns` shows all namespaces again. Favorites do not fabricate API rows or grant
namespace-list permissions.

```yaml
schema_version: 1
navigation:
  schema_version: 1
  mouse: false
  favorites:
    demo-lab:
      - team-a
```

Mouse reporting is disabled by default. Set `navigation.mouse: true` and restart
to opt in. Keyboard alternatives remain available for every operation. Pilot
semantic clicks are a widget test mechanism, not proof that physical mouse
reporting is enabled in an ordinary launch.

## Consistent workspaces and nested commands

Details/YAML/events and help share the workspace header and frame. The captured
resource remains explicit; inspection content is still a read snapshot. Container
lists now refresh readiness, restart counts and waiting/running/terminated state
from the existing Pod watch, preserving selection by container name and viewport.
Long container feedback stays scrollable in the bottom status area; use Tab to
focus it and arrow/page keys to read the full message.
No separate watch is opened for each container list. Deletion, replacement UID,
namespace/context change or fatal permission loss invalidates the old screen;
covered logs/shell work is closed and drained before client replacement. Late
worker results cannot make that old screen current again.

Container, resource inspection and log views have their own bordered `:` bar.
Typing `:` inside an input stays literal. Invalid/read-only commands retain the
view and its streams. Accepted scope navigation drains covered read owners before
switching; resource actions retain the originating UID instead of targeting a
hidden changed cursor. Local copy retains the captured view. Escape first leaves
a nested command/search input, then returns to the previous view. The embedded
shell continues to route keystrokes directly to the remote program.

`:headless` toggles the shortcuts/logo area; `:crumbsless` toggles identity/trail;
`:fullscreen` hides headers/trails/frame borders. Command, search and status stay
available. These are session controls and do not change saved preferences. The
existing log `z` toggle remains local to that log view; either fullscreen mode
can hide its header without overriding the other mode.

## Explicit clipboard writes

`:copy` copies visible selected resource names, `:copyns` their namespaces and
`:copytext` the bounded table text. Marked rows are used when present. Ctrl+Y on
the root table copies its selection's name. Existing inspection/log/review copy
actions retain redaction. Explicit Secret-value copying keeps its separate
reveal/copy policy; values are never included in a failure message.

`KUBERICH_CLIPBOARD=auto` (default) selects native plaintext on local macOS,
foreground-owned xclip on local X Window System, and OSC52 over SSH or without a native
session. `native` requires an available macOS and X Window System backend; `osc52` explicitly
selects the terminal. Native X Window System requires xclip on PATH and DISPLAY, and is not
selected for Wayland sessions. Native macOS uses the system osascript/AppKit
plaintext API; no Python clipboard package is needed. Missing auto helpers can
fall back to a bounded terminal request; forced-native failures are visible.

Native/headless copies accept at most 1 MiB UTF-8; OSC52 accepts at most 64 KiB.
Oversize or invalid UTF-8 is refused rather than truncated. The application only
writes clipboards; it never reads them to acknowledge a copy. Headless/Pilot
copies remain memory-only. Native X Window System keeps an owned selection process until
replacement or exit; persistence after exit depends on a clipboard manager.

OSC52 payloads are base64 framed, so copied escape sequences stay inert data.
Inside tmux the request uses tmux passthrough framing. A user-managed tmux server
must permit `allow-passthrough on` for its visible pane, and the outer terminal
must permit clipboard writes. KubeRich never changes a user's tmux server.
A sent request is not proof that a physical terminal accepted it. Clipboard
reads in qualification are limited to synthetic data already written on an
owned Xvfb display or explicitly owned ephemeral macOS runner.
