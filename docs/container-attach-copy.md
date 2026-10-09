# Container attachment and file transfer

S07 [#48](https://github.com/carloshm91/kuberich/issues/48) is in progress. The
attachment slice works in the implementation branch; file transfers and complete
installed/platform qualification remain pending. This is not a delivered-main
checkpoint yet.

## Attach to an existing process

Use an intended context and namespace with write actions enabled:

```sh
kuberich --context YOUR_CONTEXT --namespace YOUR_NAMESPACE --write
```

Select a pod, type `:attach` and press Enter to open its container table. Select
the intended regular, init or existing ephemeral container and press `a`.
Attachment opens inside the full Textual workspace, retaining the previous
pod/container selection and viewport. Its frame shows the captured context, pod
and container. The server must report the selected container as running.

Attachment connects to that container's existing main process. Its stdin and TTY
configuration determine the available interaction. `s` / `:shell` opens the
configured shell through the separate exec workflow. Creating an ephemeral debug
container remains a later feature.

| Key | Effect |
| --- | --- |
| Ctrl+P, then Ctrl+Q | Send kubectl's detach sequence and return to containers |
| Ctrl+] | Close the owned local attach session and return to containers |
| Ctrl+C | Forward interruption to the existing remote process |
| Ctrl+Q alone | Quit KubeRich and clean up its local processes |

Read-only mode blocks attachment before a pod preflight or process launch. The
account needs pod read and `pods/attach` permission. Private connection preparation
captures the selected client, context, namespace, container and kubeconfig/helper
environment; source kubeconfig is retained. UID/running-state checks refuse a
replaced, missing, deleting, ambiguous or finished target. Kubernetes does not
offer a UID precondition on the attach subresource; preflight cannot eliminate a
server-side replacement between the read and the attach request.

Local close/detach does not request pod deletion. A signal forwarded to the remote
main process can affect the workload; the frame identifies that behavior.
EOF/failure/interruption returns a fixed diagnostic and preserves process status
without exposing captured kubectl output in the workspace status.

## Transfer availability

Uploads/downloads are being implemented in #48. The completed flow will require
explicit local/remote paths, exact selected-container scope and a review of
destination, size and overwrite intent. Downloads need protected local staging;
read-only mode will block uploads. Copy workflows require tar in the container.
The issue remains open until actual round trips, unsafe-archive refusal,
cancellation/partial-state behavior and complete candidate qualification pass.

See [shells](container-shells.md), [connection setup](context-sessions.md) and
[credential transport](kubeconfig-interoperability.md) for current prerequisites.
