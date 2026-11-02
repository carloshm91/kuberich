# Edit and change a resource

Use a deliberate review before changing a selected resource. Start with an
explicit context and namespace in write mode. Server permissions and admission
policies still decide whether the change is allowed.

## Edit a manifest

Select a patchable row and use Shift+E or `:edit`. Lowercase `e` opens events.
The action needs an interactive selection; it is unavailable as a startup command.

1. Read and enable the local-disclosure checkbox. Your trusted editor receives
   the full manifest, including ConfigMap or Secret values. The displayed diff
   stays redacted separately from the real patch.
2. Choose **Editor**. Its argument list comes from `KUBERICH_EDITOR`, then
   `VISUAL`, then `EDITOR`, with `vi` as fallback. Quoted arguments work; shell
   expansion and pipelines are not executed by KubeRich.
3. Close the editor and check the diff and resource version. Formatting-only
   changes send no patch. Invalid YAML or an interrupted editor cannot enable Apply.
4. Choose **Validate** for a conditional server dry-run with strict field
   validation. Validation does not save the resource.
5. Choose **Apply** separately to submit the exact validated change once.

Cancel has default focus. Reopening the editor or changing input invalidates the
previous review. Unsupported dry-run or strict validation never falls back to
an unvalidated write.

The draft accepts one UTF-8, JSON-compatible YAML document of at most 1 MiB and
128 structural changes. Aliases, duplicate keys, unsafe tags, and excessive nesting
are rejected. API identity and server-managed metadata cannot change. `status`
and `metadata.managedFields` are omitted and cannot be edited through this form.

Draft directories use mode 0700 and files 0600. They are removed on graceful
close. KubeRich cannot erase editor backup/history files, terminal scrollback,
or bytes left by abrupt process death. Choose an editor you trust with the data.

## Change an annotation

Use `:annotate`, enter the key/value, and choose Review. Confirm is a separate
step. The review shows the exact target and annotation change. Other resource
data stays unchanged. Annotation keys follow Kubernetes naming rules; this form
limits values to 65,536 characters and combined annotations to 256 KiB.

## Inspect configuration data

Open `:cm` or `:secrets`, select a row, and press Enter or `v`. Key names, storage
fields, decoded sizes, and text/binary classification appear; values start hidden.

- `r` or Enter reveals the selected key; `r` again hides it.
- `x` switches decoded UTF-8 and Base64, hiding the preceding value.
- Ctrl+Y or Copy explicitly copies the selected representation.
- Shift+R or Reload reads fresh key metadata and clears displayed values.

Changing keys hides the previous value. Every reveal and copy performs a fresh
GET and checks UID and resource version. A changed object requires Reload;
a replaced object requires selecting it again. Binary data can be shown as
Base64; decoded mode refuses invalid UTF-8. Base64 is not encryption.

The view accepts up to 1 MiB decoded data, 4,096 keys, and 2 MiB serialized resource
data. Previews stop at 16,384 characters with a truncation notice. Copy accepts
64 KiB and never silently truncates. Explicit data copy contains the selected
text or Base64, so consider clipboard history and your terminal's access policy.
Application screenshot export is refused while this view is open, even with
values hidden. Ordinary details, YAML, logs, and results stay redacted.

Read-only mode allows deliberate reveal and copying but blocks editing. To edit
ConfigMap or Secret data, close this view and use the manifest workflow above.
Immutable objects and fields remain subject to server rejection.

## Read the outcome before retrying

`:writes` lists up to 32 recent operation records, including pending and uncertain
outcomes, without manifest or annotation values. Leaving a confirmed form does
not undo or resend the request. Context replacement and exit stop pending work;
a request already sent may still have changed the server.

| Result | Next step |
| --- | --- |
| Succeeded | The server response confirms the selected object |
| Blocked or stale | Select the current object and review again |
| Permission/authentication failure | Correct access or reconnect; the write is not replayed |
| Conflict or rejected change | Inspect the current resource and prepare a fresh review |
| Write outcome uncertain | Inspect server state before any new change |

Patches test UID and resourceVersion on the server. Concurrent modification or a
same-name replacement cannot be silently overwritten. Writes do not follow
redirects, refresh-and-replay a 401, or automatically retry network/server errors.
A lost response does not prove nothing changed. Read-only mode blocks these
changes before editor or write preparation. See [workload operations](workloads.md)
for scale, rollout, deletion, and Job workflows.
