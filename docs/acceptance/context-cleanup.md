# Context edits and finished-pod cleanup: M08 #63

This adds explicit kubeconfig context rename/delete and a reviewed cleanup of
finished pods. It does not publish a package or change the 0.1.0 distribution.

## Context rename and delete

- The pure planner (`domain/kubeconfig_edit.py`) edits exactly one owning file.
  A name defined in several `KUBECONFIG` files, or set as `current-context` by
  a different file, is refused. Only the context entry changes; cluster and user
  entries stay. Duplicate target names and the connected context are refused.
- Deleting the file's `current-context` removes that key and needs the typed
  `DELETE CURRENT` confirmation; other deletes need `DELETE`. A rename of the
  file's current context renames `current-context` too.
- The file adapter (`adapters/kubeconfig_files.py`) rechecks the reviewed SHA-256
  before writing and again just before the replace. It writes a `0600` backup
  next to the file, writes a temporary file with the original mode, fsyncs both,
  replaces atomically and fsyncs the directory. A symbolic link stays a link;
  its target changes. A failed save removes its backup.
- The modal is Review → Confirm; Cancel and Escape save nothing. Read-only mode
  refuses both entry points. After saving, the context list reloads and a rename
  of the connected context reconnects with the new name.

The UI uses the context marked as selected in `:ctx` (the view's context) as the
connected one. That keeps the protection active while a connection is retrying.

## Finished-pod cleanup

`domain/cleanup.py` keeps `Succeeded` and `Failed` pods that are not already
terminating, sorted by namespace/name/UID, at most 100 per batch. `:cleanup`
opens the existing batch delete review with every listed pod preselected and
labelled with its state and UID. UID/resourceVersion preconditions and the
existing per-target revalidation apply unchanged.

## Evidence

Focused local run (Linux, CPython 3.12.12, Textual 8.2.8):

```sh
uv run pytest tests/unit/test_kubeconfig_edit.py tests/unit/test_cleanup.py tests/unit/test_view_actions.py tests/contract/test_kubeconfig_files.py tests/ui/test_context_cleanup.py --cov=kuberich --cov-branch
```

The new deterministic modules and the file adapter measured 100% line/branch
coverage. The eight UI tests drive rename with backup, current-context delete,
connected-context refusal with Cancel, read-only refusal, rename of the connected
context with Escape, a file changed after review, duplicate names, and cleanup
with a lost resourceVersion race against an owned API server.

Owned kind trial (kind v0.33.0, SHA-256 matching
[integration testing](../integration-testing.md); node and Alpine images pinned
in `scripts/owned_kind.py`):

```sh
uv run python -m scripts.verify_cleanup_kind --kind /absolute/path/to/kind --evidence artifacts/cluster/cleanup.json
```

It drives the real UI with an explicit temporary kubeconfig and passed these
checks: `running-pod-excluded`, `replaced-uid-refuses-batch`,
`finished-pod-deleted`, `changed-version-conflict`, `unselected-kept`,
`running-pod-kept`, `readonly-refused`, `caller-config-unchanged`. The owned
cluster was deleted afterwards.

## Debugging notes

The first UI tests hung during teardown. The modal stored its review task in
`self._task`, which is Textual's own message-loop task attribute. On unmount it
awaited its own loop. The attribute is now `_edit_task`. Two later failures were
test timing: Textual ignores a second click while a button's press effect is
active, so the tests wait `active_effect_duration` before clicking the same
button again.

## Limits

- The kubeconfig file is written again from parsed YAML. Comments and custom
  formatting are lost; Review warns when the file has comments.
- Kubeconfig files changed by other tools are not reloaded until restart.
- The kind trial runs on Linux only. macOS and the full platform matrix rely on
  the required PR checks.
