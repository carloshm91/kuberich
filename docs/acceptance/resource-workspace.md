# Resource workspace: preview feedback #125

[Issue #125](https://github.com/carloshm91/kubetrol/issues/125) delivers an original
Python/Textual workspace inspired by the maintainer's K9s layout references.
Private reference images and their cluster data are not distributed.

## Behavior under qualification

The built-in `k9s` theme, shared identity/version/shortcut header, top command and
filter inputs, and Escape trails apply to pod/namespace/container/log navigation.
Namespaces use real owned LIST/WATCH objects and UID selection, not a scope
picker. Enter opens pods; Escape restores the namespace query/selection/viewport;
`0` selects all pods. Existing embedded shell ownership and target framing remain.

Actual Pilot/API trials exercise 40×12, 60×18, 100×30 and 180×50 layouts,
namespace lifecycle/age, filtering, g/G, watch recreation, permission denial,
stale/empty states, bounded patch cancellation and late context results.
Real PTY and fresh-installed trials qualify rapid command typeahead,
namespace/pod routes, focus, Unicode, resize and terminal restoration.
Full-suite coverage/build evidence will be recorded after final completion;
earlier passing subsets do not establish a final qualification.

## Scope and delivery limits

The displayed version comes from the installed package. Real optional release
notices and custom/live themes remain #56; Kubernetes-version/CPU/memory display
remains #68/#69. Inline completion and broader terminal qualification remain #61.
This does not establish full K9s parity or universal terminal compatibility.

Hosted Actions remain subject to the account payment/quota block. Linux local
qualification follows the maintainer-authorized [temporary quality workflow](../quality.md#temporary-private-development-workflow-when-actions-is-unavailable).
macOS and full platform CI remain required before a public release.
Visibility, package publication, version `0.0.1.dev0` and tags are unchanged.
