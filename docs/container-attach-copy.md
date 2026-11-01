# Transfer a file or directory

Copy between your machine and a selected container with an explicit review.
You need kubectl on PATH, `tar` in the container, pod read access, and `pods/exec`.
Uploads also need a POSIX `test` command in the container and an existing remote
parent directory. Local tar is unnecessary.

## Select the transfer

Open the pod's container table. Press `u` for upload or `d` for download on the
intended running container. `:upload` and `:download` open the container table from
a selected pod. These commands need interactive selection.

Read-only mode allows a deliberate download but blocks uploads. Downloads still
use Kubernetes exec permission; application read-only mode does not change RBAC.
For process attachment instead, see [shells and attach](container-shell.md).

## Review the exact destination

1. Enter absolute local and remote paths, identifying the exact file or directory.
   KubeRich does not silently substitute a destination directory.
2. Leave overwrite unchecked to refuse an existing destination. Enable it only
   for replacement of an existing regular file. Directory merging, links, and
   special-file destinations are refused.
3. Choose **Review**. Upload review reports the source snapshot's bytes and entry
   count. Download review shows limits because remote size is not yet known.
4. Check the context, namespace, pod UID, container, paths, and replacement effect.
   **Cancel** has default focus. Enter in a path only prepares review.
5. Choose **Confirm** separately to start one transfer.

Changing a field invalidates confirmation. A successful result states completion;
a failure or cancellation reports an incomplete or uncertain outcome. Escape
returns to the container table.

## Understand path and size limits

Use real absolute paths without symlink ancestors. Sources and downloaded files
exclude hard links and special files. Uploads use a private source snapshot, so
later source edits do not change the bytes sent. Changes detected while preparing
the snapshot are refused; a concurrently edited directory is not a transaction.

Downloads accept at most 512 MiB of payload, 528 MiB on the wire, 2,048 entries,
and 32 levels of paths. Extended metadata has separate limits. The process has a
five-minute deadline. Compressed/sparse archives, traversal, absolute or duplicate
paths, case-folded collisions, links, and malformed trailing data are refused.
Files are validated in a private staging directory before destination publication.
Downloaded files use mode 0600 and directories 0700.

New files cannot overwrite an existing path. Explicit file replacement rechecks
the file you reviewed. New directories are reserved and populated without merging;
publication is not one atomic operation across the entire directory. Concurrent
local renames or additions can leave copied entries at changed paths after a
failure. Inspect the destination before retrying.

Remote path checks cannot atomically prevent all concurrent replacement or
symlink changes in a container. Use an intentional destination and check the
reviewed replacement effect.

## Cancel or retry safely

Escape, context replacement, and exit stop local transfer work and remove partial
private downloads. An existing local destination stays unchanged until publication.
If publication finished before cancellation, the result says it completed during
cancellation rather than claiming nothing changed.

An interrupted upload can leave partial or completed remote files. KubeRich does
not retry or delete those files automatically. Inspect the remote destination
before reviewing another upload. A remote exec process can outlive a lost local
connection.

A stale or replaced pod requires selecting it again. Kubernetes name-based exec
has no atomic UID precondition despite the launch-time identity check. A permission
error or failed path check is not treated as proof that a destination is absent.
