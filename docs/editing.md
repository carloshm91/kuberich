# Edit a selected manifest

On a selected patchable resource, use `:edit` or Shift+E. Lowercase `e` still
opens events. This is an interactive action, rather than a startup `--command`.
The form captures context, namespace or cluster scope, name and UID. Cancel has
initial focus; `--readonly` refuses the action before a file or editor is opened.

1. Read and enable the local-disclosure checkbox. Your trusted editor receives
   the full manifest, including potentially sensitive values such as ConfigMap
   data. Secret manifests remain unavailable until their explicit reveal policy
   in C04 #55. The displayed diff is redacted separately from the real patch.
2. Choose Editor. Kubetrol reads the identified object and creates a private
   temporary directory (0700) and initial file (0600). The editor uses the native
   terminal and returns to the form. Its argument list comes from
   `KUBETROL_EDITOR`, then `VISUAL`, then `EDITOR`, with `vi` as the default.
   Quoted arguments are supported; shell expansion and pipelines are literal.
3. Review the diff and captured resourceVersion. Formatting-only edits send no
   PATCH. Failed or interrupted editors and invalid YAML cannot enable Apply.
4. Choose Validate. Kubetrol checks the captured object and sends the exact
   conditional JSON Patch with `dryRun=All` and `fieldValidation=Strict`.
   Successful validation does not save the object. Cancel again has focus.
5. Choose Apply separately. The exact validated change receives a one-use
   confirmation and fresh identity/version verification before one conditional
   PATCH. `:writes` retains its public outcome without manifests or data values.

Reopening Editor or validating again invalidates previous confirmation. A version
conflict requires closing the draft and opening a fresh edit of the current
object; Kubetrol does not overwrite, automatically merge or retry the old change.
A dropped or invalid Apply response can mean the write applied: inspect the
current object before another change. See [guarded changes](mutations.md).

Only one JSON-compatible UTF-8 YAML document of at most 1 MiB is accepted.
Aliases, duplicate/nonstring mapping keys, unsupported tags, nonfinite numbers,
excessive nesting and more than 128 structural changes are rejected. API version,
kind and server-owned metadata must remain unchanged. `status` and
`metadata.managedFields` are omitted from the draft and cannot be edited; labels,
annotations, finalizers, owner references and resource fields receive server
validation and authorization. Unsupported dry-run or strict validation does not
fall back to applying an unvalidated edit.

Escape/Cancel waits for owned preparation and file cleanup before returning to
the table. Context retry and exit drain workers before closing the captured API
client. An Apply already started remains owned by the mutation manager; leaving
the form removes its file while `:writes` retains the outcome. Draft reads refuse
symlinks, nonregular files and oversized output. Owned temporary files are removed
on graceful close; secure erasure, abrupt process death and backups/history
created by an external trusted editor are outside this cleanup guarantee.

Actual Kubernetes 1.36.4 dry-run, strict-field rejection, conflicts, replacement
UIDs and get-only RBAC are qualified on disposable kind. This does not certify
all server/admission versions, cloud providers or arbitrary external editors.
See [acceptance evidence](acceptance/editing.md) for measured scope.
