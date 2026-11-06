# Save and browse local exports

Use `:export` to review a capture of the current resource, retained logs,
diagnostics or supported table. Use `:exports` to browse files saved locally.
These features are in development source for the next release; the installed
0.3.0 release predates them. Saving is available in read-only mode and does not
change Kubernetes resources. Nothing is uploaded automatically.

## Review and save

1. Open the source you want to retain, then type `:export`. In a log viewer,
   Ctrl+S opens the same review with the log format selected.
2. Choose an available format. Read its source, context, namespace, observation
   time, limitations and redacted preview.
3. Choose a directory and a filename. Press **Save** deliberately. An existing
   file needs a separate overwrite confirmation; Cancel is the default.
4. Read the outcome before leaving. A saved artifact includes source and export
   times independently; saving old evidence does not make it fresh.

The review captures its source before opening. Ordinary arriving log lines and
table updates do not silently replace that capture. Changing its context,
namespace, selected target or relevant source options invalidates the review.
Open a new review when you want a newer capture.

| Format | Captured content |
| --- | --- |
| Resource YAML | The selected Kubernetes object, or an already-redacted YAML inspection document |
| Logs | Output still retained by the log viewer, with its producing container/window and discard notices |
| Diagnostics | The retained finding and source collection, including provenance and incomplete states |
| Screen | The supported table or loaded document as literal text, with its filter and presentation metadata |
| Support | Inspectable JSON containing a safe application report and available diagnostic evidence; resource/log content is an explicit choice |

Resource export from a compact metadata row reads the full object explicitly.
Normal resource permissions apply. A replaced UID or changed reviewed resource
cannot silently become the export target. YAML already opened in the inspection
viewer stays a redacted document; exporting it does not fetch hidden values.

Single-container logs use the retained output from that actual container,
instance and window. Aggregate logs retain source identities and the current
source filter and plain/JSON mode. No export requests older or additional log
bytes. Rotation and history limits still apply; see [read logs](log-viewer.md).
While a container/window change drains its old reader, export is unavailable
until the new producing read has been established.

The container environment/image inspector exports metadata for its selected
section. Literal, inherited and derived values stay omitted, including after
an explicit reveal. Its capture remains tied to the same observation and
section; reloading or switching sections invalidates the review.

A diagnostic export includes the full retained collection. A screen export
reflects the filtered table instead. Neither action reruns native diagnostics
or an external tool. Source observation times, partial results and name-only
external references remain qualified; see [investigate failures](cluster-diagnostics.md).

Screen text is a data snapshot, rather than an image of the terminal. Supported
tables retain their column and row order. Arbitrary custom/server column values
are withheld. Revealed configuration values, plugin output and interactive
terminal contents are not screen-export sources. An unsupported view can offer
a safe support report without capturing its contents.

## Choose a location

Without an override, exports start in the platform state directory:

- Linux: `$XDG_STATE_HOME/kuberich/exports`, normally
  `~/.local/state/kuberich/exports`.
- macOS: `~/Library/Application Support/kuberich/exports`.

Opening the browser does not create this directory. The first explicit Save
can create the default directory privately. A different directory entered in
the review must already exist. KubeRich remembers the last successful location
for the current application session.

The launch option `--screen-dump-dir PATH` selects the initial export location.
It applies to exports, rather than the diagnostic log or clipboard. Choosing a
path does not save anything by itself. This override becomes the session default
and can also be created privately on the first explicit Save. Relative launch
paths are anchored to the launch directory; `~` expands to your home directory.
For example, with fictional local paths:

```sh
kuberich --screen-dump-dir /home/demo/private-exports --command exports
```

Use a physical directory owned by your user and not writable by other users.
Path components cannot be symlinks; traversal through `..` is refused. A
filename is a single local basename, not a path. Existing entries must be owned
regular files with one link. New files use mode `0600`; created directories use
`0700`. Filesystem ownership and permissions are checked again during use.

KubeRich stages writes in the destination directory and checks the reviewed
entry before replacing it. Same-user concurrent filesystem changes cannot be
made impossible by these checks. Refresh and review again when an entry changes;
do not repeatedly confirm an uncertain overwrite.

## Browse without connecting

Launch the local browser directly:

```sh
kuberich --command exports
```

This startup command does not connect to Kubernetes, invoke a credential helper
or start the optional release check. Existing local preferences and kubeconfig
parsing still apply: an explicitly missing or invalid input can fail before the
UI opens. Back returns to a disconnected workspace. Use `:ctx` and select a
context, or explicitly type `:retry`, when you want to connect.

Opening `:exports` from an already connected workspace keeps that connection;
artifact metadata never selects a context or issues a cluster request.

Choose a directory and use the filter for a literal match against filenames,
formats, contexts, namespaces and sensitivity labels. Select a recognized
artifact, then choose an explicit action:

- **View** opens a read-only, paged document. Previous/Next cover the full saved
  content, with at most 256 KiB displayed per page.
- **Copy text** requests a clipboard write. It copies the full prepared text,
  up to 1 MiB, rather than only the visible page. Terminal clipboard transports
  can have a smaller limit; see [clipboard setup](troubleshooting.md#clipboard).
- **Save copy** opens another review with a destination and overwrite choice.
- **Delete** names the selected local entry and requires confirmation. It
  deletes that file, not the Kubernetes resource described in it.
- **Refresh** reads local metadata again. Changed entries must be reviewed again
  before an operation can use them.

The browser scans at most 2,048 directory entries. Its filter searches only
the scanned entries, so a limited listing is not a complete directory search.
Unrecognized files are skipped. Symlinks, directories and unsafe entries are
never followed as artifacts. A malformed artifact cannot become executable
content, a context instruction or a link to open automatically.

Plain log files saved by the 0.3.0 Save dialog lack the new artifact header and
are skipped. They remain ordinary text files you can read with your text viewer;
new exports include the metadata needed by this browser.

## Keep disclosure deliberate

Default exports redact recognized credentials, Secret/ConfigMap values,
environment values and sensitive structured fields. Terminal controls and
untrusted markup are rendered as literal text. Structured content has depth,
node and field limits; invalid or excessive input is refused or visibly
withheld rather than presented as a complete safe structure.

Redaction cannot recognize every confidential phrase, resource name or business
identifier. Review an artifact before sharing it. Redacted YAML is an inspection
record; replacing live objects with it would replace hidden values too.

Sensitive output is offered only for a selected raw resource YAML source.
It needs its own acknowledgement and a fresh permission/UID/version check.
The acknowledgement binds that resource and destination once. It does not
authorize later resources, paths, overwrite choices or clipboard writes.
Sensitive exports require private filesystem permissions. Log, screen,
diagnostic and support formats have no raw-output reveal mode.

Saved YAML opens redacted even when it contains sensitive values. **View
sensitive**, copying sensitive content and saving a sensitive copy require
separate acknowledgements. A file's own sensitivity label is not trusted as a
reason to skip redaction. While raw values are exposed, KubeRich refuses its
application screenshot action, including beneath another overlay. External
terminal recording is outside that application control.

## Inspect a support bundle

A support bundle is ordinary inspectable JSON, with inline components and
visible omissions. It is not a recursive directory archive. By default it
contains the fixed safe application report and available diagnostic evidence.
Choose whether to include the supported resource/log capture in the review.
A metadata-only resource is omitted rather than fetched silently for support.

Bundles do not read kubeconfig files, environment dumps, arbitrary filesystem
paths or raw external-tool output. Opening or saving one never uploads it,
launches an external program or copies it to the clipboard. Inspect the JSON
locally and choose what you share.

## Handle limits and interrupted work

Artifacts have a 16 MiB total limit, including metadata. The schema-versioned
header has an 8 KiB limit. Large structured exports fail explicitly; they are
not silently truncated into a valid-looking complete record. The viewer pages
large accepted artifacts without loading them into an editable terminal.

Cancel before publication preserves the previous destination. If cancellation
arrives after the filesystem operation commits, the outcome can correctly say
that the export was saved. A durability or cleanup warning can accompany a
completed operation; read the outcome before trying again. Context replacement
and application exit cancel and drain owned export work before releasing its
source client. Local artifact operations do not need a live cluster.
