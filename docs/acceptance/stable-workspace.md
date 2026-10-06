# Stable workspace and inline command bar

Focused preview correction [#127](https://github.com/carloshm91/kubetrol/issues/127)
supersedes the earlier dropdown preference in B07. The original Python/Textual
implementation keeps identical frame boundaries and header columns across pods,
namespaces, containers and logs at a fixed terminal size. The dedicated `:` bar
uses a styled inline completion suffix; there is no overlay.

Pilot tests assert actual regions across the full route at 40×12, 60×18, 100×30
and 180×50, including mouse focus/Pause clicks, resize round trips, search,
fullscreen and Escape. Existing navigation tests cover literal Enter versus
deliberate cycling/Tab, cached suggestions without per-key requests, stale
scope/context choices, history and retained UID selection/viewport.

The implementation uses the pinned native Textual Input suggestion renderer
through a narrowly documented field boundary. Empty input keeps its placeholder;
long suffixes display only within the available width. Broader resource
navigation and configurable hotkeys remain #61/#57.

Measured qualification results and actual synthetic captures are recorded below
once the complete candidate passes. Reference screenshots remain local/private.
