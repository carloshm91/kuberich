# Open your first workspace

Open a Kubernetes workspace in read-only mode, find a pod, and read its logs.
You need an installed `kuberich` command, a trusted kubeconfig, and permission to
read pods and their logs. See [installation](installation.md) if you have not
installed the application.

The names below are fictional. Replace `demo-lab` and `demo-apps` with a context
and namespace you are allowed to read.

## Open an explicit context

```sh
kuberich --context demo-lab --namespace demo-apps --readonly
```

The header shows your context and namespace. The pod table fills after the first
successful read. An empty table can mean the namespace has no pods; an error in
the status area explains a connection or permission problem.

Read-only mode blocks resource changes, shells, attach, uploads, port forwarding,
and plugins that you have not explicitly classified as safe for reads. It still
runs the authentication helper declared in your kubeconfig. Use a kubeconfig you
trust.

## Find a pod

1. Press `/` and enter part of a pod name.
2. Press Enter to return to the table.
3. Use arrows or `j` and `k` to move between rows.
4. Press `g` to select the first row or Shift+G for the last row.

The filter updates as pods change. Press Escape in the table to clear it.
The counter shows matching rows and the total rows in your current scope.

## Read one container's logs

1. Select a pod and press Enter.
2. Check the container names and states, then press Enter on a container.
3. Press `g` to read older output and Shift+G to follow new output again.
4. Press `/`, enter visible text, and press Enter to search.
5. Press Escape to return to containers, then Escape again to return to pods.

The container table updates state and restart counts from the pod watch. Logs
keep a limited history; Kubernetes may already have removed older server logs.
See [read logs](log-viewer.md) for windows, previous instances, and workload logs.

## Change scope

Type `:ns` and press Enter to open the namespace table. Select a namespace and
press Enter. To enter a known namespace directly, use `:ns demo-apps`.
Type `:ctx` to browse contexts. Enter connects to the selected context; highlighting
one alone does not connect.

The command bar suggests completions on the same line. Tab accepts the suggestion
for editing. Bare `:ns` still opens the namespace table. See
[navigate and search](command-navigation.md) for completion and history.

## Leave the workspace

Press Ctrl+Q to quit. KubeRich closes the requests and processes it started and
restores your terminal. Selecting contexts and namespaces does not rewrite your
kubeconfig or its current context.

If the connection fails, type `:status` for the full message and use
[troubleshooting](troubleshooting.md). After correcting credentials or connectivity,
`:retry` reconnects. Opening a shell is a separate deliberate step in
[shells and attach](container-shell.md).
