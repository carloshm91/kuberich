# First installation and trial

The usable development preview has live pods, namespace/context tables, inline
command completion, local filters, 15 [standard resource tables](standard-resources.md),
resource details/YAML/events, container logs and
embedded container shells. The checkout reports `0.0.1.dev0`. **Public packages
are not available yet; the first public product release will be 1.0.0.**
Guarded annotations, manifest editing, workload scale/restart/rollback and managed
pod/Service port forwarding, guarded deletion and Job operations are also available.
Exec credentials, certificates and proxies have locally verified connection contracts;
see [connection compatibility](kubeconfig-interoperability.md). Generic CRD tables,
metrics, attach, ephemeral debugging, file transfer and user plugins remain
separate tickets.
This preview does not claim complete K9s parity or real EKS/AKS certification.

## Run from source

Use Linux or macOS, Python 3.12–3.14 and uv. In a trusted source checkout:

```sh
git switch main
git pull --ff-only
uv sync --locked --group dev --python 3.12
uv run kuberich --version
uv run kuberich --help
uv run kuberich config check
uv run kuberich info
```

Version/help/config/info need no cluster. The UI needs an interactive terminal;
redirecting its input/output is not a way to launch it. `--config` selects
KubeRich preferences; `--kubeconfig` selects Kubernetes credentials/configuration.

Choose an explicitly permitted context/namespace. To list local context names:

```sh
kubectl config get-contexts -o name
uv run kuberich --context YOUR_CONTEXT --namespace YOUR_NAMESPACE --readonly
```

For a separate trusted kubeconfig, use its absolute path consistently:

```sh
kubectl --kubeconfig /absolute/path/to/kubeconfig config get-contexts -o name
uv run kuberich --kubeconfig /absolute/path/to/kubeconfig --context YOUR_CONTEXT --namespace YOUR_NAMESPACE --readonly
```

Replace the uppercase names. No `kubectl config use-context` is required.
KubeRich preserves the source kubeconfig and captures each connection separately.
`--readonly` blocks shells and effectful commands; the server still decides which
reads your identity may perform.

## Try the interface in order

1. Confirm the context/namespace and version in the header, and that real pods
   appear. Empty, denied, connecting and disconnected are distinct states.
2. Type `:ctx`, Enter. Contexts form a table. Use arrows and Enter to connect.
   `:ctx EXACT_NAME` connects directly; Escape restores the prior view.
3. Type `:ns`, Enter. Filter with `/`, type a namespace, Enter to return to its
   table, then Enter on the selected row to open pods. `:ns EXACT_NAME` selects
   it directly; `:ns *` selects all namespaces.
4. On pods, `/` starts a local filter. Type text and Enter; Escape in the table
   clears it. `re:api|worker` is the explicit regex form. Resize the terminal and
   use arrows/PageUp/PageDown to browse. `s` sorts pods; Shift+S reverses order.
5. Select a pod: `d` opens details, `y` YAML and `e` its events. Escape returns.
   Inspection hides sensitive field sets by default; it is not an editor.
6. Enter on a pod opens its container table. Enter on a container opens **that
   container's logs**. In logs, `p` pauses, `f` follows, `g/G` goes first/last,
   `/` searches, `n/N` moves through matches, `t` toggles timestamps and `w` wraps.
   Escape returns to containers; another Escape returns to pods.
7. In the `:` bar, type `c` and use Tab to accept the inline suggestion. Up/Down
   cycles candidates. `:back` / `:forward` restores navigation history; `?` shows
   the actual actions for the current view.
8. Ctrl+Q quits and restores the terminal. `q` also quits outside inputs/shells.

See [commands](command-navigation.md), [workspace](resource-workspace.md),
[inspection](resource-inspection.md) and [logs](log-viewer.md) for full controls.

## Try a shell in your test namespace

Install kubectl on PATH with a [version supported by the cluster](https://kubernetes.io/releases/version-skew-policy/#kubectl).
The account needs pod reads and `pods/exec`; the chosen image must contain `sh`
or your configured shell. Exit the read-only preview, then deliberately enable
shell actions for this invocation:

```sh
uv run kuberich --kubeconfig /absolute/path/to/test-kubeconfig --context YOUR_TEST_CONTEXT --namespace YOUR_TEST_NAMESPACE --write
```

`--write` overrides a read-only preference without changing its file. Select the
pod, Enter, select the container and press `s` or `x`. The shell occupies the
embedded Textual terminal, with its captured context/pod/container shown above.
It uses **kubectl exec**, not SSH into the pod or node.

Inside it, `pwd` or `printf 'hello\n'` are enough for a basic trial. `exit` or
Ctrl+D returns to containers; Ctrl+] closes the owned session locally. Ctrl+C
interrupts the remote program; Ctrl+Q quits KubeRich. Escape, Tab, arrows, `:`,
`/` and `q` are delivered to the remote program while the shell is open.
After returning, Escape goes back to pods. Distroless/completed containers or an
image without a shell need a suitable image; ephemeral debugging is not available
yet. [Shell requirements and limits](container-shell.md).

## EKS and AKS prerequisites

Use the same trusted kubeconfig, user, helper PATH and provider login that work
with explicit-context kubectl. KubeRich invokes the declared exec helper; it
does not provision clusters or manage a separate credential database.

- EKS: AWS CLI with the configured profile/role/session. If the profile uses SSO,
  run `aws sso login --profile YOUR_PROFILE` externally, then `:retry`.
- AKS: Azure kubelogin for its declared login mode; `azurecli` additionally needs
  Azure CLI and the intended `az login` session. An Azure helper requiring
  interaction can use the explicit `:login` action; it runs the declared helper.
  KubeRich does not infer a different tenant/login mode or convert the kubeconfig.

The local adapter/process contracts are verified with owned helpers and kind.
Actual AWS/EKS and Microsoft Entra/AKS trials are deferred to #87. Read
[EKS](eks-authentication.md) and [AKS](aks-authentication.md) for supported
versions/modes, refresh behavior and certification limits.

## Install a supplied local candidate

For a trusted wheel supplied by the maintainer, run outside the checkout:

```sh
uv tool install --python 3.12 /absolute/path/to/kuberich-VERSION-py3-none-any.whl
kuberich --version
kuberich --help
kuberich config check
kuberich info
kuberich --kubeconfig /absolute/path/to/kubeconfig --context YOUR_CONTEXT --namespace YOUR_NAMESPACE --readonly
```

Use the actual filename/version. If uv reports its tool bin directory missing
from PATH, add the directory it reports using your preferred shell setup. The
rehearsal uses private tool directories and an absolute executable path; it never
changes the maintainer's shell configuration or existing tool installation.
`pipx install --python python3.12 /absolute/path/to/WHEEL.whl` is the alternative
already qualified by packaging checks. Do not install the same CLI with both.

Uninstall with `uv tool uninstall kuberich` or, for pipx, `pipx uninstall kuberich`.
Preferences/logs remain separate from the installed application. Running through
the checkout does not create a uv tool installation to uninstall.

PyPI and the public Homebrew tap are planned first-release channels. They are
**not available installation instructions yet**. Public ownership, Linux/macOS
installation and version-to-version upgrades must pass D04 #40 after approval.
Standalone Linux/macOS binaries remain 0.1.0 work.

## If something fails

| Symptom | Next check |
| --- | --- |
| kubectl works but KubeRich does not | Compare the exact `--kubeconfig`, `--context`, `--namespace`, user, helper PATH and provider session; run `:status`, then `:retry` |
| Authentication failure / expired provider login | Complete the declared AWS/Azure login, then retry; never paste tokens or kubeconfig contents into reports |
| Permission denied / 403 | Check the same identity's resource/namespace permission; denied namespace listing can still allow `:ns EXACT_NAME` |
| No matching pods | Clear `/` filtering and confirm the namespace; a denied/stale view is not an empty healthy list |
| Shell blocked | Use `--write` on your test scope; check `kubectl` on PATH, `pods/exec`, container state and the image shell |
| F2/F3 intercepted by terminal/tmux | Use the portable `:ctx` / `:ns` commands |
| UI won't open | Run in an interactive terminal; verify preferences with `config check` |

For feedback, give the version, OS/terminal, exact keys, expected/observed behavior
and a sanitized error/screenshot. `info` describes local preferences/dependencies;
it is not a cluster-connectivity test. Automated coverage supports confidence;
it does not prove compatibility with every cluster or terminal.

## Maintainer rehearsal

The reproducible private trial installs a real wheel into owned uv tool state,
checks config/help/info, uses verified disposable kind, exercises contexts,
namespace filtering/Enter, inspection, logs, read-only rejection and embedded
shell/return/quit, then uninstalls while preserving preferences:

```sh
uv run python -m scripts.verify_quickstart --wheel /absolute/path/to/WHEEL.whl --kind /absolute/path/to/kind --kubectl /absolute/path/to/kubectl
```

It uses pinned kind 0.33.0/Kubernetes+kubectl 1.36.4 and Alpine fixture identities
from [integration qualification](integration-testing.md). Linux results are
recorded in [W01 acceptance](acceptance/quickstart.md); actual macOS and public
channel rehearsal remain #40. No package/site publication is performed.
