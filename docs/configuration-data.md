# Inspect configuration data deliberately

This workflow is implemented in the source checkout for the next release.
The published 0.1.0 package keeps ordinary inspection redacted and does not
include this data view or Secret manifest editing.

Open `:cm` or `:secrets`, select a row, then press Enter or `v`. The data view
shows key names, storage fields, text/binary classification and decoded byte
counts. Values start hidden, including ConfigMap values. The header identifies
the captured context, namespace and resource. `d` and `y` in the resource table
continue to open ordinary redacted details and YAML.

| Control | Result |
| --- | --- |
| `r` or Enter on a key | Reveal the selected value; press `r` again to hide |
| `x` | Toggle decoded UTF-8 and Base64; hide the previous value |
| `Ctrl+Y` or Copy | Copy the selected representation explicitly |
| Shift+R or Reload | Read current key metadata; clear any displayed value |
| Escape or Back | Close the view and return to the resource table |

Changing the selected key hides the previous value. Binary data can be revealed
or copied as Base64; decoded mode refuses invalid UTF-8. Base64 is an encoding,
not encryption. A malformed stored value produces a content-free error.

Every reveal and copy performs a fresh GET using the captured client, UID and
resource version. A changed object requires Reload before disclosure; a replaced
object or changed context/scope requires selecting the resource again. Read-only
mode allows deliberate reads and copying but blocks editing. Kubernetes read
permissions still apply: a denied GET cannot fall back to cached table values.

## Limits and local disclosure

The data view accepts up to 1 MiB of decoded data across at most 4,096 keys, and
at most 2 MiB of serialized resource data. A preview displays at most 16,384
characters and visibly reports truncation. Clipboard output is limited to
64 KiB of UTF-8 bytes; it is never silently truncated. Terminal controls are
escaped in the preview. Explicit clipboard output contains the selected original
text or Base64, sent through Textual's OSC52 support. Your terminal must allow
clipboard writes; copying is a local disclosure and does not prove clipboard
receipt on every terminal, SSH client or multiplexer.

Ordinary details, YAML, diagnostics and write receipts retain redaction. Built-in
SVG screenshot export is refused while the configuration data view is open,
including when values are hidden. Closing clears the view and drains owned reads
before disconnecting its client. This does not erase terminal scrollback,
clipboard history, external screenshots or process memory securely.

## Edit a ConfigMap or Secret

Close the data view and use Shift+E or `:edit` on the resource table. Explicitly
acknowledge that the trusted local editor receives the full manifest, then use
Editor, Validate and a separate Apply. The review stays redacted. Drafts have
private permissions and are removed on graceful close. Identity, resource-version
conflicts, read-only mode and server authorization use the same guarded workflow
as other manifest edits. Immutable fields and immutable Secrets/ConfigMaps remain
subject to server rejection; there is no forced overwrite or automatic retry.

The editor accepts one UTF-8 JSON-compatible YAML document of at most 1 MiB;
a large encoded manifest can exceed that bound even when its decoded values fit
the inspection limit. See [manifest editing](editing.md) for editor selection,
validation, cancellation and cleanup limits.
