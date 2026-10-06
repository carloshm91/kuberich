# Resource workspace

Preview feedback [#125](https://github.com/carloshm91/kubetrol/issues/125) adopts
the layout and keyboard workflow in the maintainer's K9s screenshots, using
original Python/Textual code. Local reference images are not distributed.

The default `k9s` theme has a black background, cyan tables/frames/selection,
yellow metadata labels/navigation, blue shortcut keys and white headings.
Explicit Textual themes remain supported. Select it for one invocation:

```sh
KUBETROL_THEME=k9s uv run kubetrol
```

The top header shows context, cluster/user **aliases**, namespace, connection
state and installed application version, without credentials. View-specific
shortcuts show implemented pod, namespace, container and log actions. Inputs sit
above resources. The dedicated `:` bar shows the selected completion suffix next
to typed text, in muted italic styling; it never opens a dropdown over resources.
Tab accepts it and Up/Down cycles the bounded local candidates. Plain Enter
submits literal input; Enter after deliberate cycling accepts that candidate.
Typing makes no API requests; suggestions still use the session name catalogue.

The bottom trail identifies the current view and Escape action. Escape first
leaves an input, then clears an active filter, then returns to the parent view.
Pods, namespaces, containers and logs share the same frame margins, header
columns and reserved interaction/footer rows at a fixed terminal size. Clicking
controls or changing focus does not move that frame. View actions change while
their header columns retain a fixed row count. Container/log views retain captured
pod identity and parent viewport. Embedded
shells retain their existing target frame, remote-key routing and cleanup.

## Live namespaces

Bare `:ns`, `:namespace`, `:namespaces`, `n` or F3 open a normal workspace table.
It reads real Namespace objects through the owned per-session LIST/WATCH service.
NAME/STATUS/AGE columns use UID selection and ascending name order; unknown
status/time appears as `Unknown` / `—`.

- `/` filters name/status using the same literal and bounded `re:` syntax as pods.
  Enter returns to the table; Escape there clears the filter.
- Enter opens pods in the selected namespace. The namespace filter does not
  filter pods. Escape from the unfiltered pod table restores the namespace
  filter, UID selection and viewport.
- `0` or **All namespaces** opens all pods. It is a scope action, not a fabricated
  resource row with a fake UID.
- `j/k`, arrows, PageUp/PageDown and `g/G` navigate namespace rows.
- `:ns NAME`, `:ns *`, `:po NAME`, `:po *` still select pods directly. A pod filter
  stays active when changing scope from the pod view.
- `:po` opens pods in the current scope. `:back` / `:forward` retain resource kind,
  context, namespace, filter and viewport.

Only the active resource is watched. Switches invalidate old results, await old
watches/projection/filter workers and clear obsolete navigation targets. Denied
listing is an error rather than an empty table; directly entering an allowed
namespace still works. Temporary failures retain the last snapshot with stale
status. Recreated namespaces have distinct UID selection.

Inspection uses existing captured-UID details/YAML/events services. Logs and
shells require a pod; namespace mutations remain planned.

## Sizes and remaining work

At 70+ columns the header uses six rows. Narrow terminals use four rows, omitting
cluster/user aliases and the logo. Below 16 rows the three-row context/namespace/
state header preserves room for resources/inputs. Container hints and log controls
remain available; help contains secondary shortcuts. NO_COLOR retains textual cues.

`--headless` hides the shortcut/logo header, `--logoless` hides its brand and
`--crumbsless` hides identity/navigation bars. Log `z` hides the header/route and
frame, preserving search, controls and stream ownership.

The header shows the actual installed development version. Optional real release
notices and custom/live/context themes remain [U01 #56](https://github.com/carloshm91/kubetrol/issues/56).
Kubernetes-version/CPU/memory presentation belongs to [O01 #68](https://github.com/carloshm91/kubetrol/issues/68)
and [O02 #69](https://github.com/carloshm91/kubetrol/issues/69).
Stable geometry and inline completion are the focused correction
[#127](https://github.com/carloshm91/kubetrol/issues/127). Broader navigation/clipboard
qualification remains [B07 #61](https://github.com/carloshm91/kubetrol/issues/61). This preview does not
establish full K9s parity.

Behavior references: [K9s commands](https://k9scli.io/topics/commands/),
[K9s skins](https://k9scli.io/topics/skins/),
[Textual themes](https://textual.textualize.io/guide/design/).
