# Container attachment and file transfer

Use the intended context and namespace explicitly:

```sh
kuberich --context YOUR_CONTEXT --namespace YOUR_NAMESPACE --write
```

Select a pod and press Enter to view its containers. Regular, init and already
existing ephemeral containers are listed; the selected container must be running
for attach or copy. Creating a debug container remains a separate feature.
The table retains its selection and the preceding pod viewport on return.

## Attach to an existing process

`:attach` opens the selected pod's container table. Press `a` on the intended
container to connect to its existing main process inside the terminal workspace.
Its stdin and TTY configuration determine the available interaction. `s` / `:shell`
opens a new configured shell through exec instead.

| Key | Effect |
| --- | --- |
| Ctrl+P, then Ctrl+Q | Send kubectl's detach sequence and return to containers |
| Ctrl+] | Close the owned local attach session and return to containers |
| Ctrl+C | Forward interruption to the existing remote process |
| Ctrl+Q alone | Quit KubeRich and clean up its local processes |

The frame identifies the captured context, pod, container and controls. Local
close/detach does not request pod deletion. Interrupting the main process can
affect the workload. EOF/error/interruption preserves its subprocess status and
returns a fixed diagnostic; raw kubectl output is not copied into persistent
workspace diagnostics.

Read-only mode blocks attachment before pod reads or process creation. The account
needs pod read and `pods/attach` permission. UID and running-state checks refuse
missing, replaced, deleting, ambiguous or finished targets.

## Review an upload or download

`:upload` and `:download` open the selected pod's container table. Press `u` for
upload or `d` for download on the intended container. These commands need an
interactive selection and cannot be used as a startup `--command` action.

1. Enter an **absolute local path** and **absolute remote path**. Both identify the
   exact file or directory; no destination directory is silently substituted.
2. Leave overwrite unchecked to refuse an existing destination. Check it only to
   review replacement of an existing regular file. Directory merges, replacing a
   directory, links and special-file destinations are refused.
3. Choose **Review**. Upload preparation makes a private source snapshot and shows
   its measured bytes/entry count. Download preparation opens and retains the
   explicit destination parent; remote size remains unknown and shows the limits.
4. Check the captured context, namespace, pod UID, container, paths, size and
   overwrite effect. **Cancel is the default focus**. Enter on a path prepares the
   review. Choose **Confirm** separately to start one transfer.
5. The result states completion or an incomplete/cancelled outcome. Back/Escape
   returns to the retained container table.

Changing fields invalidates confirmation. Files copied from the upload snapshot
are unaffected by later source edits. Observed source changes during preparation
are refused; an ordinary filesystem cannot provide a transaction across every
file in a concurrently edited tree. Local source/destination ancestors cannot be
symlinks; use their real absolute paths. Sources and downloaded regular files
exclude hard links and special files. Private downloaded files use mode 0600 and
directories 0700; remote upload uses `kubectl cp --no-preserve`.

The container needs **tar**. Uploads also need a silent POSIX **test** command on
PATH and an existing destination parent. Local kubectl must be installed on the
captured PATH. Local tar is not required. Every command uses a literal argument
vector with the captured private kubeconfig, context, namespace and container.
Retry count is zero, avoiding kubectl cp's remote shell retry pipeline.
A failed exec/path check is never treated as proof of a missing destination.

## Download protection and limits

Downloads stream an uncompressed tar archive into an owned private directory.
The wire stream is bounded to 528 MiB, payload to **512 MiB**, entries to **2,048**,
path depth to **32**, and extended metadata to **64 KiB per header / 16 MiB total**.
The entry limit includes implicit parent directories. Only ordinary PAX path,
size, time, ownership and text fields are accepted; unknown/sparse extensions
are refused before the tar parser can expand them. The operation
has a five-minute process deadline and an 8 MiB output mailbox; a stalled consumer
or excessive error output refuses the copy. Compressed/sparse archives, traversal,
absolute/unrelated/duplicate paths, case-folded collisions, symbolic/hard links,
special files and malformed/trailing data are refused before publication.

Extraction creates only regular files/directories beneath the private staging
root. Local operations retain no-follow directory descriptors. New file commits
are exclusive; explicit replacement rechecks the reviewed file identity. A new
directory is exclusively reserved and populated after complete validation; its
publication is not a filesystem-wide atomic rename. Existing directories are
never merged. Failed publication cleans known copied entries through its owned
directory descriptor; a concurrent replacement is retained. Concurrent additions
or renames can leave an empty owned reservation or copied entries at changed
paths. Inspect the destination and those changes after a directory failure.
Concurrent local changes detected before publication require a fresh review;
explicit replacement cannot provide a POSIX compare-and-swap against all possible
same-user changes at the final rename boundary.

Read-only mode permits an explicit download and blocks uploads before source
snapshotting or process launch. Kubernetes still requires pod read and
`pods/exec` permission for the tar transport; application read-only is not RBAC.

## Cancellation and remote outcome

Cancel/Escape/context replacement/exit stop and drain owned local work before
private files and the selected client are removed. Downloads retain the existing
local destination and remove the partial private archive. Pending publication
receives cooperative cancellation; a commit that finished before cancellation
is reported as completed during cancellation, rather than claiming no file changed.

An interrupted upload can leave partial **or completed** files in the container.
KubeRich reports that uncertainty, sends no automatic retry, and does not delete
remote files. Inspect the explicit remote destination before reviewing a retry.
Remote exec processes can outlive a lost connection; local kubectl cleanup does
not promise to terminate the server-side process.

Kubernetes exec/attach has no UID precondition. The pod and container are checked
again before launch, but replacement can occur between that read and the server's
request. Remote path checks similarly cannot provide an atomic no-overwrite or
symlink precondition across a concurrently modified container filesystem. Use
intentional destinations and review explicit replacement carefully.

See [shells](container-shell.md), [connection setup](context-sessions.md),
[credential transport](kubeconfig-interoperability.md), and the
[S07 verification evidence](acceptance/container-transfers.md).
