# An everyday cluster workflow

This walkthrough connects the main views into one practical session: find a
workload, inspect a pod, read a container's logs, and return to your resource table.
Optional write-mode steps explain shells and reviewed workload changes.

Every name here is fictional. `demo-lab` is a kubeconfig context, `demo-apps` is a
namespace, and `demo-api` is an example Deployment. Substitute an explicitly
intended context, namespace and resource. The walkthrough does not create them.
Screenshots use synthetic resources or owned disposable test clusters.

## Before opening the workspace

Complete [installation](installation.md) and verify the installed entry point:

```sh
kuberich --version
kuberich --help
kuberich config check
```

These commands run locally without contacting Kubernetes. `config check` validates
preferences without creating a file. KubeRich preferences and Kubernetes
connection configuration are separate: `--config` selects application preferences;
`--kubeconfig` selects Kubernetes connections.

Use a trusted kubeconfig and its declared authentication helpers. If your provider
requires login, establish the intended session first; see [EKS](eks-authentication.md),
[AKS](aks-authentication.md) or [other credentials](kubeconfig-interoperability.md).
The Kubernetes API remains authoritative about your permissions.

## Open an explicit read-only session

```sh
kuberich --kubeconfig /absolute/path/to/kubeconfig \
  --context demo-lab --namespace demo-apps --readonly
```

The header identifies the selected context and namespace, connection state and
installed version. The main table reports its resource synchronization separately.
A connected session can still have a denied or temporarily stale resource view.

Read-only mode permits browsing, inspection and logs. It blocks effectful actions,
including shell launch, attach, new port forwards and resource writes. It is an
application policy; Kubernetes RBAC still controls access.

If the table is empty, first check the namespace and filter. An empty successful
list differs from **Permission denied**, **Auth error** or retained **Stale** data.
Use [troubleshooting](troubleshooting.md) for those states.

## Choose a context or namespace

1. Type `:ctx` and press Enter to open the local context table. Browsing it does
   not authenticate. Select a context with arrows or `j`/`k`; Enter connects.
2. Type `:ns` and press Enter to open the namespace table. `/` filters its rows.
   Enter selects the namespace and opens pods there.
3. Use `:ns demo-apps` to choose an exact namespace directly, including when you
   cannot list all namespaces. `:ns *` selects all namespaces that your API
   permissions allow you to read.

The bordered command bar completes inline. Tab accepts the suggested suffix for
editing. Up/Down chooses among candidates; Enter after that choice accepts and
submits it. Bare `:ns` and `:ctx` still open their tables.

Escape first leaves an input, then clears an active filter, then returns through
the workspace trail. [Commands and navigation](command-navigation.md) documents
completion, aliases and history in detail.

## Find and inspect a pod

Open `:pods`. Press `/`, type `demo-api`, then Enter to return focus to the table.
The filter matches displayed fields locally; it does not add a server selector.
`re:api|worker` uses the supported bounded regular-expression filter.

Use arrows or `j`/`k` to select a pod. `g` selects the first row; Shift+G selects
the last. PageUp/PageDown moves through the viewport. On the pod table, `s`
cycles sorting and Shift+S reverses its direction. The view retains selection
by resource identity while live updates arrive.

| Key | View | What to inspect |
| --- | --- | --- |
| `d` | Details | Scheduling, container state, restart reasons and specification |
| `y` | YAML | The captured manifest with ordinary-view redaction |
| `e` | Events | Events associated with this exact resource identity |

In an inspection viewer, `/` searches literal text and `n`/Shift+N moves between
matches. Escape leaves search before closing the viewer. Reopen to refresh the
captured snapshot. Copy transfers redacted text through terminal clipboard support;
it depends on your terminal's configuration.

Return to the pod table with Escape. Your filter, selection and viewport remain.
See [resource inspection](resource-inspection.md) for identity checks and redaction.

## Move from pod to container to logs

Press Enter on the selected pod. The container table shows names, types, state,
readiness, restarts, images, probes, declared ports and CPU/memory requests/limits.
Those CPU/memory values are specification values, not measured live usage.

Select a container and press Enter or `l` to read its logs. This stream uses the
captured pod UID and container, so a replacement pod does not silently inherit
the old selection. The container table itself is a snapshot; reopen it to refresh.

| Log control | Result |
| --- | --- |
| `/`, then `n`/Shift+N | Search retained text and move through matches |
| `p` | Toggle receiving new output |
| `f` | Toggle following the newest retained output |
| `g` / Shift+G | Move to the beginning / end of retained history |
| `w` / `t` | Toggle wrapping / displayed timestamps |
| Escape | Leave search first, then return to containers |

Receiving and following are separate. When reception continues and follow is off,
you can read earlier lines while new lines arrive within the bounded buffer.
History can be evicted at its limits; this is not an unlimited log archive.

Shift+L on a supported pod/workload row opens aggregate logs. Its source selector
and identity labels distinguish containers and pods. See [log controls](log-viewer.md)
for previous-container logs, time windows, aggregation, copy and file export.

## Open an embedded shell deliberately

Quit the read-only invocation with Ctrl+Q. When you intend to run a remote program,
start a separate write-mode session using the same explicit scope:

```sh
kuberich --kubeconfig /absolute/path/to/kubeconfig \
  --context demo-lab --namespace demo-apps --write
```

Select a pod, press Enter, select its container and press `s` or `x`. Shells need
local `kubectl`, API permission for exec, a running container and an available
configured shell. They open inside the Textual workspace with a captured-target
heading. Opening a shell allows arbitrary commands under the container's identity.

Ordinary keys now go to the remote program. `exit` or Ctrl+D ends the shell and
returns to containers. Ctrl+] closes the owned session. Ctrl+Q exits KubeRich.
Local history review suspends remote-key forwarding: Alt+PageUp opens it, `/`
searches, `v` selects a retained row and `y` copies redacted selection. Escape
returns from local review without sending those review keys to the remote shell.

These sessions have bounded history and terminal-protocol limits. See
[embedded shells](container-shell.md) and [terminal compatibility](terminal-compatibility.md).

## Review a workload change

In write mode, open `:deployments` and select the intended Deployment. `:rollout`
reads its progress and also works in read-only mode. For a deliberate change,
`:scale 3` opens a review of the selected workload's replica count.

Read the captured context, namespace, resource identity and intended effect.
Review prepares a change; it does not apply it. Cancel is the safe initial focus.
Choose Confirm separately to send the one-use request. A changed resource,
conflict, missing permission or policy restriction requires a new review.
Autoscaler ownership can block manual scale.

API confirmation establishes that the request succeeded, not that the rollout
completed. Use `:rollout` to observe progress. `:writes` retains recent outcomes;
an uncertain result means you must inspect the object before another attempt.
Leaving a confirmed operation does not undo it or repeat it.

[Workload operations](workloads.md) describes scale, restart and explicit-revision
rollback. [Manifest editing](editing.md), [annotations](mutations.md) and
[deletion/Jobs](resource-operations.md) describe their separate review flows.

## Finish the session

Return using Escape and the workspace trail, or `:back`/`:forward` for retained
navigation states. Use `?` to see actions for the current view. Ctrl+Q exits,
closes owned streams/processes/forwards and restores the terminal.

For a problem report, follow [troubleshooting](troubleshooting.md#report-a-problem)
and reproduce with fictional or disposable resources where possible.
