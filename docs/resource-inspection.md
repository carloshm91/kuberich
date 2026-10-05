# Inspecting a pod

Select a live pod row, then press `d` for details, `y` for YAML, or
`e` for its related events. The viewer shows the captured context, namespace and
resource name. These actions work in read-only mode and make only API reads.

The buttons and `y`/`d`/`e` switch pages. Arrow keys, PageUp/PageDown and the mouse
scroll the text; horizontal scrolling retains long lines. `m` switches to YAML
and toggles `metadata.managedFields`. Press `/`, type literal text and Enter to
select the first match; `n`/`N` move through matches. Search is case-insensitive,
uses character positions for Unicode and lists at most 10,000 matches. An empty
query or a query longer than 256 characters produces no matches.

`Ctrl+Y` or Copy copies the selected redacted text, or the current page when
there is no selection. Textual sends OSC52 to the terminal; the terminal must
support and permit clipboard writes. This establishes local terminal output,
not the separate native clipboard, SSH and tmux qualification in B07/Q02.
`Ctrl+C` retains the application's quit behavior. Escape leaves search first,
then closes the viewer. Back closes it directly. Returning retains the table's
filter, sorting, UID selection and viewport while live updates continue.

## Identity and errors

Opening captures the owned client, session generation and resource UID before
any await. An individual API GET must return the same name and UID; the table's
cached manifest is not a fallback for a denied or missing GET. Events use the
same captured client and namespace, with bounded paginated core/v1 reads. Only
records referencing the captured UID and namespace are included; name equality
alone never associates an old pod's events with a new pod.

A 403 states that read permission is denied; a 404 states the resource/API is
unavailable. An events error leaves YAML and details usable. Missing events
means none were returned for that UID, not that the pod has never had events.

The viewer is a captured inspection snapshot. Reopen it to refresh; automatic
viewer refresh remains U06. Live updates to the same UID continue underneath.
Deletion, same-name recreation, scope changes and client replacement invalidate
the viewer, clear its text and prevent copying. Closing cancels and awaits
owned reads; serializer cancellation also drains its background thread.

## Ordinary-view redaction

YAML retains Kubernetes field names and values outside the documented redaction
policy; derived table columns never become manifest fields. Pod details present
metadata, scheduling, normal/init containers, volumes and status evidence.
They are an original resource summary, not an invocation of `kubectl describe`.

Ordinary views and clipboard content hide Secret/ConfigMap payload values,
inline environment values, command/argument arrays, annotation values, sensitive
key names and recognized credential text. Managed field managers, operation,
time and other metadata remain available when enabled; `fieldsV1` sets are
hidden because set keys may embed literal values. Secret references retain safe
identifiers where possible. There is no reveal-sensitive-data action in B04.
The resulting YAML is an inspection document and may contain redaction markers;
it is not an apply/edit export.

Free text is additionally sanitized for known credential patterns and terminal
controls. Arbitrary unlabelled sensitive prose cannot be identified reliably;
fixtures deliberately verify the supported policy rather than claiming a
universal secret detector. TextArea displays plain text, so Rich markup in a
resource or event remains literal.

Individual text fields are limited to 65,536 characters, documents to 262,144
characters and nesting to 64 levels. Oversized documents fail explicitly instead
of producing partial YAML. Oversized related-event output reports its limit
while retaining resource details. Transport, collection count and memory bounds
remain those of the resource reader.
