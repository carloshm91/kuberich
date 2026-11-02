# User guides before task consolidation

This is an engineering history record, excluded from user navigation and the website.
The source snapshot is commit `a14d1ab65201a214fe178c0f01d1d4e9bcc59a1d`.
It preserves superseded guide text, including historical acceptance and release notes.
Use the current task guides for instructions.

## docs/quickstart.md

SHA-256: `4dc118263a12e0e7f87f2de6b5bdedacf180c9c3a68c0ed2ec281d1c9d771cd8`

````markdown
# First installation and trial

KubeRich 0.2.0 has live pods, namespace/context tables, inline
command completion, local filters, 15 [standard resource tables](standard-resources.md),
resource details/YAML/events, generic CRD tables, single/aggregate logs and
embedded container shells. It also adds themes, local plugins and
navigation preferences. Public PyPI, Homebrew and standalone installations
are available. See
[installation and upgrades](installation.md) for channels and measured scope.
Guarded annotations, manifest editing, workload scale/restart/rollback and managed
pod/Service port forwarding, guarded deletion and Job operations are also available.
Exec credentials, certificates and proxies have locally verified connection contracts;
see [connection compatibility](kubeconfig-interoperability.md). Captured attach
and file transfer are delivered; metrics, creating ephemeral debug containers
and user plugins are planned. Embedded-shell history/search/copy is
delivered: Alt+PageUp opens local review, `/` searches, `v` selects, `y` copies
with recognized credential redaction and Enter/Escape returns to live output.
This preview does not claim complete K9s parity or real EKS/AKS certification.

## Install the public release

On Linux or macOS, choose one method:

```sh
brew install kuberich/tap/kuberich
# Alternative with Python 3.12–3.14:
uv tool install --python 3.12 kuberich
```

Then run `kuberich --version`, `kuberich config check` and
`kuberich --context YOUR_CONTEXT --namespace YOUR_NAMESPACE --readonly`.
Use your intended context and namespace. The remaining examples use a source
checkout; omit `uv run` when using the installed command.

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
Actual AWS/EKS and Microsoft Entra/AKS certification needs separate provider trials. Read
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
changes your shell configuration or existing tool installation.
`pipx install --python python3.12 /absolute/path/to/WHEEL.whl` is the alternative
already qualified by packaging checks. Do not install the same CLI with both.

Uninstall with `uv tool uninstall kuberich` or, for pipx, `pipx uninstall kuberich`.
Preferences/logs remain separate from the installed application. Running through
the checkout does not create a uv tool installation to uninstall.

PyPI and the public Homebrew tap are available. Upgrades to 0.2.0 were tested
from the published 0.1.0 packages.
See [upgrade constraints](distribution.md#upgrade-and-uninstall-contract).
Four qualified standalone Linux/macOS archives are available in the
[0.2.0 release](https://github.com/carloshm91/kuberich/releases/tag/v0.2.0).

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
recorded in [quickstart verification](acceptance/quickstart.md); actual macOS and public
channel verification remain release requirements. No package/site publication is performed.

````

## docs/everyday-workflow.md

SHA-256: `f9b42a5d17798f59c0c17448658955beff7711a3a0bfa148d6560b96ceb87cc2`

````markdown
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

````

## docs/installation.md

SHA-256: `2c35b7849376fbd2df96bdc8fd05aa54171e41272250e71429c3e471933ffe5a`

````markdown
# Installation and upgrades

**0.2.0 is published** on [PyPI](https://pypi.org/project/kuberich/0.2.0/),
[GitHub Releases](https://github.com/carloshm91/kuberich/releases/tag/v0.2.0) and
the [project Homebrew tap](https://github.com/kuberich/homebrew-tap).

Choose one installation method. Every method provides the `kuberich` command;
preferences and kubeconfig remain separate from the application installation.

## Python on Linux or macOS

Use CPython **3.12–3.14** and an isolated [uv tool](https://docs.astral.sh/uv/guides/tools/)
or [pipx](https://pipx.pypa.io/stable/installation/) environment. For a supplied
candidate, run outside the source checkout:

```sh
uv tool install --python 3.12 /absolute/path/to/kuberich-0.2.0-py3-none-any.whl
kuberich --version
kuberich config check
```

Alternatively:

```sh
pipx install --python python3.12 /absolute/path/to/kuberich-0.2.0-py3-none-any.whl
```

Use the actual trusted file path. If the manager reports a missing executable
directory on PATH, add the directory it reports through your normal shell setup.
KubeRich does not modify your shell startup files.

For the public PyPI package, use:

```sh
uv tool install --python 3.12 kuberich
# Alternative:
pipx install --python python3.12 kuberich
```

These unpinned installs allow normal manager upgrades. A file-path installation
or an exact version constraint does not automatically select future releases;
see the upgrade section before changing installation methods.

## Homebrew on Linux or macOS

The project organization **kuberich** owns repository `kuberich/homebrew-tap`.
Install with:

```sh
brew install kuberich/tap/kuberich
kuberich --version
```

The formula declares Python 3.14, kubectl and libyaml. Homebrew manages these
dependencies; a separate Python environment is unnecessary.

From 0.2.0, Homebrew installs a prebuilt bottle on these systems:

| System | Architecture | Bottle |
| --- | --- | --- |
| macOS 14 (Sonoma) or newer | Apple Silicon | `arm64_sonoma` |
| macOS 15 (Sequoia) or newer | Intel | `sequoia` |
| Linux | x86_64 | `x86_64_linux` |

A bottle only unpacks files, so it takes seconds instead of minutes. Other
systems, such as Linux ARM64 or macOS 14 on Intel, still build from source. A
source build can take several minutes.

Homebrew itself publishes prebuilt dependencies, such as Python and kubectl,
only for Apple Silicon with macOS 15 or newer and for Linux. On macOS 14 or an
Intel Mac, Homebrew may build those dependencies from source first, which can
take much longer than installing KubeRich. `brew upgrade kuberich` from 0.1.0 moves
to the bottle and keeps your preferences. Homebrew has no downgrade command; the
old version stays in the Cellar until `brew cleanup` removes it.

## Standalone Linux and macOS archives

A standalone archive includes its own Python runtime. The
[GitHub Release](https://github.com/carloshm91/kuberich/releases/tag/v0.2.0)
contains these four archives and `DOWNLOAD-SHA256SUMS`:

| System | Architecture | Archive |
| --- | --- | --- |
| Linux | x86_64 | `kuberich-0.2.0-linux-x86_64.tar.gz` |
| Linux | ARM64 | `kuberich-0.2.0-linux-arm64.tar.gz` |
| macOS | Intel | `kuberich-0.2.0-macos-x86_64.tar.gz` |
| macOS | Apple Silicon | `kuberich-0.2.0-macos-arm64.tar.gz` |

Linux archives require glibc 2.35 or newer; Alpine/musl and Windows are outside
this release. macOS archives have a measured deployment floor of 14. Native
trials cover macOS 14 ARM and macOS 15 Intel; a physical macOS 14 Intel trial is
not claimed. The archives use ad-hoc signatures; Developer ID notarization is
not claimed.

Compare the selected archive's SHA-256 with its exact line in the supplied
`DOWNLOAD-SHA256SUMS`. On Linux, use `sha256sum ARCHIVE.tar.gz`; on macOS, use
`shasum -a 256 ARCHIVE.tar.gz`. Reject different bytes before extracting.

Extract into a new directory, retaining the complete `kuberich/` tree:

```sh
mkdir kuberich-0.2.0
tar -xzf /absolute/path/to/ARCHIVE.tar.gz -C kuberich-0.2.0
./kuberich-0.2.0/kuberich/kuberich --version
```

Replace `ARCHIVE.tar.gz` with the selected filename. The launcher depends on its
adjacent `_internal` files and notices; copying only the executable is insufficient.
Move the whole directory to your preferred location, then use its absolute
launcher path or create a symlink in a directory already on PATH.

## Qualification scope

The complete source matrix covers Ubuntu 24.04 x86_64 and macOS 26 ARM, each with
CPython 3.12, 3.13 and 3.14. Native archive trials separately cover Ubuntu 22.04
x86_64/ARM64, macOS 14 ARM and macOS 15 Intel. Homebrew trials cover Ubuntu 24.04
x86_64, macOS 14 ARM and macOS 15 Intel with its declared Python dependency.
Exact first-version results are retained with the release candidate; a supported
runtime range does not establish every OS/architecture/terminal combination.

Use an interactive UTF-8 terminal. SSH and tmux transport/restoration have owned
automated trials; physical terminal-emulator, font and clipboard certification
remains separate. See [terminal compatibility](terminal-compatibility.md).

## First launch

Local version/help/config commands need no cluster. For the UI, select a trusted
kubeconfig and an explicitly permitted context/namespace:

```sh
kuberich --kubeconfig /absolute/path/to/kubeconfig --context YOUR_CONTEXT --namespace YOUR_NAMESPACE --readonly
```

Use the actual path and names. The first-launch guide covers `:ctx`, `:ns`, `/`,
pod → container → logs and shell return. Shells, attach, transfers and forwarding
need kubectl on PATH and the corresponding Kubernetes permissions; read-only
mode blocks effectful actions. Provider exec helpers remain external tools.
See [first launch](quickstart.md), [EKS](eks-authentication.md) and
[AKS](aks-authentication.md). Owned helper trials do not certify real clouds.

## Upgrade and uninstall

Update an unpinned managed installation with:

```sh
uv tool upgrade kuberich
# Or, for the method originally chosen:
pipx upgrade kuberich
brew upgrade kuberich/tap/kuberich
```

Upgrades from 0.1.0 to 0.2.0 were tested with uv, pipx and Homebrew, starting
from the published 0.1.0 packages. Preferences and kubeconfig stay unchanged.
To replace a supplied local wheel, use the same manager with its explicit new
file/install constraint; a reinstall is not proof of a normal channel upgrade.

For an archive update, verify a new archive, extract it into a new version
directory and run its version/first-launch checks before switching your launcher.
Keep the previous verified directory until the replacement works.

Remove the application with the chosen manager:

```sh
uv tool uninstall kuberich
# Alternatives:
pipx uninstall kuberich
brew uninstall kuberich/tap/kuberich
```

For an archive install, remove only its extracted directory and your own symlink.
Preferences, logs and kubeconfig stay intact. Use `kuberich info` before uninstall
to locate your preference/log paths; deleting those files is a separate choice.

## Troubleshooting

| Symptom | Next step |
| --- | --- |
| Command not found | Check the manager's reported executable directory or the complete archive launcher path |
| Unsupported Python | Select Python 3.12–3.14 explicitly; standalone archives include their runtime |
| Executable format/library error | Match OS/architecture, verify the checksum and retain the full directory; check the documented native floor |
| Package/tap unavailable | Check network access, the project tap name and your configured package index |
| UI does not open | Use an interactive terminal and run `kuberich config check` |
| kubectl works but KubeRich fails | Compare the exact context, kubeconfig, namespace, helper PATH and provider session; see the connection guides |

Report the version, OS/architecture, installation method and a sanitized error.
Do not include tokens or kubeconfig contents in reports.

````

## docs/context-sessions.md

SHA-256: `afad310cf5f1c291ec414398580efa85d2ee3b374ba1b26e18c97d87845db0b5`

````markdown
# Context sessions

Each selected context owns an independent connection. The workspace lists and
watches the selected resource scope, reports live/stale/error states and retains
its latest snapshot during temporary failures. It includes live resource tables,
details, container logs and embedded shells. See [navigation](command-navigation.md)
and [authentication setup](kubeconfig-interoperability.md) for the related workflows.
Connection errors remain in the UI so you can choose another context or retry.

## Start and select

```sh
uv run kuberich
uv run kuberich --context my-context --namespace my-namespace
uv run kuberich --kubeconfig /path/to/config --context my-context -A --request-timeout 15s
```

An explicit `--kubeconfig` reads a single file. Otherwise `KUBECONFIG` is split
using the platform path separator, then `~/.kube/config` is used if the variable
is unset or empty. Missing entries in an environment list are skipped; a missing
explicit file returns exit 3. Duplicate paths are read once. The first file to
supply a current context or named entry wins; relative credential/CA/helper paths
resolve against that entry's originating file. Selecting or switching a context
never rewrites these files or the current context. Loading the catalogue runs no
helpers and makes no requests.

Without configuration/current context the workspace stays disconnected. F2
shows the loaded contexts; it does not reload files changed by other tools.
Restart after editing kubeconfig elsewhere. An explicit unknown context produces
a configuration state without falling back to another context.

- **c / F2**, `:ctx` or `:context`: browse the local context workspace table;
  `/` filters, Enter connects and Escape restores the preceding resource view.
  `:ctx NAME` selects it directly.
- **n / F3**, `:ns` or `:namespace`: choose a namespace; `:ns NAME` permits manual selection.
- **`:ns *`** or `*` in the selector: select all namespaces.
- **i / F5** or `:status`: read the full connection message in a scrollable dialog, including in narrow terminals.
- **r / F4** or `:retry`: reconnect the selected context with a fresh client and helper cache.
- **Ctrl+Q**: quit while connecting, selecting or editing an input.

Letter shortcuts work outside text inputs; typing in the filter or command field
keeps those letters. Press Escape to return to the resource table. If the terminal
intercepts a function key, use the letter or type the colon command and Enter.
KubeRich cannot receive a key consumed by an outer terminal or tmux binding.

Selectors support arrows, PageUp/PageDown, mouse and Esc/Back. Names are rendered
as literal text. Selecting a namespace records a scope; it does not grant RBAC
permissions. `--namespace` overrides context defaults and `-A` selects all.
They are mutually exclusive. `--request-timeout` accepts seconds or ms/s/m/h,
from 0.1 through 3600 seconds; the default is 10 seconds. Discovery has a total
request deadline and helpers have bounded deadlines too.

Each context replacement cancels and awaits the previous request/helper, closes
the previous explicit SDK client and removes its private TLS files before opening
the next client. The session has a context, generation and client UUID. Namespace
changes advance the generation; selected scopes are remembered per context for
this process without writing preferences. Responses from an earlier connection attempt
cannot update the screen. No SDK global defaults are changed. Normal/error quit
awaits cleanup and restores the terminal.

## Rename or delete a context

Open `:ctx` and move the cursor to a context. Then:

- `:rename NEW` renames it. `:rename` alone opens the form with an empty name.
- **Ctrl+D** or `:delete` deletes it.

Nothing is saved until you choose Review and then Confirm. Review shows the
kubeconfig file that will change and what will change in it. Cancel, or Escape,
leaves the file as it was.

- Only the context entry changes. Its cluster and user entries stay, because
  other contexts may still use them.
- If the context is the file's `current-context`, a rename updates that value
  too. A delete removes it, and you must type `DELETE CURRENT` to confirm. Other
  deletes ask you to type `DELETE`.
- You cannot delete the context KubeRich is using now. Switch to another
  context first. Renaming it reconnects with the new name.
- Before saving, KubeRich writes a backup next to the file, for example
  `config.kuberich-20261019T101500000000.bak`. Only you can read the backup.
  To undo a change, copy the backup over the file.
- The new file replaces the old one in a single step, so a crash cannot leave
  it half-written. The file keeps its permissions. If the path is a symbolic
  link, the file it points to is changed and the link stays.
- If the file changed after Review, nothing is saved. Review again.
- The file is written again from its parsed contents. Comments and custom
  formatting are lost; Review warns you when the file has comments.

KubeRich refuses to guess when the change is unclear. This happens when the
same context name appears in more than one `KUBECONFIG` file, or when a
different file sets it as `current-context`. Edit those files yourself.
`--readonly` blocks rename and delete.

## Credentials and TLS

Supported now:

- Static bearer `token` or periodically refreshed `tokenFile`; the last successfully
  read file value takes precedence over an explicit configured token.
- Embedded or file-backed CA and client certificate/key pairs. Inline TLS data
  takes precedence over a file field. Copies live in a session-owned directory
  with mode 700 and files with mode 600; closure removes them.
- Exec **token or paired TLS certificate/key** credentials using `client.authentication.k8s.io/v1`
  or `v1beta1`. Kind/version must match the configured version. v1 requires
  `interactiveMode`; beta defaults to `IfAvailable`. `Never`/`IfAvailable` receive
  `KUBERNETES_EXEC_INFO.spec.interactive=false` and closed stdin. Args and configured
  environment variables are passed literally, without a shell. `provideClusterInfo`
  supplies cluster metadata including CA data and the reserved exec extension.
  Each session caches credentials until expiration, process closure or 401; a read
  rejected with 401 invalidates and retries once. Helpers drain both output pipes,
  cap stdout at 1 MiB/stderr at 64 KiB, and kill/reap their owned process group on
  failure, timeout, cancellation and completion.

Optional exec `args` and `env` lists may be absent, null or empty. This includes
the `env: null` form emitted in DigitalOcean/doctl kubeconfigs. Null lists are
treated as empty; malformed non-list values still produce a safe auth error.
This compatibility fix does not qualify every provider/login combination.

Kubeconfig is trusted local configuration: configured helpers run with your user
privileges, including in application read-only mode. Never launch with an
untrusted kubeconfig. Helpers are authentication tools, separate from future
operator-invoked plugins. Their credential stdout, raw SDK errors and response bodies are never printed
or logged. Explicit `:login` sends the configured native helper's prompt/stderr
to the terminal during the handoff; it is not retained in diagnostics.

TLS verification is on by default. A native kubeconfig
`insecure-skip-tls-verify: true` or an HTTP endpoint displays **Insecure transport**
in the status, including with hidden headers. `tls-server-name` is honored.
Native `proxy-url` supports HTTP(S)/SOCKS5. Without a nonempty explicit proxy,
captured HTTP(S)_PROXY/NO_PROXY settings apply. Automatic netrc identity remains
disabled. Owned real proxy/TLS contracts and Kubernetes HTTP CONNECT qualify
local behavior; [interoperability guidance](kubeconfig-interoperability.md)
records precedence, cleanup and SOCKS5 streaming limits.

KubeRich supports exec certificate renewal and native helper `:login`, including
the exact declared stdin behavior, private stdout and restored terminal.
Legacy `auth-provider` and basic credentials remain explicitly unsupported;
the same guide describes migration to exec/token/certificate entries.
Credential behavior is verified locally. Real EKS/AKS/GKE compatibility requires
separate provider trials; synthetic tests do not certify cloud tenants.
See [EKS](eks-authentication.md) and [AKS](aks-authentication.md) limits.
CLI cluster/user/token/TLS/impersonation overrides are supported;
see the [effective launch connection](k9s-cli.md#effective-invocation-connection).
They apply to this invocation, including context changes, reads, watches, logs
and the private captured kubectl shell connection. Real provider qualification
requires separate authorized trials.

## Connection states and bounds

| State | Meaning and action |
| --- | --- |
| Disconnected | No selected configuration; configure kubeconfig or use F2 |
| Connecting | Background authentication/discovery; inputs and quit stay responsive |
| Connected | Namespace discovery succeeded; resource status separately reports pod synchronization |
| Limited | Listing namespaces returned 403; select an allowed namespace manually |
| Auth error | Missing/rejected/unsupported credentials or helper failure; check login and retry |
| TLS error | Invalid/untrusted certificates or hostname mismatch; check CA/server/client files |
| Timeout | Request exceeded the deadline; check connectivity or timeout and retry |
| Unreachable | Connection/network failure; check VPN/server address and retry |
| Config error | Invalid connection/catalogue fields; fix config or select another context |
| API error | Unexpected status, malformed/excessive response; check endpoint and retry |

A 403 cannot establish that any resource operation is authorized. The terminal
connection attempts namespace discovery; resource reads have their own
explicit permission/error results. Namespace discovery follows at most
32 pages and retains at most 2048 namespace names, with 1 MiB per response;
exceeding a limit is a visible error rather than a truncated successful list.
Automatic response decompression and redirects are disabled. Kubeconfig reads
are limited to 32 paths, 1 MiB per file, 2048 named entries per merged section,
30 YAML nesting levels and 65536 parser events. Aliases, duplicate mapping keys,
duplicate names within a file and nonregular files are rejected. These are
application limits, not Kubernetes API limits.

## Qualification

Unit tests exercise merge precedence, path provenance, invalid configurations and
scope decisions. Fake numeric-loopback HTTP/TLS servers test real API requests,
static/token-file/client-certificate auth, 401/403, pagination/limits, invalid CAs,
TLS names, timeouts and cancellation. Synthetic helper scripts test exec contracts,
expiry/refresh, concurrent output, malformed responses, cancellation and reaping.
Pilot and PTYs verify responsive selectors, switching, quit and terminal restoration.
Installed artifacts and the OS/Python matrix qualify the same code.

`scripts/verify_contexts_kind.py --kind /path/to/verified-kind` creates a uniquely
named local kind cluster with an explicit temporary kubeconfig, verifies namespace
listing, TLS/client-certificate authentication, generations, resource discovery,
consistent paginated snapshots and client cleanup,
then deletes only its owned cluster in `finally`. It never selects an ambient
cluster. CI requires this check on Linux/Python 3.12 and retains sanitized JSON
evidence. The binary/version/image are pinned in the workflow/script.

Sources: [kubeconfig merge rules](https://kubernetes.io/docs/concepts/configuration/organize-cluster-access-kubeconfig/),
[exec credential contract](https://kubernetes.io/docs/reference/access-authn-authz/authentication/#client-go-credential-plugins),
[kubeconfig schema](https://kubernetes.io/docs/reference/config-api/kubeconfig.v1/),
[kind quick start](https://kind.sigs.k8s.io/docs/user/quick-start/).

````

## docs/eks-authentication.md

SHA-256: `87c8fa0b1dfdf08517fa871881c7b22ae5ade7058f99331a03338efcefba68b7`

````markdown
# EKS authentication

KubeRich uses the `aws eks get-token` exec entry already declared in your trusted
local kubeconfig. The AWS CLI owns its credential chain, profiles, role assumption,
SSO cache and refresh; KubeRich does not embed AWS credentials or create clusters.
The local contracts below are implemented. **Actual AWS/EKS qualification is
pending.** Automated checks establish local credential-helper behavior; they
do not certify a real AWS account, role or SSO policy.

## Supported local contracts

- Honor declared arguments/environment and `client.authentication.k8s.io/v1`
  or `v1beta1`. Version v1 requires `interactiveMode`; Never and IfAvailable
  receive closed stdin and `KUBERNETES_EXEC_INFO.spec.interactive=false`.
  Empty environment values such as `AWS_PAGER=""` remain literal empty strings.
- Cache tokens per context until their expiration, rejection or session closure.
  Concurrent refresh requests share the helper lock. Delayed 401 responses from
  an older cache revision cannot invalidate a newer revision, even when AWS
  returns the same token bytes; each request retries a rejection at most once.
- Capture inherited helper environment when the session is created. Refresh
  preserves it. Delegated shells inherit the same AWS variables and HOME, retain
  declared exec env/args, and use the same kubeconfig-relative working directory.
  A bare `aws` command is resolved using the effective helper PATH and pinned
  in the private kubectl connection snapshot. No inherited AWS secrets are
  added to the snapshot file; captured variables remain in process memory.
- Drain helper pipes concurrently with existing 1 MiB stdout/64 KiB stderr
  bounds, timeout, process-group cleanup and no raw output in diagnostics.
  Closing a session discards the credential cache and prevents further delegation.
- Show fixed hints for a missing AWS CLI, execution permissions, recognized SSO
  errors, denied AssumeRole, missing credentials and expired AWS credentials.
  Unknown helper failures retain a generic AWS hint. Recognition is best effort
  for a declared `aws ... eks get-token` executable; wrappers retain generic
  helper errors. Kubernetes 401 and 403 remain separate API outcomes.

Complete SSO login outside KubeRich using the profile from your exec entry:

```sh
aws sso login --profile YOUR_PROFILE
```

Then retry with `r` or `:retry`. KubeRich does not open a browser automatically or
rewrite your kubeconfig/AWS files. The AWS CLI may renew its own cached credentials
as part of the configured helper. Explicit native `:login` is available for generic
helpers with `Always`/`IfAvailable`/`Never` stdin semantics and TLS certificate
renewal. It runs the declared helper; it does not infer an `aws sso login` command.
See [kubeconfig interoperability](kubeconfig-interoperability.md).

## Opt-in real smoke

Run only on a **test context explicitly authorized by its owner**. The script
refuses omitted scopes and non-AWS exec entries, and never falls back to the
active/default context:

```sh
uv run python -m scripts.verify_eks_auth \
  --kubeconfig /absolute/path/to/test-kubeconfig \
  --context YOUR_EKS_TEST_CONTEXT \
  --namespace YOUR_TEST_NAMESPACE \
  --kubectl /absolute/path/to/kubectl \
  --acknowledge-test-cluster
```

It reads at most one pod per response through the Python adapter, forces only
the session-local cache expiration for five concurrent reads, and performs the
same pod read with real kubectl and a private connection snapshot. It creates no
cluster resources, performs no exec and calls no provisioning APIs. Its report
contains fixed outcomes/platform information; no token, account, ARN, context,
namespace, kubeconfig, helper output or pod contents are retained. The private
snapshot is removed and the client/TLS directory closed on success and failure.

This smoke does **not** prove naturally expiring tokens, the full SSO/role matrix,
or the server-side principal merely from successful reads. Qualification must
record actual AWS CLI/Kubernetes/kubectl/platform versions and the authorized
profile/role/SSO scenarios separately, without publishing private identities.
The checked-in tests use local synthetic helpers, and the kind verifier uses a
synthetic AWS-shaped helper with a disposable service-account token. Neither is
real-cloud evidence. See [measured acceptance](acceptance/eks-authentication.md).

## Sources

- [EKS kubeconfig and AWS helper](https://docs.aws.amazon.com/eks/latest/userguide/create-kubeconfig.html)
- [AWS CLI get-token](https://docs.aws.amazon.com/cli/latest/reference/eks/get-token.html)
- [AWS CLI SSO sessions](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html)
- [AWS CLI 2.36.46 ExecCredential version negotiation](https://github.com/aws/aws-cli/blob/2.36.46/awscli/customizations/eks/get_token.py)
- [Kubernetes exec credential protocol](https://kubernetes.io/docs/reference/access-authn-authz/authentication/#client-go-credential-plugins)

````

## docs/aks-authentication.md

SHA-256: `841a277c1fd580ebb73249e79f69bb77262e432f7bdec41b49672f895a74bdd1`

````markdown
# AKS authentication

KubeRich runs the Azure `kubelogin get-token` exec entry declared in the selected
trusted kubeconfig. It does not implement Azure login protocols, store a second
identity database, convert the kubeconfig, select another tenant or provision AKS.

## Implemented local contract

- Exec `client.authentication.k8s.io/v1` and `v1beta1`; v1 requires a valid
  `interactiveMode`, while beta defaults to `IfAvailable`.
- Literal provider args/env, including `azurecli`, `devicecode`, service principal
  (`spn`) password/PFX certificate inputs and `workloadidentity` federation settings.
  The provider owns precedence, caches and certificate/token exchange. Native
  kubelogin returns a bearer token even when the service principal uses a certificate.
- Concurrent expiration and 401 refresh share the per-context cache. Delayed 401s
  cannot invalidate a newer revision. API 403 remains an authorization failure,
  distinct from missing kubelogin/Azure CLI, login expiry, tenant configuration,
  service-principal credentials and federation hints.
- Captured inherited `AZURE_*`, `AAD_*`, `ARM_*`, `AZURESUBSCRIPTION_*`, `HOME`,
  `PATH` and `KUBECACHEDIR` are retained for delegated kubectl, together with the
  declared args/env, resolved helper executable and kubeconfig working directory.
  Changing the launch environment or source kubeconfig cannot redirect that session.
- Exec bearer credentials have a separate 64 KiB visible-ASCII bound, avoiding the
  8 KiB argument/name limit for group-heavy JWTs. Whitespace and control/header
  injection are rejected. This is a client bound; the selected server/proxy can
  impose a lower HTTP header limit.

## Explicit login and retry

Ordinary background requests use closed stdin and `spec.interactive=false`.
Existing provider sessions can supply credentials without leaving the UI.
A recognized device-code prompt stops the owned background helper promptly and
shows a fixed `:login` hint; private device codes and provider output stay out of
widgets/logs. Unrecognized helper waits still have the request deadline.
Browser-interactive mode and `Always` require an explicit login rather than an
automatic browser/terminal interaction.

On a configured Azure context, `:login` temporarily suspends the native workspace
and runs the same declared helper. The provider's stderr/prompt uses the terminal;
stdout credential JSON is captured with the existing 1 MiB bound and is never
printed. `Never` retains closed stdin; `IfAvailable` and `Always` receive terminal
stdin and `spec.interactive=true`. The handoff has a five-minute application
limit; a declared provider timeout may be shorter. Ctrl+C cancels the child.
After success KubeRich validates the response and reconnects through the ordinary
per-context API path. Failure/cancellation restores the UI and offers retry.
Shutdown or a context replacement owns process cleanup and rejects old results.

This route is allowed in application read-only mode because authentication is
needed for reads. It requires a native POSIX terminal; headless/non-TTY/Web surfaces
refuse it. The configured local helper controls its own interactive stderr output;
KubeRich does not record that output in diagnostics. Do not configure a provider
verbosity that prints secrets. For `azurecli`, establish the intended `az login`
session externally; `:login` runs the declared kubelogin entry, not an inferred
`az login` command or a different login mode.

## Qualification limits

The automated evidence uses owned synthetic helpers, loopback APIs, actual PTYs,
fresh wheel installation and a disposable kind cluster with real kubectl. It
establishes local adapter/process behavior, not successful Microsoft Entra
exchange or tenant policy compatibility. Actual AKS/Entra certification is deferred
to explicitly authorized provider trials. No real tenant is contacted by
the automated suite. Linux results do not establish macOS qualification.

Local tests also cover GKE/OIDC-shaped helper contracts and
`ExecCredential.status.clientCertificateData/clientKeyData` output rotation locally.
That Kubernetes TLS mechanism is distinct from Azure service-principal certificate
**inputs**. [Interoperability guidance](kubeconfig-interoperability.md) documents
the supported output and legacy-provider migration. Conditional
Access, browser forwarding on SSH and provider cache/keyring differences need
actual environment evidence. See [acceptance evidence](acceptance/aks-authentication.md).

## Optional read-only test-context smoke

The developer verifier requires every explicit scope and an acknowledgement:

```sh
uv run python -m scripts.verify_aks_auth --kubeconfig /path/to/test-kubeconfig --context TEST_CONTEXT --namespace TEST_NAMESPACE --kubectl /path/to/kubectl --acknowledge-test-cluster
```

It requires a declared Azure helper, reads at most one pod through the API, forces
only the local cache deadline, verifies five concurrent reads share one refresh,
and checks a real delegated kubectl read using a private mode-600 config that is
removed afterwards. It performs no resource writes, exec or provisioning.
Forced refresh does not prove natural expiry, real interactive login, or the
full Entra mode/policy matrix; the evidence says so. It never falls back to the
active user context, and returns fixed sanitized failures.

## Sources

Reviewed Azure kubelogin source at
[`5d03c6dd909e27b36b39a1cb9a815f2b47d9a180`](https://github.com/Azure/kubelogin/tree/5d03c6dd909e27b36b39a1cb9a815f2b47d9a180),
including [token writer](https://github.com/Azure/kubelogin/blob/5d03c6dd909e27b36b39a1cb9a815f2b47d9a180/pkg/internal/token/execCredentialWriter.go),
[device prompt](https://github.com/Azure/kubelogin/blob/5d03c6dd909e27b36b39a1cb9a815f2b47d9a180/pkg/internal/token/devicecodecredential.go)
and [environment precedence](https://github.com/Azure/kubelogin/blob/5d03c6dd909e27b36b39a1cb9a815f2b47d9a180/pkg/internal/token/options.go).
Latest observed provider release was v0.2.20; it is not a qualified installed version.

- [Microsoft AKS authentication](https://learn.microsoft.com/en-us/azure/aks/kubelogin-authentication)
- [Azure login modes](https://azure.github.io/kubelogin/concepts/login-modes.html)
- [Azure get-token arguments](https://azure.github.io/kubelogin/cli/get-token.html)
- [Kubernetes exec input/output contract](https://kubernetes.io/docs/reference/access-authn-authz/authentication/#client-go-credential-plugins)

- [Microsoft Entra error-code reference](https://learn.microsoft.com/en-us/entra/identity-platform/reference-error-codes)

````

## docs/kubeconfig-interoperability.md

SHA-256: `03dd3d805158084d000c564b636f7cd527630d1c4090d83c27a7514b2c780c73`

````markdown
# Kubeconfig and credential interoperability

KubeRich uses the selected context's effective connection for resource reads,
watches, logs, guarded writes, shells and port forwarding. It does not change
your kubeconfig or infer a different cloud account when authentication fails.
The contracts below are tested with owned helpers, HTTP/TLS/proxy servers,
native terminals, installed packages and a disposable Kubernetes cluster.
Real cloud-provider compatibility needs separate trials in the intended environment.

## Configuration and private material

`--kubeconfig` selects one file; otherwise `KUBECONFIG` can list files separated
by the operating system's path separator. Catalogue merging preserves the
directory that supplied each cluster/user entry. Relative CA, certificate, key,
token-file and helper paths resolve against that directory, including when the
context and user come from different files. Embedded TLS data overrides its
corresponding file. CA/certificate/key copies and generated connection snapshots
live in an owned mode-700 directory with mode-600 files; awaited session cleanup
removes them.

Encrypted static client keys are refused before OpenSSL can request a passphrase
inside the application. Use a compatible unencrypted key or an explicit exec
helper that owns decryption; KubeRich never starts an implicit password prompt.

`tokenFile` is read at connection preparation, then checked before requests at
most every 60 seconds. A 401 forces a reread before one read-only retry. The last
successful file value takes precedence over an explicit `token`; an unavailable
rotation preserves that value. An unreadable initial file can use only the
explicit configured token. It never selects an anonymous identity as a fallback.
Effectful requests receive refreshed credentials before sending and are not
automatically replayed after a rejection or uncertain response.

## ExecCredential

The declared helper receives literal argv and configured environment entries,
runs in its original kubeconfig directory, and uses a captured inherited
environment. Bare executable names resolve through the effective helper PATH;
the successfully used absolute executable is pinned for delegated tools.
Capturing includes variables that were absent, so a later caller cannot inject
a different profile or helper identity. Helpers remain trusted local programs
running with your user's privileges, including in read-only mode.

KubeRich supports `client.authentication.k8s.io/v1` and `v1beta1`, with matching
response kind/version. Version v1 requires `interactiveMode`; beta defaults to
`IfAvailable`. The native `:login` command explicitly runs that same helper:

| Declared mode | Ordinary background authentication | Explicit native `:login` |
| --- | --- | --- |
| `Never` | Closed stdin, `interactive=false` | Closed stdin, `interactive=false` |
| `IfAvailable` | Closed stdin, `interactive=false` | Terminal stdin, `interactive=true` |
| `Always` | Refused with a login hint | Terminal stdin, `interactive=true` |

The background helper never inherits terminal input. Login requires the native
terminal, keeps credential stdout private and restores the workspace after
success, Ctrl+C, cancellation or termination. The configured helper controls
its terminal stderr, such as browser/device prompts. KubeRich does not retain
that interactive output in logs or diagnostics. Headless/non-TTY/Web operation
cannot provide this handoff.

`provideClusterInfo` must be a boolean and defaults to false. Only true includes
`spec.cluster`: effective server, verification setting, CA data, TLS name,
proxy and the `client.authentication.k8s.io/exec` extension configuration.
`spec.interactive` always describes the stdin actually supplied. See the
[Kubernetes credential API](https://kubernetes.io/docs/reference/config-api/client-authentication.v1/).

Responses contain either a bounded bearer token or a paired PEM client
certificate/private key. Mixed identities, missing pairs, encrypted helper keys,
invalid versions/JSON and expired or timezone-free deadlines are rejected.
The helper's output is bounded to 1 MiB; stderr is bounded to 64 KiB. Each
session owns its cache, helper process group, deadline and cancellation.

Certificate renewal validates the key pair, creates fresh private files and
replaces the connection pool. Previous TLS connections close so the new pair
participates in a new handshake. Changing to a token removes the old certificate
identity. Invalid replacement material refuses the request; it cannot silently
continue under the previous certificate. Concurrent refresh shares one lock;
an old response cannot invalidate a newer credential revision.

## Proxies, TLS and delegated tools

An explicit nonempty `proxy-url` wins. Otherwise the captured `HTTP_PROXY` /
`HTTPS_PROXY` or lowercase equivalents select the proxy, with `NO_PROXY` bypass
rules. Environment settings bypass localhost/loopback; an explicit proxy still
applies there. CGI-style `HTTP_PROXY` is refused. Supported URL schemes are
HTTP, HTTPS and SOCKS5, including proxy credentials. Proxy authentication stays
separate from the Kubernetes bearer token. Automatic netrc identity remains
disabled.

Server certificates use the configured CA and original server hostname, or
nonempty `tls-server-name`. This also applies through SOCKS5 and certificate
renewal. Disabling verification remains explicit and visible as insecure
transport. Proxy failures and TLS mismatches produce fixed safe diagnostics.
Repeated impersonation groups and user/UID/extras retain their meaning.

Shells and forwards receive a captured private kubeconfig with the same server,
proxy, TLS material, helper and impersonation settings. They do not reload the
ambient current context. HTTP CONNECT is qualified against real Kubernetes
for logs, exec and forwarding. SOCKS5 qualifies API reads/streams/TLS; Kubernetes
documents a limitation for SPDY exec/attach/forward transports. KubeRich preserves
the selected proxy and reports failures rather than silently bypassing it.
See the [kubeconfig API](https://kubernetes.io/docs/reference/config-api/kubeconfig.v1/).

The shared private-connection staging also accepts Helm's future purpose. Actual
Helm operations are not available in this release.

## GKE, OIDC and legacy migration

For GKE, install `gke-gcloud-auth-plugin` using Google's instructions and
regenerate the intended cluster entry with `gcloud container clusters
get-credentials CLUSTER --location LOCATION`. Select that context in KubeRich.
Google documents this exec plugin as the client authentication mechanism.
[GKE setup and migration](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/cluster-access-for-kubectl).

External OIDC helpers use the same exec contract; KubeRich does not embed an
issuer, token exchange, keyring or browser-login implementation. An OIDC
`kubelogin get-token` entry without Azure's `--server-id` remains a generic
helper. For AKS, use the configured Azure kubelogin exec entry and
[AKS guidance](aks-authentication.md). For EKS, retain the intended
[AWS profile/role entry](eks-authentication.md).

Legacy `auth-provider` entries, including GCP/Azure/OIDC modes, and HTTP basic
username/password are explicitly unsupported. Migrate the selected entry to
the provider's exec helper or an explicit token/certificate user. KubeRich refuses
conflicting mechanisms and never guesses a replacement identity or rewrites
provider credential files. The automated provider-shaped fixtures verify local
contracts; they do not establish successful cloud exchange, tenant policies,
natural cache expiry or SSH browser forwarding.

````

## docs/command-navigation.md

SHA-256: `d8faf531e8f3e3d64b0107dfd0c5646c0efa9dcee831cab6e33b41c1ac1e1783`

````markdown
# Commands, filtering and navigation

The workspace has live pod and namespace views. Selected pods support [inspection](resource-inspection.md),
[logs](log-viewer.md) and [embedded shells](container-shell.md); other resource
tables are described in [standard resources](standard-resources.md).

See [terminal navigation and remote clipboard](terminal-navigation.md) for the
next-release key matrix, wide/errors/selection controls, nested commands, favorites
and explicit clipboard backends.

## Commands

Press `:` outside an input, type a command and press Enter. The same parser and
read-only policy handle `--command` / `-c` at launch. Arguments preserve casing.

| Command | Behavior |
| --- | --- |
| `po`, `pod`, `pods` | Focus the available pod view |
| `po NAMESPACE`, `po *` | Select a pod namespace or all namespaces |
| `ctx`, `context`, `contexts` | Open the local context workspace table |
| `ctx NAME` | Connect directly to that context |
| `rename NEW`, `delete` | In the context table: review renaming or deleting the selected kubeconfig context; see [contexts](context-sessions.md#rename-or-delete-a-context) |
| `ns`, `namespace`, `namespaces` | Open the live namespace workspace table |
| `ns NAME`, `ns *` | Select that namespace or all namespaces |
| `shell`, `exec` | Open the selected pod’s container picker; `s`/`x` launches its shell |
| `attach` | Choose a running container; `a` connects to its existing main process |
| `upload`, `download` | Choose a container; `u`/`d` opens explicit copy review |
| `status`, `retry` | Open connection details / reconnect |
| `resource NAME[.GROUP][/VERSION] [NAMESPACE or *]` | Browse a discovered API family or an explicit served version |
| `cleanup` | In a pod view: review deleting the completed and failed pods shown; see [cleanup](resource-operations.md#clean-up-finished-pods) |
| `jump`, `jump NAME` | Open a related view from the selected row, with a filter already set; see [jumps](resource-jumps.md) |
| `refresh` | Renew discovery and the selected resource watch on the current client |
| `columns`, `columns cN ...`, `columns default`, `columns none` | Inspect/configure transient generic server columns |
| `views` | Configure resource columns, widths, alignment and typed sort; explicitly save globally or by context in next-release source |
| `plugins`, `plugin NAME`, `pluginjobs` | Next-release source: list/review explicitly configured local commands and inspect/stop owned jobs; see [plugins](plugins.md) |
| `back`, `forward` | Restore the previous / next navigation state |
| `help`, `?` | Show actual keyboard actions and limits |
| `quit`, `q`, `exit` | Exit and restore the terminal |

For example, `uv run kuberich --context YOUR_CONTEXT --command 'po YOUR_NAMESPACE'`
connects once and starts the requested pod scope without first watching another
namespace. `--command 'ctx NAME'` selects that context before authentication.
Unsupported commands report unavailable; they never display a substitute table.
Inspection commands remain usable in read-only mode. Embedded shells are available
in write mode; startup `--command shell`/`exec` is refused because a deliberately
selected pod is required. Attach and copies also require interactive selection;
see [attach and file transfer](container-attach-copy.md). Guarded mutations have
their own review workflows. Local plugins are available in next-release source
through explicit [configuration and review](plugins.md); published 0.1.0 is unchanged.
The shared policy rejects effectful commands in read-only mode.

## Completion

The dedicated `:` bar shows the selected prefix match as an inline suggested
suffix in muted italic styling. Up/Down cycle up to eight local candidates;
there is no dropdown. The suffix is display text until accepted. Tab accepts it
for editing; Enter after Up/Down accepts and submits the selected candidate once.
Enter without arrow selection submits the typed text, so bare `:ns` opens the
namespace table and `:ctx` opens the context picker. Editing the query, leaving
the input or changing scope discards prior arrow selection. Matching ignores
case; the accepted context name retains its original case. At 40×12 the native
one-line input scrolls horizontally with its cursor.
Inputs/candidates are bounded to 256 characters; only the suffix that fits in the
remaining input width is visible. Empty input retains its placeholder. Suggestions
never resize the bar or cover resources. Right moves the editing cursor rather
than accepting a completion.

Candidates come from local command aliases, the current client's discovered
resource catalogue, the loaded kubeconfig catalogue and
the active session's namespace cache. Typing, selecting and accepting suggestions
does not authenticate or make API requests. A context switch immediately drops
the old namespace candidates. When namespace listing is denied, only the known
current namespace and `*` are suggested; enter a permitted namespace directly.
Disconnected/connecting sessions have no namespace suggestions.

Tab moves focus when no candidate applies. Shift+Tab always moves focus backward.
Moving the input cursor away from its end hides suggestions; returning to the end
restores applicable candidates. Escape leaves the input and clears command text;
filter text remains until Escape in the table. Help restores the prior focus.

## Filters

Press `/` outside an input. Plain text performs case-insensitive literal matching
across namespace, name, readiness, status and restart count. `re:PATTERN` selects
case-insensitive Unicode regex matching with the `regex` package's VERSION1
dialect. For example, `api` finds matching names and `re:api|worker` matches either.
Age is excluded because it changes continuously. These are local filters over
the current snapshot, rather than server-side label/field selectors.

Filtering updates while typing and continues through live pod changes. Enter
returns to the table; Escape there clears the filter. Status reports visible/total
counts. A valid filter with no matches shows **No pods match this filter**.
Invalid or excessive regex patterns show a clear error and all current pods;
they never masquerade as a successfully empty scope.

Queries are limited to 256 characters. Matching runs off the UI loop, with a total
50 ms regex budget per snapshot; a timeout discards partial results and reports
the error. The engine releases the GIL during matching and supports an actual
match timeout. Cancellation awaits the owned worker. Scope/query identity guards
reject late results; rapid input coalesces into the latest render request.
Next-release source adds inverse regex, fuzzy subsequences, bounded local label/field selectors and separate memory-only filter recall; see [terminal navigation](terminal-navigation.md).
Maximum-workload latency and memory still need sustained performance validation.
These bounds alone do not establish a maximum supported workload.

## Navigation history

Alt+Left / Alt+Right, or `:back` / `:forward`, restore context, namespace, filter,
sort direction/column, selected pod UID and viewport. History retains at most 32
states in each direction for this invocation. New manual navigation clears the
forward stack. Missing/deleted UIDs use the table's deterministic row fallback.
History can return from a failed context; authentication/read failures remain
visible. Restoring a context owns a new connection and cancels the previous watch.
Only the matching revision can restore a saved viewport. History is not persisted,
and next-release source adds explicit per-context namespace favorites and last-command recall; see [terminal navigation](terminal-navigation.md).

## Verification

```sh
uv run pytest tests/unit/test_navigation.py tests/unit/test_filtering.py tests/ui/test_navigation.py
uv run pytest tests/terminal/test_navigation.py tests/packaging/test_distribution.py
```

The command grammar and deterministic navigation domain enforce 100% line/branch
coverage. Pilot exercises actual loopback HTTP sessions, input focus, cached
literal completions, no keystroke I/O, small screens, stale scopes, filter errors,
history restoration and exit during a blocked owned worker. Real PTYs exercise
rapid Tab/Enter input, filters, scope commands, history, resize and terminal
restoration. The same trial runs against freshly installed console/module entry
points outside the checkout. Disposable-kind qualification exercises real regex
filtering, namespace completion and restored selection/sorting.

Sources: [Textual Input](https://textual.textualize.io/widgets/input/),
[bindings](https://textual.textualize.io/guide/input/#bindings),
[queued callbacks](https://textual.textualize.io/api/message_pump/#textual.message_pump.MessagePump.call_later),
[regex timeout and threading](https://pypi.org/project/regex/).

Measured delivery evidence and unavailable platform checks:
[navigation verification](acceptance/B03.md).

Namespaces share these filter bounds for name/status. See [workspace layout, live namespaces and Escape routes](resource-workspace.md).

The next-release source also provides `:themes` / `:theme` for local appearance
and `:about` for branding/version-check state. See [themes](themes.md) for
preview, save, precedence and release availability.

The next-release source also offers [navigation preferences](navigation-preferences.md):
per-view keys, literal aliases with effective completion and explicitly saved
resource layouts. Published 0.1.0 packages retain their original fixed keys.

````

## docs/terminal-navigation.md

SHA-256: `34537ea6f688b23814985c823b2ed04395835794c6d20ea2257ad7afb6792a11`

````markdown
# Terminal navigation and remote clipboard

These features are in the source checkout for the next release. Published 0.1.0
packages retain their original behavior. No new account or hosted service is
required.

## Keys belong to the focused view

| View | Movement | First / last | Pages | Half pages | Horizontal | Other owners |
| --- | --- | --- | --- | --- | --- | --- |
| Resource and namespace tables | j / k | g / G | Ctrl+F / Ctrl+B | J / Ctrl+U | h / Alt+L | l logs; n namespaces; Ctrl+D deletion review; Ctrl+Y copy name |
| Context/container and other selectors | j / k | g / G | Ctrl+F / Ctrl+B | J / Ctrl+U | h / Alt+L | Container s/x shell, l logs, a attach, u/d transfer; selectors retain their actions |
| Details, YAML, events | j / k | g / G | Ctrl+F / Ctrl+B | Ctrl+D / Ctrl+U | h / l | y/d/e pages; m managed fields; n/N search matches; Ctrl+Y copy |
| Help | j / k | g / G | Ctrl+F / Ctrl+B | Ctrl+D / Ctrl+U | h / l | Escape returns to the prior view |
| Logs | j / k | g / G | Ctrl+F / Ctrl+B | Ctrl+D / Ctrl+U | h / l | n/N search; Ctrl+Y copy; existing follow/pause/window/source actions |
| Command, filter, search or editor input | Native editing | Native editing | Native editing | Native editing | Native editing | Printable letters stay literal; Tab in commands deliberately completes |
| Embedded shell | Remote program | Remote program | Remote program | Remote program | Remote program | Ctrl+] returns locally; Ctrl+Q quits; remote keys take precedence |

Capital `G` is one uppercase character. Neither Vim numeric counts nor a complete
Vim grammar is implemented. Arrows and PageUp/PageDown remain available.
Table Home/End move horizontally; Ctrl+Home/Ctrl+End and g/G select whole-view
edges. TextArea Home/End retain line boundaries; g/G move to document edges.
Configure the independent `text` profile, `logs` profile or table profiles in
[navigation preferences](navigation-preferences.md). Text and log profiles do
not inherit common table overrides.

## Command and filter recall

Alt+Up/Alt+Down recall at most 32 submitted entries and restore the unfinished
draft when moving forward past the latest entry. Command and root-filter
histories are separate and memory-only. Up/Down in the command bar keep their
existing suggestion-cycling behavior. `:!!` repeats the last accepted command
through normal policy, target checks and review; it never approves a mutation
or a local plugin automatically. Launch `--command` refuses these selection and
recall controls before authentication; use them interactively.

Alt+Left/Alt+Right and `:back`/`:forward` retain the separate scope/view history.

## Additional local filters

Use `/` to enter one filter family at a time:

| Query | Meaning |
| --- | --- |
| `api` | Case-insensitive literal substring of visible resource search fields |
| `re:api\|worker` | Unicode regular expression |
| `!re:api\|worker` | Inverse regular expression |
| `fuzzy:apwrk` | Case-insensitive ordered subsequence; retains normal table sorting |
| `label:app=api,tier in (frontend,worker),!debug` | Local label AND terms |
| `field:metadata.name=api` | Local allowlisted field equality |

Labels support `=`, `==`, `!=`, `in`, `notin`, existence and `!` absence. Missing
keys match inequality/notin and absence. At most eight terms and 256 query
characters are accepted. Field selectors accept equality/inequality only.

The deliberate field subset is metadata.name/namespace for API resources;
status.phase and spec.nodeName/schedulerName/hostNetwork for Pods;
spec.unschedulable for Nodes; and status.successful for Jobs (mapped to the API
status.succeeded value). Omitted booleans default to false; omitted Job succeeded
counts default to zero. Arbitrary JSON paths, annotations and Secret data are
excluded. These are filters over the owned snapshot, not server-side selectors
or a claim to implement every kubectl field selector. No per-keystroke API calls
are made. Plain/regex/fuzzy filters do not decode manifests. Metadata filtering
runs in an owned worker with a 250 ms total budget and a one-snapshot cache;
regular expressions retain their independent 50 ms total deadline. Invalid or
timed-out queries retain all rows with a visible error, never partial matches.

`:errors` toggles resources with observable failures or unready conditions.
Unknown health is omitted and counted separately; it is not presented as healthy.
Completed successful Pods remain successful despite historical restarts. A CRD
without understood health conditions can be unknown. This is a local observation,
not a replacement for alerts or provider-specific health evaluation.

## Wide columns and marked rows

`:wide` temporarily expands the current resource's available fields. Pods gain
Node, IP and QoS. Turning wide off restores the configured layout; the toggle
does not save or replace preferences. Typed sorting and stable UID selection
continue to apply.

Space toggles a visible resource mark. Shift+Up/Shift+Down extend a range in the
current filtered, sorted order. `:mark`, `:range`, `:selectall` and `:selectnone`
provide alternatives when terminal modifiers are unavailable. Selection is
bounded to 100 UIDs, pruned when rows disappear from the filter, and cleared on
scope changes. Same-name replacement objects never inherit an old UID's mark.
`:deletebatch` reviews the marked rows when marks exist, otherwise the bounded
visible rows as before. Existing confirmation, UID checks, default Cancel and
read-only restrictions remain in force.

## Namespace favorites

`:favorite add team-a` or `:favorite remove team-a` explicitly saves a namespace
under the captured context in the preference file. There are at most 64 names
per context and 128 contexts. No kubeconfig or cluster mutation is made.
`:favorites` shows the ordinary namespace workspace filtered to those favorites;
`:ns` shows all namespaces again. Favorites do not fabricate API rows or grant
namespace-list permissions.

```yaml
schema_version: 1
navigation:
  schema_version: 1
  mouse: false
  favorites:
    demo-lab:
      - team-a
```

Mouse reporting is disabled by default. Set `navigation.mouse: true` and restart
to opt in. Keyboard alternatives remain available for every operation. Pilot
semantic clicks are a widget test mechanism, not proof that physical mouse
reporting is enabled in an ordinary launch.

## Consistent workspaces and nested commands

Details/YAML/events and help share the workspace header and frame. The captured
resource remains explicit; inspection content is still a read snapshot. Container
lists now refresh readiness, restart counts and waiting/running/terminated state
from the existing Pod watch, preserving selection by container name and viewport.
Long container feedback stays scrollable in the bottom status area; use Tab to
focus it and arrow/page keys to read the full message. Live row updates retain
existing action feedback.
No separate watch is opened for each container list. Deletion, replacement UID,
namespace/context change or fatal permission loss invalidates the old screen;
covered logs/shell work is closed and drained before client replacement. Late
worker results cannot make that old screen current again.

Container, resource inspection and log views have their own bordered `:` bar.
Typing `:` inside an input stays literal. Invalid/read-only commands retain the
view and its streams. Accepted scope navigation drains covered read owners before
switching; resource actions retain the originating UID instead of targeting a
hidden changed cursor. Local copy retains the captured view. Escape first leaves
a nested command/search input, then returns to the previous view. The embedded
shell continues to route keystrokes directly to the remote program.

`:headless` toggles the shortcuts/logo area; `:crumbsless` toggles identity/trail;
`:fullscreen` hides headers/trails/frame borders. Command, search and status stay
available. These are session controls and do not change saved preferences. The
existing log `z` toggle remains local to that log view; either fullscreen mode
can hide its header without overriding the other mode.

## Explicit clipboard writes

`:copy` copies visible selected resource names, `:copyns` their namespaces and
`:copytext` the bounded table text. Marked rows are used when present. Ctrl+Y on
the root table copies its selection's name. Existing inspection/log/review copy
actions retain redaction. Explicit Secret-value copying keeps its separate
reveal/copy policy; values are never included in a failure message.

`KUBERICH_CLIPBOARD=auto` (default) selects native plaintext on local macOS,
foreground-owned xclip on local X Window System, and OSC52 over SSH or without a native
session. `native` requires an available macOS and X Window System backend; `osc52` explicitly
selects the terminal. Native X Window System requires xclip on PATH and DISPLAY, and is not
selected for Wayland sessions. Native macOS uses the system osascript/AppKit
plaintext API; no Python clipboard package is needed. Missing auto helpers can
fall back to a bounded terminal request; forced-native failures are visible.

Native/headless copies accept at most 1 MiB UTF-8; OSC52 accepts at most 64 KiB.
Oversize or invalid UTF-8 is refused rather than truncated. The application only
writes clipboards; it never reads them to acknowledge a copy. Headless/Pilot
copies remain memory-only. Native X Window System keeps an owned selection process until
replacement or exit; persistence after exit depends on a clipboard manager.

OSC52 payloads are base64 framed, so copied escape sequences stay inert data.
Inside tmux the request uses tmux passthrough framing. A user-managed tmux server
must permit `allow-passthrough on` for its visible pane, and the outer terminal
must permit clipboard writes. KubeRich never changes a user's tmux server.
A sent request is not proof that a physical terminal accepted it. Clipboard
reads in qualification are limited to synthetic data already written on an
owned Xvfb display or explicitly owned ephemeral macOS runner.

````

## docs/resource-inspection.md

SHA-256: `7029ad9dc44c2daf4c0b3845224e0525684aafc43b357bb5d37a6c3a8fcd34f6`

````markdown
# Inspecting a pod

Select a live pod row, then press `d` for details, `y` for YAML, or
`e` for its related events. The viewer shows the captured context, namespace and
resource name. These actions work in read-only mode and make only API reads.

The buttons and `y`/`d`/`e` switch pages. Arrow keys, PageUp/PageDown and the mouse
scroll the text; horizontal scrolling retains long lines. `m` switches to YAML
and toggles `metadata.managedFields`. Press `/`, type literal text and Enter to
select the first match; `n`/`N` move through matches. Search is case-insensitive,
uses character positions for Unicode and lists at most 10,000 matches. An empty
query or a query longer than 256 characters produces no matches.

`Ctrl+Y` or Copy copies the selected redacted text, or the current page when
there is no selection. Published 0.1.0 sends OSC52 to the terminal. Next-release
source adds bounded native macOS and X Window System and explicit remote OSC52 backends; see
[clipboard behavior](terminal-navigation.md#explicit-clipboard-writes). A sent
terminal request does not prove physical clipboard receipt.
`Ctrl+C` retains the application's quit behavior. Escape leaves search first,
then closes the viewer. Back closes it directly. Returning retains the table's
filter, sorting, UID selection and viewport while live updates continue.

## Identity and errors

Opening captures the owned client, session generation and resource UID before
any await. An individual API GET must return the same name and UID; the table's
cached manifest is not a fallback for a denied or missing GET. Events use the
same captured client and namespace, with bounded paginated core/v1 reads. Only
records referencing the captured UID and namespace are included; name equality
alone never associates an old pod's events with a new pod.

A 403 states that read permission is denied; a 404 states the resource/API is
unavailable. An events error leaves YAML and details usable. Missing events
means none were returned for that UID, not that the pod has never had events.

The viewer is a captured inspection snapshot. Reopen it to refresh; automatic
viewer refresh is planned. Live updates to the same UID continue underneath.
Deletion, same-name recreation, scope changes and client replacement invalidate
the viewer, clear its text and prevent copying. Closing cancels and awaits
owned reads; serializer cancellation also drains its background thread.

## Ordinary-view redaction

YAML retains Kubernetes field names and values outside the documented redaction
policy; derived table columns never become manifest fields. Pod details present
metadata, scheduling, normal/init containers, volumes and status evidence.
They are an original resource summary, not an invocation of `kubectl describe`.

Ordinary views and clipboard content hide Secret/ConfigMap payload values,
inline environment values, command/argument arrays, annotation values, sensitive
key names and recognized credential text. Managed field managers, operation,
time and other metadata remain available when enabled; `fieldsV1` sets are
hidden because set keys may embed literal values. Secret references retain safe
identifiers where possible. There is no reveal-sensitive-data action in ordinary inspection.
The source checkout additionally provides a separate
[configuration data view](configuration-data.md) with deliberate per-key
reveal/copy. That view does not change ordinary inspection redaction.
The resulting YAML is an inspection document and may contain redaction markers;
it is not an apply/edit export.

Free text is additionally sanitized for known credential patterns and terminal
controls. Arbitrary unlabelled sensitive prose cannot be identified reliably;
fixtures deliberately verify the supported policy rather than claiming a
universal secret detector. TextArea displays plain text, so Rich markup in a
resource or event remains literal.

Individual text fields are limited to 65,536 characters, documents to 262,144
characters and nesting to 64 levels. Oversized documents fail explicitly instead
of producing partial YAML. Oversized related-event output reports its limit
while retaining resource details. Transport, collection count and memory bounds
remain those of the resource reader.

````

## docs/resource-jumps.md

SHA-256: `4e0ac45e6c6cde526708a956aad5735b25c5d5092d47ef4f1bc146b13b8a3753`

````markdown
# Jump to related resources

A jump opens a related view from the selected row. For example, a jump can go
from a Deployment to its pods, or from a node to the pods running on it. You
define jumps in the preference file. Published 0.1.0 packages do not include
jumps.

## Define a jump

Add a `jumps` section to the preference file shown by `kuberich info`:

```yaml
schema_version: 1
jumps:
  schema_version: 1
  definitions:
    pods:
      description: Pods selected by this Deployment
      source: apps/v1/deployments
      target: v1/pods
      labels: "{{ spec.selector.matchLabels }}"
    node-pods:
      source: v1/nodes
      target: v1/pods
      namespace: "*"
      fields: "spec.nodeName={{ metadata.name }}"
```

Each jump has a name and these fields:

| Field | Meaning |
|---|---|
| `source` | The view where the jump is available, as `VERSION/RESOURCE` or `GROUP/VERSION/RESOURCE`. Core resources omit the group. |
| `target` | The view to open, in the same form. Custom resources work too. |
| `namespace` | Optional. The namespace to open. `*` means all namespaces. Without it, the jump uses the namespace of the selected row, or all namespaces if the row has none. |
| `labels` | Optional. A label filter for the target view. |
| `fields` | Optional. A field filter for the target view. Use `labels` or `fields`, not both. |
| `description` | Optional. Up to 200 characters for your own notes. |

## Templates

`namespace`, `labels` and `fields` can include values from the selected row.
Write the path of a field between `{{` and `}}`:

- `{{ metadata.name }}` reads one value.
- `{{ metadata.labels["app.kubernetes.io/name"] }}` reads a key that contains
  dots or slashes.
- `labels: "{{ spec.selector.matchLabels }}"` turns a whole label map into
  `key=value` pairs.

Templates only read fields. They do not support functions, conditions, indexes
or any code. A value is used only if it fits in a selector: letters, digits,
`.`, `_`, `-` and `/`. If a field is missing, or its value contains other
characters, KubeRich does not open the jump and says why.

Label filters use the same syntax as `label:` in the filter box. Field filters
use the same short list of fields as `field:`, such as `metadata.name`,
`status.phase` and `spec.nodeName`.

## Use a jump

Select a row and type `:jump`. If one jump matches the current view, it opens.
If several match, KubeRich lists their names; type `:jump NAME` to choose.

The target view opens with the filter already in the filter box. Press Escape
to clear it. `:back` returns to the previous view.

The filter runs in KubeRich on the rows it already watches. It does not change
what is read from the cluster.

Run `kuberich config check` to check jump definitions without connecting to a
cluster.

````

## docs/log-viewer.md

SHA-256: `377294fe0c890f8caaeb3d0f4b3a3d0ea3c11109f90902ca51fa4e32c2e33e16`

````markdown
# Container log viewer

Select a connected pod and press Enter to open its [container table](container-navigation.md),
then Enter on a container to read its logs. Esc returns logs → containers → pods.

For the direct log shortcut, press `l` on a pod. A single regular container opens directly;
multiple regular/init containers open a selector first. `c` or **Container**
changes the selected container. Logs work in read-only mode and use the captured
context, namespace, pod UID and container, independently of resource watches.
They do not mutate kubeconfig or Kubernetes resources.

The title identifies the container/current-or-previous mode and target. `?` or
**Help** shows the complete context/namespace/pod, state and keyboard controls
when a narrow terminal truncates the header/status. Terminal sizes down to 40×12 retain
the target controls, log body, search and status.

## Controls

These keys act in the log body; letters in search/value inputs remain text.

| Key / control | Behavior |
| --- | --- |
| `c` / Container | Choose a regular or init container |
| `v` / Previous | Switch current/previous instance; previous is a finite snapshot |
| `o` / Window | Tail 1000, tail 100, all, head 1000, last 1/5/15/30/60 minutes, or an RFC3339 start time with Z/offset |
| `p` / Pause | Pause/resume delivery into retained history; backpressure the owned stream |
| `f` / Follow | Follow the newest retained output without changing reception pause |
| `g` / `G` (Shift+G) | Oldest/newest retained line; G explicitly resumes viewport follow |
| `j/k`, arrows | Move vertically; upward movement leaves viewport follow |
| Ctrl+F/B, PageDown/PageUp | Move one page |
| Ctrl+D/U | Move half a page |
| `h/l`, left/right | Horizontal movement when wrap is off |
| `w` / Wrap | Toggle wrapping; reflow at current terminal width |
| `t` / Time | Hide/show requested timestamps without reopening the stream |
| `L` | Keep horizontal offset during automatic follow |
| `/`, Enter, `n/N` | Literal case-sensitive search, then next/previous matching retained line |
| `C` | Clear retained history and marks; keep the selected stream |
| `m` | Mark/unmark the first visible retained line; marks expire with evicted lines |
| `z` | Toggle fullscreen |
| Ctrl+Y | Copy retained redacted timestamped output, at most 1 MiB |
| Ctrl+S | Save retained redacted timestamped output to an explicit new file |
| `?` / Help | Read all controls and the complete state |
| Esc / Back | Leave an input, then return to containers (Enter path) or pods (`l` path) |

Reading older output does not pause reception. Pausing reception does not freeze
navigation, search, wrapping or help. G/f do not unpause a paused stream. A paused
stream retains no growing application queue; delivery waits for resume. Socket
and transport buffers remain separately bounded by their libraries. A graceful
end is **Stream complete**, including an empty stream. An opened quiet follow
says **Waiting for log output**. Permission, deleted pod, previous-instance,
network and timeout errors have explicit safe messages; there is no automatic
replay. Reselect the container/window or close and reopen to request history again.

Changing container, instance or read window cancels and awaits the old read, clears
the old history, then opens the captured target with new options. Head 1000 reads
from the oldest available server output and closes after the first 1000 lines;
normal other windows retain the newest output. Kubernetes retention/rotation may
have removed older server output. Since-time is sent in UTC. Reopening can repeat
historical output; timestamps are not unique line identifiers.

## Retention, rendering and target ownership

The consumer retains at most **10,000 lines AND 4 MiB of UTF-8 text**, with a dropped
line counter. Either bound evicts oldest entries and their marks. g/G and search
operate on that retained history; they cannot recover evicted output. Clearing
history resets its eviction counter and keeps monotonically increasing internal
line identities, so marks cannot accidentally select a later reused row.

Rendering is coalesced at 50 ms intervals. The virtualized body caches only
retained primitive text, cell-width and highlight-range descriptions. Actual
styles, segments and viewport strips are constructed on demand. At most 128
rendered Strip entries are cached, independently of terminal height; expired
line identities and replaced projections are pruned; theme changes also invalidate
cached styles without reopening a reader. It does not rebuild one giant
text document on every received line. Layout work yields every 16 entries and
reception every 64 lines. Reflow/search uses an owned serialized layout operation.
The top visible line identity and horizontal offset survive arrivals and reflow;
if that line is evicted, the viewport clamps to the oldest retained output.
Layout/cache memory is bounded additional storage, separate from the 4 MiB text
bound. Overall resident memory and maximum-load responsiveness still need
separate sustained performance validation.

Scope/client changes and disappearance/recreation of the selected pod invalidate
and clear the viewer, including while a child container/window/save prompt is
open. Display/copy/save require the captured target to remain current. Read,
render and export tasks have lifecycle owners; dismissal stops them before
widgets disappear, and unmount awaits their completion. The underlying pod table
continues its owned watch and preserves surviving selection/filter/sort/viewport
when returning.

The [transport contract](container-log-transport.md) defines UTF-8 framing,
long-line truncation, literal control/markup handling, recognized credential
redaction, safe errors and the API's non-atomic UID limitation. Unlabelled
sensitive prose is not universally recognizable. Copy/save use timestamped
retained sanitized lines, regardless of timestamp visibility/wrap/search/marks;
there is no raw-output reveal switch. Saving creates a complete mode-0600 file
without replacing a file or symlink. The parent directory must exist. File work
runs outside the event loop and is drained on cancellation; an explicitly
requested save can finish while closing the viewer.

Clipboard receipt depends on the terminal, SSH and tmux configuration. Saved-export
browsing and richer export formats are planned. The controls below operate on
the log body; resource-table keys are described in the navigation guide.

## All-container and workload logs

Select an ordinary Pod, Deployment, ReplicaSet, StatefulSet, DaemonSet, Job or
CronJob row and press Shift+L (`:logsall`). Pod Enter still opens the container
list; Enter there opens only that selected container. Explicit generic-resource
routes retain read-only inspection and do not open aggregate logs.

Every aggregate line includes a stable source number, namespace, Pod, container
and actual Pod UID. Same-name Pod recreation gets a new source number and UID;
retained output remains distinguishable. Workload membership follows captured
controller UID/kind/API group/name in the same namespace. Deployments require
the Deployment→ReplicaSet→Pod chain; CronJobs require CronJob→Job→Pod. Matching
labels alone never establish ownership. Reading requires parent GET, namespace
Pod LIST/WATCH and Pod/pods-log GET; Deployment/CronJob also require intermediate
ReplicaSet/Job LIST/WATCH. A new container stays **starting** until its own
running/terminated status establishes log availability; Pod readiness and startup
probe success are not required. Waiting/CrashLoop containers can read a valid
last terminated instance; Previous requires that last instance's identity.
Missing previous history appears as **no prior** in the picker. Eligibility follows
the [pinned kubelet's log-state contract](https://github.com/kubernetes/kubernetes/blob/v1.36.4/pkg/kubelet/kubelet_pods.go#L1417-L1474).
A pre-open current-log 400 waits for changed container start evidence,
without polling. An opened, ended or failed stream never automatically replays.

The source picker (`c`) lists current, waiting, starting, failed, ended and recent
removed sources independently of the output filter. At most **eight readers**
run at once; this is KubeRich's limit. Automatic admission uses namespace/Pod/UID
and container order. Inspect a waiting row beyond that limit, then Enter to read
only it, or Space to toggle an explicit set of up to eight. Empty explicit
selection opens zero readers. `r` explicitly reopens that row and can repeat
history; `a` returns to automatic admission. Removed selections are pruned without
selecting a replacement UID. Cursor identity and scroll survive status/churn;
an expired selected row cannot open a different source.

The catalogue refuses more than **256 current sources** before opening excess
readers; choose a narrower Pod/workload view. It retains **64 recent removed
statuses** and at most one expired selected picker row. Ended/current sources
remain visible rather than being silently evicted and replayed. Historical source
identity remains only with bounded retained lines; removed status history beyond
64 is not a complete audit trail.

`s` filters retained output only and makes no reader requests. `J` changes between
plain prefixed lines and JSON Lines envelopes containing source identity, line
identity, timestamp and payload. Valid JSON values preserve their types and useful
fields after decoded credential-key/string redaction; ordinary `[INFO]`, `[1]`
followed by prose, literal markup and date prefixes remain plain text. Whole
`[1]` is a JSON array. Apparently structured malformed,
truncated or excessive JSON is visibly withheld. Structured parsing is limited
to depth 16, 512 values and 8,192 serialized characters; aggregate payloads have
a further **4,096 escaped-character** bound with a visible truncation marker.
There is no raw-secret reveal. Recognized patterns cannot identify every sensitive
phrase; inspect the sanitized export before sharing it.

Each source retains at most **500 lines and 256 KiB**; the aggregate retains at
most **10,000 lines and 4 MiB**. Accounting reserves the larger plain/JSON byte
representation, including identity prefixes and control expansion. Either bound
evicts oldest lines and marks. Lines appear in delivery order with monotonic local
IDs; clocks may differ, timestamps can regress and transport delays can reorder
events. No global timestamp sort or synchronized cluster clock is implied.

The existing pause/follow, search, marks, wrap, column lock, fullscreen, windows,
previous-instance and timestamp controls remain available. Timestamp visibility
and plain/JSON changes reuse history without reopening readers. Changing window
or previous/current explicitly closes the old aggregate and can replay requested
history; head 1000 applies independently to each admitted source. Copy/save use
the current source filter/mode, preserve timestamps and identity, and sanitize
output. Copy is limited to 1 MiB; save uses a new complete mode-0600 file.

Formatting/export runs in owned workers; counters do not serialize the full
history on the event loop. Leave, context change and shutdown drain membership
watches, readers, render and export work before captured client/TLS cleanup.
A closing viewer remains registered until that work completes; another aggregate
waits for it. An explicitly requested save may finish during close.
These are bounded retained-history controls. Embedded shells have their own
[local history, search and copy](container-shell.md). Sustained performance
validation remains separate from the documented buffer bounds.

## Try the workflow

From a trusted, installed version:

```sh
kuberich --context demo-lab --namespace demo-apps --readonly
```

The context and namespace above are fictional; replace them with your intended scope.
Select a pod and press `l`. Choose its container,
try `g` then `G`, `/` plus some visible text, and `p`/`f`. Esc returns to pods.
Report whether output matches `kubectl logs` for the same explicit target/window,
and whether follow, search, resizing and return work in your terminal.

````

## docs/container-navigation.md

SHA-256: `a74ff6e717eba656ff7ca466c9201e9c64ffc5894708c0de9301d6ea23970a8c`

````markdown
# Pod and container navigation

Select a connected pod and press Enter. A scrollable table shows the selected
pod’s regular and init containers, including pods with only one container.
Type labels distinguish App, Init and restartable init Sidecar containers.
Rows also show captured image, readiness, state/reason, restarts, probes,
CPU/memory requests/limits and ports. Status is matched by name; missing status
is explicit. See [column semantics](resource-workspace.md#container-details).
Press Enter or `l` on a row to open that container’s logs directly.
Press `s` or `x` for its [embedded shell](container-shell.md); read-only mode blocks
that action. `x`, `:shell` and `:exec` on pods also open this container picker.

Esc returns logs → containers → pods. Both tables retain their selection and
viewport. In logs, `c` still switches among all of this pod’s containers.
On the pod table, `l` keeps its direct shortcut: one container opens immediately,
multiple containers show the existing log picker. `d` opens resource details;
`y` and `e` open YAML and related events.

The container table supports arrows, PageUp/PageDown, `j/k` and `g/G` (Shift+G)
for first/last row. These letters remain log controls after opening logs.
The view fits 40×12 and 100×30 windows, with horizontal scrolling for long names.

Published 0.1.0 uses a captured snapshot. Next-release source refreshes the
open list from the owned Pod watch and invalidates it on UID/scope/permission
loss. See [terminal navigation](terminal-navigation.md). Ephemeral debug
container creation remains separate work.
Read-only mode supports container navigation and logs. No kubeconfig or cluster
resource is modified by opening these views.

The captured target includes context, client generation, namespace and pod UID.
Changing scope or deleting/recreating the pod invalidates selection, including
while logs cover the container screen. The backend independently checks pod UID
and container membership before and after opening the log stream. Closing logs
cancels and awaits their owned tasks.

For command suggestions, type `:ns ` and a prefix, use Up/Down to choose, then
Enter to accept and submit once. Tab accepts without submitting. Plain Enter
keeps literal commands and the bare `:ns`/`:ctx` selectors. Editing, leaving the
input or changing scope discards prior arrow selection.

See [log controls](log-viewer.md), [commands](command-navigation.md) and
[container shells](container-shell.md) for the next steps.

````

## docs/container-shell.md

SHA-256: `904656b07adba547937c9395c417402ea58f1bc44ee53115921d1f88a741c0c3`

````markdown
# Selected-container embedded shell

On pods, `x`, `:shell` or `:exec` opens the container table. Enter on a pod also
opens that table, including single-container pods. Choose a regular/init container
with arrows or `j/k`, then press `s` or `x` to launch its configured shell.
Enter/`l` still opens logs. Pod `s` continues to change the sort column.

KubeRich opens a full-screen **embedded terminal inside Textual**. Its frame keeps
context, namespace/pod and container visible while an owned PTY runs
[kubectl exec](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_exec/).
The actual shell prompt, ANSI colors, cursor movement and alternate-screen
programs are rendered by an emulator. Textual stays active throughout the session.

- `exit` or Ctrl+D returns to the retained container selection.
- Ctrl+] closes the owned exec session and returns to containers.
- Ctrl+C reaches the shell/program; it does not quit KubeRich here.
- Ctrl+Q quits KubeRich and cleans up the exec process.
- Escape, Tab, arrows, `q`, `:` and `/` reach the remote program while the terminal is live.
- After returning, Escape goes from containers to the retained pod table.

The frame consumes two columns and six rows; resizing a 80×25 terminal gives the
remote PTY 78×19 cells. Target lines are literal, redacted and clipped in compact
windows. A failed exec returns to safe, scrollable feedback. SIGTERM cleans up
and exits the CLI with 143 after terminal restoration.

## Review output without sending shell commands

Click **History**, or press Alt+PageUp / Shift+PageUp, to review a frozen copy of
normal-screen output. The remote program keeps running and receiving its actual
PTY size; its latest output and cursor stay in the live emulator. Full-screen
alternate buffers, such as an editor, do not enter normal-screen history.

- Up/Down or `j/k`, PageUp/PageDown and Home/End or `g/G` move through the capture.
  The mouse wheel scrolls only during review; clicking selects a row.
- `/` or Ctrl+F starts literal, case-insensitive Unicode search. Enter finds a
  match; `n/N` finds the next/previous match with wraparound. Escape cancels search.
- `v` or Space starts/ends a range; move to its other end. Shift-click also
  selects a range. `y` or Ctrl+Y explicitly copies the selected whole rows.
- Enter, Escape or `q`, or clicking **Live**, returns to the current remote
  screen. Search, selection, navigation and paste stay local during review.
  Ctrl+] still closes the session and Ctrl+Q still quits KubeRich.

At most **1,000 scrolled rows** are retained. The footer reports discarded live
history; a frozen capture retains its own rows while the live ring advances.
Resizing crops the capture to the new viewport without reflowing or modifying its
captured rows. Search accepts 256 characters and copy accepts at most 64 KiB after
control escaping. Copy redacts the recognized credential patterns used elsewhere
in KubeRich; it cannot identify arbitrary secrets printed by a program. Copy uses
the host clipboard mechanism, whose availability depends on the outer terminal.
Remote OSC52 clipboard requests remain inert. Nothing copies automatically.
Closing, stale-target cancellation and repeated sessions release the capture,
history and session-owned cell cache. See [history evidence](acceptance/terminal-history.md).

## Requirements and preferences

Install kubectl on PATH, using a [client version supported by your cluster](https://kubernetes.io/releases/version-skew-policy/#kubectl).
Use trusted Kubernetes configuration and credentials; configured exec-auth
helpers remain trusted local programs. The selected account needs pod reads
and pods/exec permission; the Kubernetes server makes the authorization decision.
Read-only mode blocks shells before file preparation or executable lookup.

The default image command is `sh`. To choose another shell, edit KubeRich
preferences and restart:

```yaml
schema_version: 1
shell: ["/bin/bash", "-l"]
```

This is an argument list, with 1–32 nonempty strings. It is passed literally after
kubectl's `--`, without shell interpolation. The image must contain that program.
`config check` validates the preference; it does not connect or execute anything.
Initial `--command shell` is unavailable because launching a shell requires a
selected pod and container. The interactive aliases take no command arguments.

## Captured scope and return

The action captures the owned client/session, context, namespace, pod name/UID,
container, shell argv, environment and working directory before awaiting work.
A GET verifies that the pod still has the captured UID and container, and that
it is not deleting or completed. Scope invalidation blocks launch. A replacement
between that check and kubectl's server request remains a Kubernetes race:
exec-by-name has no atomic pod-UID precondition. KubeRich does not claim otherwise.

Kubectl uses a private snapshot of the prepared session's endpoint, TLS material
and credential mechanism, with explicit context/namespace/pod/container flags.
Changing the original kubeconfig after connection cannot redirect this action.
The snapshot is mode 0600 inside the owned mode-0700 SDK directory and is deleted
after return or cancellation. Certificate files live until their client closes.
The original kubeconfig and current-context are never rewritten.

Missing local kubectl, denied pod reads, deleted/replaced pods, unavailable
containers and nonzero exec exits produce safe feedback. Exit 126/127 suggests
an unavailable image shell. Other kubectl failures name the exit code and
permission/state/shell checks; raw stderr appears only in the deliberately
opened embedded terminal and is not retained in UI diagnostics. Exec is never retried
automatically. An image without a shell requires a suitable image or the later
ephemeral-debug workflow, not an invented SSH connection.

## Verification and remaining scope

See [shell verification evidence](acceptance/S04.md) and the
[embedded-terminal acceptance](acceptance/embedded-shell.md) for qualified
commits, coverage, actual terminal/cluster trials and unavailable platform checks.

Behavioral checks cover immutable capture, exact arguments, private file modes,
UID replacement, stale views, read-only policy and repeated cancellation/cleanup.
Pilot trials cover selected-container launch, compact feedback and retained
cursor/viewport. Source and freshly installed CLI PTYs cover actual child controlling-terminal
ownership, input, resize, Ctrl+C, fullscreen use, failures and terminal restoration.

The isolated Kubernetes trial creates and deletes its own cluster and fixtures:

```sh
uv run python -m scripts.verify_shell_kind --kind /path/to/kind --kubectl /path/to/kubectl
```

It requires kind 0.33.0 and kubectl 1.36.4, pins the Kubernetes 1.36.4 node and
Alpine images by digest, and exercises the actual CLI with two containers,
configured/default/missing shells, full-screen vi, resize, interruption, repeated
return and denied pods/exec. It also edits only its owned source kubeconfig after
connection to verify the prepared session remains pinned. Evidence is written to
`artifacts/cluster/shell.json` and `artifacts/terminal/kind-shell-*`.

Native POSIX terminal, SSH and tmux behavior is tested separately from
real-provider authentication. [Attach and file transfer](container-attach-copy.md)
have separate workflows; node shells and new ephemeral debug containers are planned. This checkpoint supports shell keys, bounded Unicode paste,
ANSI/256/true colors, cursor reports and alternate screens. It does not implement
mouse reporting, terminal graphics or advanced keyboard protocols. There is no
promise that every terminal program is compatible or that K9s parity is complete.

Output storage is limited to two 400×150 cell screens, 32 code points per cell,
1,000 history rows, one frozen capture of at most 1,150 rows, a session-owned
1,024-entry immutable cell cache, a single saved cursor and 128-byte control
sequences. PTY reads backpressure at
8×16 KiB and pending input at 64 KiB; paste accepts at most 16,384 characters.
Remote OSC/DCS/APC/PM/SOS strings, including clipboard/title/link/image commands,
are consumed without being relayed to the host. Terminal output is deliberately
visible to its operator and is not stored in application diagnostic logs.

[Pyte 0.8.2](https://github.com/selectel/pyte/tree/0.8.2) is an unmodified,
dynamically imported LGPLv3 dependency, pinned in pyproject.toml and
uv.lock. KubeRich's own adapter/widget code is original Apache-2.0 code; no upstream
widget source is copied. Pyte's license and replacement/source availability must
be preserved in standalone distributions, together with license and SBOM checks.

````

## docs/container-attach-copy.md

SHA-256: `f2278b9a4949831c0d9f06f2e0ebef7b9b1bc77b9a5f2a9502add6977bfb83d2`

````markdown
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
[file-transfer verification evidence](acceptance/container-transfers.md).

````

## docs/port-forwards.md

SHA-256: `28c338e5821eeb7de0aeee9a3d171d14d5c3670c9ff26b1a08931af4aa3b96be`

````markdown
# Managed TCP port forwards

KubeRich supports pod and core/v1 Service forwarding through your installed `kubectl`.
It captures the selected context, namespace, resource UID and connection settings.
No command changes your original kubeconfig or its current context.

1. Open pods with `:po` or Services with `:svc` and select a row.
2. Press **Shift+F** (`F`) or submit `:portforward`.
3. Enter one to eight comma-separated `local:remote` TCP mappings.
   `8080:80` requests local 8080; `:80` or `0:80` asks for an available local port.
   The initial remote port is a hint from the first declared TCP port, or 8080.
   Remote ports can also use a declared port name: `8080:http` or `:http`.
   Pod mappings can qualify a regular container: `web::8080:http`. Ambiguous,
   absent and non-TCP names are rejected. Service names resolve to Service ports;
   `kubectl` translates their target ports on the selected backend.
4. Keep `127.0.0.1` for access from this machine. A different literal IP address
   can be entered; a non-loopback address also requires selecting **Allow
   connections from other hosts**. Hostnames, address lists and multicast are rejected.
5. Start opens the session list. **READY** means the live process actually
   reported all requested listeners and the captured UID passed another API read.
   **BOUND (LAST)** shows the observed local/backend ports; it remains historical
   after a session stops. For Services, the backend can differ from the requested
   Service port: a Service port 80 can forward to its selected pod's 8080.

`:pf` and `:portforwards` open this list again. `/` filters its public fields;
`j/k`, arrows and `g/G` navigate. **s** or **Stop selected** stops the selected
session and waits for its process group, listener and private connection file to
close. **STOPPING** distinguishes cleanup in progress from **STOPPED**. Escape
returns to your preceding resource view; leaving the list does not stop a forward.
Starting a new forward selects its new row. Status patches retain selection/scroll.

## Connection and resource lifetime

Forwards survive resource-view and namespace changes within the same connection.
Changing context, retrying/re-authenticating or replacing that connection stops
its forwards before SDK/TLS directory cleanup. Application exit stops all forwards.
The UI states these rules. Reconnections are disabled by default. The review form
can opt into **0–3 reconnect attempts** after a previously ready `kubectl` process
disconnects. A child that fails before readiness does not consume further retries,
including a failed replacement during reconnect. Correct the startup problem and
start a newly reviewed forward.
**RECONNECTING** appears only after the old process/listener/private file have
been cleaned up. Each attempt rechecks the captured UID and current connection,
uses fresh private connection material and starts a new owned process after
bounded backoff. Permission denials, deleted/replaced resources, lost context,
invalid readiness, occupied ports and explicit Stop are not retried. A Service
restart can select a different current backend. Dynamic local ports may change;
always read the newly observed **BOUND (LAST)** value after reconnection.

The owner checks the exact pod/Service UID before launch and after readiness, and
rechecks it every second while active. Missing, replaced, deleting or finished pods,
permission/connection loss and process death stop the affected forward. A selected
Service backend pod exiting can end `kubectl` before the Service itself changes.
Named declarations are also revalidated against the captured numeric mappings.
If a Service keeps its UID but reassigns the selected name to another port, the
forward stops and requires fresh review. Backend target-port changes are distinct
from Service-port changes and can be resolved on an opted-in restart.
The server resolves a kubectl target by name, so the UID checks reduce the
name/recreation race; they cannot make kubectl's server-side name resolution atomic.

The list is local to this application instance: up to eight active sessions and
32 recent records. Recent records contain target/status/ports, not credentials,
helper environment or raw subprocess output. It does not discover forwards started
by another terminal. Read-only mode allows listing but blocks starting forwards
before file, API and executable preparation.

`kubectl` must be available in the captured PATH. The process uses a private
mode-0600 kubeconfig staged in the captured client's owned directory, explicit
context/namespace and an argument vector. Existing provider/helper/environment
and connection override behavior is shared with embedded shell delegation.
A missing executable, occupied port, readiness timeout or denied operation gives
a bounded diagnostic without displaying raw helper output. Common Kubernetes
permissions are `get` on the target pod/Service, pod selection for Services and
`create` on `pods/portforward`; server RBAC remains authoritative.

## Presets and annotation shortcuts

The review form includes a **Preset** selector. Local named presets live in the
KubeRich preferences file; they do not modify kubeconfig or cluster manifests:

```yaml
schema_version: 1
forwarding:
  schema_version: 1
  auto_annotations: false
  presets:
    web:
      ports: "8080:http,9090:metrics"
      address: "127.0.0.1"
      transport: auto
      retries: 1
  contexts:
    example-production:
      auto_annotations: false
      presets:
        admin:
          ports: "0:https"
          address: "::1"
```

An exact context entry replaces the global forwarding preferences; unspecified
values in that entry use safe defaults. Limits are 32 presets per entry and 128
context entries. `manual` and `annotation` are reserved preset names.
`kuberich config check` validates the local structure without loading a cluster;
port-name resolution happens against the selected resource when starting.
Loading a preset never selects **Allow connections from other hosts**. A
non-loopback preset still needs that separate confirmation.

For migration, KubeRich recognizes `k9scli.io/port-forwards` and
`k9scli.io/auto-port-forwards` annotations. Comma-separated Pod values use
`container::[local:]remote`, for example:

```yaml
metadata:
  annotations:
    k9scli.io/port-forwards: "web::8080:http,metrics::0:metrics"
```

An omitted local port uses the resolved remote number; an explicit `0` or empty
local part requests a free port. Numeric remote ports are also accepted.
Service annotations use `[local:]service-port` without a container.
The auto key takes precedence if both keys exist. Invalid annotations stop the
action with a diagnostic; they do not silently fall back to different mappings.

**Annotations never start a listener merely because a resource is listed.**
Pressing **Shift+F** normally opens review. To allow an auto annotation to bypass
that review on later explicit **Shift+F** actions, set `auto_annotations: true`
locally or select **Allow auto-port-forward annotations for this context this
session** while starting a reviewed forward. The checkbox changes only this
running app's exact-context permission; it does not save files. With no local
opt-in, even an auto annotation opens review. Annotation shortcuts always use
loopback, automatic transport selection and no reconnections.

## kubectl transport selection

The review form and named presets accept:

| Value | Child process behavior |
| --- | --- |
| `auto` | Preserve captured `KUBECTL_PORT_FORWARD_WEBSOCKETS`; otherwise use kubectl's default. |
| `websocket` | Set `KUBECTL_PORT_FORWARD_WEBSOCKETS=true`; kubectl can fall back to SPDY if the upgrade fails. |
| `spdy` | Set `KUBECTL_PORT_FORWARD_WEBSOCKETS=false`. |

Only the owned child's environment changes. KubeRich does not modify your shell
environment, helper identity or other sessions. These labels select kubectl's
behavior; they do not claim to observe which protocol the server negotiated.
This flag is separate from `KUBECTL_REMOTE_COMMAND_WEBSOCKETS`, which controls
kubectl exec/attach/copy. A proxy or server rejecting both protocols still fails
visibly. See Kubernetes' [environment-variable reference](https://kubernetes.io/docs/reference/kubectl/kubectl/#environment-variables).

## Verification and remaining scope

[Acceptance evidence](acceptance/port-forwards.md) covers real loopback processes,
Pilot, actual source/fresh-install terminals and actual TCP/HTTP through an owned
kind pod and Service. Those fixtures never use the caller's active cluster.

This implementation accepts TCP ports and one bind address per session.
It does not discover external forwards or support UDP. See [attach and file transfer](container-attach-copy.md) for those
separate workflows. Real cloud-provider compatibility requires authorized trials.

Kubernetes documents the underlying [kubectl command](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_port-forward/)
and [pod/Service port-forward workflow](https://kubernetes.io/docs/tasks/access-application-cluster/port-forward-access-application-cluster/).

````

## docs/editing.md

SHA-256: `da15de68a20076b95cfd1254edf1ac29df4219b08b4fdad4db25dc69fc0c4732`

````markdown
# Edit a selected manifest

On a selected patchable resource, use `:edit` or Shift+E. Lowercase `e` still
opens events. This is an interactive action, rather than a startup `--command`.
The form captures context, namespace or cluster scope, name and UID. Cancel has
initial focus; `--readonly` refuses the action before a file or editor is opened.

1. Read and enable the local-disclosure checkbox. Your trusted editor receives
   the full manifest, including potentially sensitive values such as ConfigMap
   data. The source checkout also supports Secret manifest editing through the
   same deliberate flow; the published 0.1.0 package does not. See
   [configuration data](configuration-data.md). The displayed diff is redacted
   separately from the real patch.
2. Choose Editor. KubeRich reads the identified object and creates a private
   temporary directory (0700) and initial file (0600). The editor uses the native
   terminal and returns to the form. Its argument list comes from
   `KUBERICH_EDITOR`, then `VISUAL`, then `EDITOR`, with `vi` as the default.
   Quoted arguments are supported; shell expansion and pipelines are literal.
3. Review the diff and captured resourceVersion. Formatting-only edits send no
   PATCH. Failed or interrupted editors and invalid YAML cannot enable Apply.
4. Choose Validate. KubeRich checks the captured object and sends the exact
   conditional JSON Patch with `dryRun=All` and `fieldValidation=Strict`.
   Successful validation does not save the object. Cancel again has focus.
5. Choose Apply separately. The exact validated change receives a one-use
   confirmation and fresh identity/version verification before one conditional
   PATCH. `:writes` retains its public outcome without manifests or data values.

Reopening Editor or validating again invalidates previous confirmation. A version
conflict requires closing the draft and opening a fresh edit of the current
object; KubeRich does not overwrite, automatically merge or retry the old change.
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

````

## docs/mutations.md

SHA-256: `877ba0fc26c9779106b98b148b03d46ec8fbc8ad4a2b3b2249b06b2cece8ee4d`

````markdown
# Guarded resource changes

To change an annotation, select a patchable resource, run `:annotate`,
enter a key/value and choose Review. The
confirmation shows captured context, namespace or cluster scope, resource name,
UID, opaque resourceVersion and the intended annotation value. Enter after Review
focuses Cancel. Only deliberate Confirm sends the patch. Existing annotations
and resource data are preserved; Secret data is not exposed by this action.

`--readonly` blocks this action through the same policy used by initial commands,
interactive commands and effectful services. `:writes` remains available and
shows at most 32 operation records, including in-progress and uncertain outcomes.
History contains target identity, changed paths and fixed result messages;
annotation values, manifests, credentials and raw server errors are omitted.

Preparation uses a fresh individual GET. A one-use confirmation binds the exact
immutable request, captured client and API path. Execution revalidates identity
and version, then sends JSON Patch with UID and resourceVersion tests first.
Server-side tests close the race between reading and applying a change. A new
object with the same name or a concurrent update requires a new review.

| Result | Meaning and next action |
| --- | --- |
| Succeeded | A bounded valid API response confirms the captured object. |
| Blocked / stale | Policy, confirmation or target changed; no write started. |
| Permission denied / authentication failed | Check API permissions or reconnect; no write replay. |
| Conflict | Read the current object and review a new change. |
| Rejected (422) | A precondition or validation failed; inspect the current object. The status alone does not distinguish those causes. |
| Timed out / cancelled before write | Revalidation or credential preparation stopped before sending. |
| Write outcome uncertain | The request may have applied. Inspect the current object before another change. |

PATCH never follows redirects or refreshes-and-replays a 401. Failed, interrupted,
oversized or invalid responses after request start cannot prove nothing changed.
There is no automatic retry, including on throttling or server failure.

Leaving the form retains an already started bounded operation; use `:writes` to
see its outcome. Changing the captured client or exiting cancels and drains owned
requests/decoding before SDK cleanup, including a Review read still in progress.
Concurrent cleanup requests cancel that reader once and await its owned decoding.
This preserves an honest uncertain outcome for a write when
necessary. Eight concurrent operations and 32 recent records bound ownership.
API writes are not a sandbox or a replacement for server RBAC/admission.

[Manifest editing](editing.md) uses these guards after explicit local
disclosure, redacted preview and strict non-persisting server dry-run.
[Workload operations](workloads.md) add guarded scale/restart/rollback and independent
monitoring; [resource operations](resource-operations.md) add deliberate deletion,
independent batch outcomes and Job/CronJob actions. No complete operations-parity claim follows
from these actions.
Annotation keys use Kubernetes qualified names; the combined annotations are
bounded to 256 KiB and this form limits a value to 65,536 characters.

Sources: [Kubernetes conditional updates](https://kubernetes.io/docs/reference/using-api/api-concepts/),
[annotation syntax](https://kubernetes.io/docs/concepts/overview/working-with-objects/annotations/).

````

## docs/configuration-data.md

SHA-256: `891f8470afd470a9382c4f3a0703961bd71e09f7fa36c5b3a689dd2c44326fbf`

````markdown
# Inspect configuration data deliberately

This workflow is implemented in the source checkout for the next release.
The published 0.1.0 package keeps ordinary inspection redacted and does not
include this data view or Secret manifest editing.

Open `:cm` or `:secrets`, select a row, then press Enter or `v`. The data view
shows key names, storage fields, text/binary classification and decoded byte
counts. Values start hidden, including ConfigMap values. The header identifies
the captured context, namespace and resource. `d` and `y` in the resource table
continue to open ordinary redacted details and YAML.

| Control | Result |
| --- | --- |
| `r` or Enter on a key | Reveal the selected value; press `r` again to hide |
| `x` | Toggle decoded UTF-8 and Base64; hide the previous value |
| `Ctrl+Y` or Copy | Copy the selected representation explicitly |
| Shift+R or Reload | Read current key metadata; clear any displayed value |
| Escape or Back | Close the view and return to the resource table |

Changing the selected key hides the previous value. Binary data can be revealed
or copied as Base64; decoded mode refuses invalid UTF-8. Base64 is an encoding,
not encryption. A malformed stored value produces a content-free error.

Every reveal and copy performs a fresh GET using the captured client, UID and
resource version. A changed object requires Reload before disclosure; a replaced
object or changed context/scope requires selecting the resource again. Read-only
mode allows deliberate reads and copying but blocks editing. Kubernetes read
permissions still apply: a denied GET cannot fall back to cached table values.

## Limits and local disclosure

The data view accepts up to 1 MiB of decoded data across at most 4,096 keys, and
at most 2 MiB of serialized resource data. A preview displays at most 16,384
characters and visibly reports truncation. Clipboard output is limited to
64 KiB of UTF-8 bytes; it is never silently truncated. Terminal controls are
escaped in the preview. Explicit clipboard output contains the selected original
text or Base64, sent through Textual's OSC52 support. Your terminal must allow
clipboard writes; copying is a local disclosure and does not prove clipboard
receipt on every terminal, SSH client or multiplexer.

Ordinary details, YAML, diagnostics and write receipts retain redaction. Built-in
SVG screenshot export is refused while the configuration data view is open,
including when values are hidden. Closing clears the view and drains owned reads
before disconnecting its client. This does not erase terminal scrollback,
clipboard history, external screenshots or process memory securely.

## Edit a ConfigMap or Secret

Close the data view and use Shift+E or `:edit` on the resource table. Explicitly
acknowledge that the trusted local editor receives the full manifest, then use
Editor, Validate and a separate Apply. The review stays redacted. Drafts have
private permissions and are removed on graceful close. Identity, resource-version
conflicts, read-only mode and server authorization use the same guarded workflow
as other manifest edits. Immutable fields and immutable Secrets/ConfigMaps remain
subject to server rejection; there is no forced overwrite or automatic retry.

The editor accepts one UTF-8 JSON-compatible YAML document of at most 1 MiB;
a large encoded manifest can exceed that bound even when its decoded values fit
the inspection limit. See [manifest editing](editing.md) for editor selection,
validation, cancellation and cleanup limits.

````

## docs/workloads.md

SHA-256: `7676830b975b845376bc93d99edfba2bdb296856e697611c0e4cd6920a56305e`

````markdown
# Workload operations

Select a workload in its resource table before opening an action. Commands capture
the selected context, namespace, name and UID. They require an interactive
selection rather than a `--command` startup view.

| Command | Resources | Behavior |
| --- | --- | --- |
| `:scale` or `:scale 3` | Deployments, ReplicaSets, StatefulSets | Review replicas, then separately Confirm a guarded `/scale` patch. |
| `:restart` | Deployments, StatefulSets, DaemonSets | Review a pod-template timestamp change, then Confirm. |
| `:rollback` or `:rollback 1` | Deployments, StatefulSets, DaemonSets | Restore the template from one explicit retained controller revision. |
| `:rollout` | Deployments, StatefulSets, DaemonSets | Read actual controller progress, including in read-only mode. |

Cancel has default focus. Input Enter prepares a review without writing. Review
identifies the resource/version/effect; separate Confirm consumes one prepared
change. Changed input invalidates the review. Counts range from 0 to 2147483647;
zero stops replicas. StatefulSet scale-down review discloses PVC deletion when
its actual retention policy requests it.

Scale requires workload get and `/scale` get/patch access, without parent patch
permission. Namespace HPA list access checks ownership; an HPA targeting this
workload blocks manual scale. Absent autoscaling v2 falls back to v1; denied or
invalid checks block preparation. An HPA can appear after the check: this is not
a cross-resource atomic transaction. ReplicaSet owners can reconcile manual replicas.

Restart/rollback require parent get/patch. Paused Deployments refuse these actions.
`OnDelete` StatefulSets/DaemonSets need deliberate pod deletion; automatic restart/
rollback is refused. Rolling partitions are respected, without resetting strategy.

Rollback reads Deployment ReplicaSets or StatefulSet/DaemonSet ControllerRevisions
owned by the captured UID. One explicit positive retained revision is required;
absent, ambiguous or unsupported history is refused. Its UID/version is checked
again before writing. Only the template is restored; replicas and strategy stay
current. Failed StatefulSet recovery may require deliberate removal of a failed
pod after rollback; this action does not force-delete pods.

The [shared mutation guards](mutations.md) provide one-use confirmation, atomic
UID/version tests and no automatic replay. Conflicts need a new review. `:writes`
retains confirmed/uncertain outcomes without manifest values. Leaving a confirmed
write view does not undo or repeat the request. Context change/exit drains it.

Monitoring reads observed generation, controller counters, Deployment deadline
failure, paused state and StatefulSet revisions/partitions. API confirmation does
not imply rollout completion. Cancel/Escape stops monitoring without claiming an
undo. After five minutes it times out; reopen progress with `:rollout`.

Sources: [Deployment controllers](https://v1-36.docs.kubernetes.io/docs/concepts/workloads/controllers/deployment/),
[StatefulSet controllers](https://v1-36.docs.kubernetes.io/docs/concepts/workloads/controllers/statefulset/),
[DaemonSet controllers](https://kubernetes.io/docs/concepts/workloads/controllers/daemonset/).
See [acceptance evidence](acceptance/workloads.md) for measured scope and limits.

````

## docs/resource-operations.md

SHA-256: `641a2c646381995b8df5e887d3a1372cb065e2a00829b22357b480bb7c63bedd`

````markdown
# Delete resources and operate Jobs

Select a resource in a connected table, then use a command below. These commands
require write mode; `--readonly` blocks both the UI and service paths. Local
contexts are configuration entries and cannot be deleted through Kubernetes. To
remove one from kubeconfig, see [rename or delete a context](context-sessions.md#rename-or-delete-a-context).

| Command | Captured effect |
| --- | --- |
| `:delete` | Delete the selected resource UID/version. |
| `:deletebatch` | Choose exact targets from the currently displayed, filtered rows. |
| `:cleanup` | In the pods view, review deleting the completed and failed pods shown. |
| `:trigger` | Create one manual Job from the selected batch/v1 CronJob template. |
| `:suspend` | Set the selected batch/v1 Job or CronJob's `spec.suspend` to true. |
| `:resume` | Set its `spec.suspend` to false. |
| `:writes` | Read retained outcomes, including every item in a batch. |

## Review and confirmation

The form shows context, API/resource, namespace or cluster scope and UID. Review
reads current versions and captures immutable request bytes. Cancel receives
focus after review; Enter there cancels. A separate Confirm submits the reviewed
operation once. Changing selection or options invalidates review.

For deletion, choose a propagation policy and optional grace seconds. Blank uses
the server default. Type `DELETE 1` for a single resource, or `DELETE <count>`
matching the reviewed batch count, before Confirm. Batch mode selects nothing
automatically: Space toggles individual rows. Filter a large table first; a batch
is limited to 100 exact targets, which can include explicitly reviewed namespaces
from an all-namespaces view. It never sends collection-wide DELETE.

| Propagation | Consequence |
| --- | --- |
| Foreground (default) | Dependents are cleaned before the owner finishes deletion. |
| Background | The owner may disappear while dependent cleanup continues. |
| Orphan | Dependents remain; their owner references are handled by Kubernetes. |

Zero grace requests immediate termination where supported. It does not bypass
finalizers, guarantee an underlying process has stopped, or establish cleanup of
external storage. Deleting pods may cause controllers to recreate them; deleting
namespaces, workloads or storage can affect other resources. Review the scope.
Already terminating resources are refused; inspect their finalizers instead.

Each DELETE includes server-enforced UID and resourceVersion preconditions.
Same-name replacement or concurrent modification is refused. Existing finalizers
are disclosed in review and observed afterward; this tool never removes them.

## Results and batch behavior

**Accepted; deletion pending** means the API accepted the request while completion
remains pending or could not be observed. A successful follow-up read showing
absence establishes removal of the captured object, not dependent cleanup. If a
replacement is observed, it is reported and left untouched. Permission denial,
conflicts, stale captures and uncertain writes remain distinct.

Batches execute sequentially with one request per target and independent results.
A denied or stale item does not conceal successful earlier items. There is no
transactional rollback. Leaving the form keeps the confirmed operation owned by
the write manager; `:writes` retains every target's result. Context replacement
or app exit drains the operation; an interrupted request can be uncertain while
remaining unsent items are marked cancelled. Up to 32 operation records are
retained in the application session; they are not a persistent audit log.

No write follows redirects, refreshes/replays a 401, or retries transport/server
failures. In particular, DELETE connection replay is suppressed through the HTTP
client's public middleware. If the response is lost, inspect actual cluster state
before making a new deliberate change.

## Clean up finished pods

In a connected `:pods` view, type `:cleanup`. KubeRich lists the pods in the
current view that have finished: completed pods and failed pods, such as evicted
ones. Running and pending pods are never listed. Pods that are already being
deleted are skipped. Filter the view first to narrow the list.

Each row shows the namespace, name, state and UID. Every listed pod starts
selected; press Space to keep one. Then use the normal delete review: choose
Review, type `DELETE <count>` and Confirm.

KubeRich checks every pod again before deleting it:

- If a listed pod is removed or replaced (it gets a new UID) before Confirm,
  nothing is deleted. Run `:cleanup` again and review the new list.
- If a pod only changed after Review, that pod is not deleted and its result
  shows a conflict. The other pods are still deleted.

One cleanup handles at most 100 pods; run it again for the rest. `--readonly`
blocks cleanup.

## Manual Jobs and suspension

Run now uses a fresh CronJob template snapshot and reports the exact Job name,
namespace and returned UID. It copies template labels, annotations and Job spec;
it does not copy managed metadata or owner references. The manual Job is
independent and remains discoverable through `:job`. The name carries a one-use
request identity. Repeating the same captured request uses that same name and
gets a conflict rather than creating a second Job. No automatic replay occurs;
opening another form for a new explicit run creates a new request identity.

The preview and retained result include the name even when creation is uncertain.
Manual runs can occur while a CronJob is suspended and do not enforce its schedule
or concurrency policy. Template settings such as Job suspension/TTL remain part
of the copied spec. Source revalidation and creation are separate API requests:
there is no atomic cross-resource transaction if the CronJob changes afterward.

Suspension uses a guarded JSON Patch of one boolean. Suspending a CronJob stops
future scheduled runs, not its existing Jobs. Resuming can cause missed runs to
start immediately. Suspending a Job terminates its active pods; resuming restarts
execution and can reset its start time. Review these consequences before Confirm.
The API's RBAC and admission policies remain authoritative.

## Verification

Resource operations are verified with decision tests, actual HTTP/TLS fault contracts, Textual Pilot,
native source/fresh-wheel terminals and an owned-kind verifier:

```sh
uv run pytest tests/unit/test_operations.py tests/contract/test_operations.py tests/ui/test_operations.py tests/terminal/test_operations.py
uv run python -m scripts.verify_operations_kind --kind /absolute/path/to/verified/kind --evidence artifacts/cluster/operations.json
```

The verifier creates its own explicit cluster and removes it afterward. It never
uses the developer's active context. See [acceptance evidence](acceptance/resource-operations.md)
for measured qualification and remaining platform/cloud limits.

Sources: [Kubernetes DeleteOptions](https://kubernetes.io/docs/reference/kubernetes-api/definitions/delete-options-v1-meta/),
[finalizers](https://kubernetes.io/docs/concepts/overview/working-with-objects/finalizers/),
[CronJob suspension](https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/#schedule-suspension),
[Job suspension](https://kubernetes.io/docs/concepts/workloads/controllers/job/#suspending-a-job).

````

## docs/configuration.md

SHA-256: `e8977ad4b432621cdb5bbfccd79197f76e61236c3247c00dbb497c7953d3608c`

````markdown
# Local preferences and diagnostics

KubeRich provides `info`, `config init`, `config check`, `config migrate`, and local
diagnostic logging, alongside the [resource workspace](resource-workspace.md).
Preference inspection does not connect to Kubernetes. The UI applies built-in themes and displays
read-only mode in both header/status and shared command decisions. The native shell service applies the shared read-only guard before preparation.

The next-release source adds [theme preview and context preferences](themes.md),
including the explicit local save controls and an opt-in cached version notice.
The published 0.1.0 package does not include those controls. `config check` in the
source validates custom palette fields, contrast and registered theme references;
invalid appearance settings leave files unchanged. It also checks
[jump definitions](resource-jumps.md).

## Legacy preview compatibility

KubeRich uses `kuberich` for its package, Python imports and canonical command.
The `kubetrol` console command remains an alias to the same entry point for the
initial preview. Its help/version identify KubeRich. The old Python module and
distribution are not duplicate packages; use `python -m kuberich` for module
launch. Removing the alias requires a later minor release and migration notes.

Default preference selection is CLI `--config`, then `KUBERICH_CONFIG`, then
`KUBETROL_CONFIG`, then the platform's KubeRich file. If no KubeRich file exists,
the old platform Kubetrol `config.yaml` is read in place. An existing or broken
symlink/directory/invalid KubeRich file never silently falls back to old settings.
Each `KUBERICH_*` preference variable wins over its corresponding `KUBETROL_*`
alias; CLI overrides still have highest precedence. Explicit files never fall
back to another location. Environment-provided relative log paths retain the
launch directory rather than the preference directory.

`info` reports the file actually read, whether migration is pending and the new
target, without writing either file. `config check` and ordinary loading also
leave preferences unchanged. `config init` refuses to replace existing legacy
preferences. Use `config migrate` with default paths and without runtime overrides
to create a mode-0600 KubeRich file atomically. It retains the original, unknown
fields, read-only policy and effective settings; relative file-provided log
destinations are made absolute to preserve their target. Existing legacy log/lock
headers and archives remain accepted for explicitly configured log destinations.
Default new logs use KubeRich's new platform directory.

An existing destination is never replaced, including a competing creation during
the commit. Repeating a completed migration validates the current file and makes
no change. Explicit `--config` or configuration environment paths cannot be
relocated implicitly by this command. It does not move kubeconfig, credentials,
diagnostic logs or tool installations.

## Commands

```sh
uv run kuberich info
uv run kuberich config check
uv run kuberich config init
uv run kuberich config migrate
uv run kuberich --config /path/to/preferences.yaml config check
uv run kuberich --log-level DEBUG --log-file /path/to/kuberich.log
```

Place global flags before a command. `--logLevel`/`-l` and `--logFile` are aliases
for `--log-level` and `--log-file`. `--config` selects **KubeRich preferences**;
`--kubeconfig` selects Kubernetes connection configuration for a terminal launch.

`info` prints JSON with installed versions, local config/data/log paths, validated
effective preferences, unknown-field count and migration status. It never prints
unknown field names/values, credential environment variables or kubeconfig
contents. `info` and `config check` create no files. They do not execute cloud
credential helpers or inspect/connect to a cluster.

`config init` creates schema-v1 defaults at the selected path. It never overwrites
an existing file, persists environment overrides, or creates diagnostic logs.
All runtime overrides are rejected for this command. You can edit the YAML with your
own editor and run `config check` afterward. There is no automatic rewrite on load.

## Paths and precedence

The config path is chosen from `--config`, then `KUBERICH_CONFIG`, then
`KUBETROL_CONFIG`, then the platform default with the legacy fallback described
above. Defaults follow [platformdirs](https://platformdirs.readthedocs.io/en/latest/api.html). An absent
default file uses the defaults below. An explicitly selected missing file fails
with exit 3; use `config init` to create it. Empty/comment-only files also use
defaults. Paths expand `~`, support spaces and reject control characters.

| Platform | Default preferences | Default diagnostic log |
| --- | --- | --- |
| Linux | `$XDG_CONFIG_HOME/kuberich/config.yaml` or `~/.config/kuberich/config.yaml` | `$XDG_STATE_HOME/kuberich/log/kuberich.log` or `~/.local/state/kuberich/log/kuberich.log` |
| macOS | `~/Library/Application Support/kuberich/config.yaml` | `~/Library/Logs/kuberich/kuberich.log` |

`info` reports the actual paths on your machine. Preference operations never
load Kubernetes credentials or change kubeconfig or its `current-context`. Files recognized as
kubeconfig are rejected as preferences. Startup never writes preference files.

Preference precedence is **explicit runtime CLI override → `KUBERICH_*`
environment → selected YAML → defaults**. Each layer is validated; a malformed
file/environment value fails even if a higher layer would override it. This
prevents an invalid lower layer from silently resurfacing on the next invocation.
The file is always read; log flags do not bypass a broken config.

| YAML field | Default | Environment | Runtime CLI |
| --- | --- | --- | --- |
| `shell` | `["sh"]` | Not available | Not available; configure YAML |
| `theme` | `k9s` | `KUBERICH_THEME` | Not yet available |
| `refresh_seconds` | `2.0` | `KUBERICH_REFRESH` | `--refresh`, `-r`; periodic table ages/local repaint, independent of live watches |
| `read_only` | `false` | `KUBERICH_READONLY` | `--readonly` / `--write` (mutually exclusive) |
| `log_level` | `WARNING` | `KUBERICH_LOG_LEVEL` | `--log-level`, `--logLevel`, `-l` |
| `log_file` | `null` (platform path) | `KUBERICH_LOG_FILE` | `--log-file`, `--logFile` |

Environment read-only values are `true`/`false`, case insensitive. Levels accept
DEBUG, INFO, WARNING, ERROR or CRITICAL, case insensitive, and are normalized to
uppercase in effective settings. Refresh must be a finite number
in 0.1–3600 seconds; booleans and numeric strings in YAML are rejected. Theme IDs
are 1–64 ASCII letters/digits/underscores/hyphens starting with a letter; available
themes must also be `k9s` or registered built-in Textual themes when opening the UI.
`config check` validates the schema, while the UI validates availability.
A null log path selects the platform
default, while an empty path is an error.

Relative `log_file` values from YAML resolve against that file's directory.
Relative environment/CLI paths resolve against the invocation's working directory,
including when their text happens to match the file's value.

Runtime choices never rewrite preferences. `--write` explicitly overrides a valid
file/environment read-only setting for this invocation. Read-only blocks commands
through a shared service decision, including the native shell service.
See the [launch contract](k9s-cli.md) for aliases, availability and command-specific
option handling. Per-context settings are described below.

## Per-context settings

A `context_settings` section can make one kubeconfig context stricter or change
how often its tables refresh:

```yaml
schema_version: 1
context_settings:
  schema_version: 1
  contexts:
    production:
      read_only: true
    staging:
      refresh_seconds: 5
```

Each context accepts only `read_only` and `refresh_seconds`. A context can turn
read-only mode on, but it cannot turn it off. `refresh_seconds` uses the same
0.1–3600 range as the global setting. Names are the kubeconfig context names, up
to 128 contexts.

The settings apply when you switch to that context and stop when you leave it.
The order is:

1. Command-line flags and `KUBERICH_*` environment variables.
2. The settings of the current context.
3. The global values in the preference file.
4. The defaults.

`--readonly` or a read-only file keeps every context read-only. `--write` does
not lift a context's `read_only: true`.

## Changing preferences while KubeRich runs

KubeRich checks the preference file every two seconds. When you save a valid
change, it applies the new themes, colors, aliases, jumps, context settings,
plugins, shell and refresh interval, and shows "Preferences reloaded." Your
current view, filter and selection stay as they are.

- Key binding and mouse changes are read but apply after a restart. The notice
  says so.
- Log settings apply after a restart.
- Turning `read_only` off in the file does not end read-only mode in a running
  session. Restart to leave it.
- Plugin files are read again when the preference file changes.
- If the file is invalid, KubeRich keeps the last valid preferences and shows the
  error once. Run `kuberich config check` to see it again.
- If the file is deleted, the current preferences stay active.

Fields that KubeRich does not know are kept in the file and ignored. Startup,
reload and `kuberich config check` name them, so a typo is easy to spot.

`shell` is a list of 1–32 nonempty strings, with an executable first and
literal arguments after it. Strings and shell expressions are rejected. For
example, `shell: ["/bin/bash", "-l"]` selects bash only in images that contain it.
A saved change applies to the next shell you open. Diagnostics omit this
argument list. See [native shells](container-shell.md).

## Schema, compatibility and writes

```yaml
schema_version: 1
theme: textual-dark
refresh_seconds: 2.0
read_only: false
log_level: WARNING
log_file: null
shell: ["sh"]
```

Unknown fields are retained in memory and preserved by the atomic save API; they
do not become effective settings or appear in diagnostics. Unknown schema versions
are rejected so older builds cannot overwrite a newer schema. Versionless/v0
preferences migrate `refresh` to `refresh_seconds` and `readonly` to `read_only`
in memory. Supplying both a legacy and current name fails. A later explicit save
writes version 1 while retaining unknown fields; current CLI commands do not
perform that migration write automatically.

YAML uses a [safe loader](https://pyyaml.org/wiki/PyYAMLDocumentation), unique string
keys and a 64 KiB input limit. Aliases, object-construction tags, multiple documents,
more than 20 nested collections and excessive parser events are rejected. Parser
errors identify the problem without echoing source values or source excerpts.

Writes use a mode-0600 temporary file in the destination directory, flush/fsync it,
and commit with an atomic link for creation or replace for an explicit save.
Creation cannot overwrite a concurrent writer. New application directories are
mode 0700; existing parent directories keep their permissions. Destination
symlinks are refused. A failure or interrupt before commit leaves the previous file
intact and removes the temporary file. A post-commit cleanup/directory-sync failure
returns exit 3 and explicitly says the preferences were saved but durability or
cleanup could not be confirmed; reread the file before retrying.

## Logging and errors

The ordinary CLI creates its local log and a small persistent `.lock` sibling,
both mode 0600. A nonblocking process lock permits only one writer per log path;
concurrent instances must use different `--log-file` values. Logs rotate at
approximately 1 MiB with three archives. Each formatted record is bounded to
8 KiB in UTF-8; total log storage is bounded by four times (1 MiB + 8 KiB), plus
the small lock file. Open files and locks are released on normal exit or failure.

Nonempty destinations and existing archives must have KubeRich's diagnostic
header. Foreign files, symlinks and nonregular files are refused rather than
modified. This includes a mistakenly selected kubeconfig. An empty regular file
is accepted. These checks prevent mistaken destinations; they are not a sandbox
against another program modifying files with the same user's privileges.

Logs use an application-owned logger without console handlers or root/SDK
logging configuration changes. Messages redact common tokens, Bearer/Basic auth,
JWTs, passwords, secret/access/API keys, private-key blocks, certificate data and
HTTP URL passwords. Terminal control and directional-control characters are
escaped. Debug exceptions include type and frame locations, excluding exception
values, source text, chained exception values and locals. Raw kubeconfig, external
command output, credential-helper responses and arbitrary API bodies must never
be logged; pattern matching is defense in depth, not proof that arbitrary text
contains no secret. Debug output stays in the file.

| Exit | Meaning |
| --- | --- |
| `0` | Successful command, help, version or normal UI quit (including Ctrl+C) |
| `1` | Unexpected internal/local failure; concise message without raw exception |
| `2` | Invalid arguments, settings, schema, YAML or a noninteractive UI launch |
| `3` | Missing explicit file, local permissions/I/O, existing init destination or log ownership failure |
| `4` | Recognized option/command requires behavior not shipped in this version |
| `130` | Interrupted non-UI operation |
| `143` | SIGTERM during a native shell, after cleanup and terminal restoration |

Argument parsing does not echo rejected arguments, which might contain tokens.
Settings errors name the setting without printing its value. Logging failures
cannot fall back to Python logging's raw-record stderr output.

The tests exercise temporary files, real wheel entry points, injected permission,
replace/fsync failures, interrupts, migration round trips, redaction, bounded
rotation and an actual second process competing for a log. They never use a real
cluster or the maintainer's kubeconfig.

````

## docs/themes.md

SHA-256: `f615a0ee468648956fc9e2bdf9bdb068631e4cbfd04d770e5797e03fba6148a5`

````markdown
# Themes and local appearance

These controls are implemented in the source checkout for the next release.
The published 0.1.0 package supports its configured built-in theme; it does not
include the theme picker, custom/context palettes, inversion or update notices.

Open `:themes` in the workspace, or launch `kuberich --command themes`.
The standalone picker reads local configuration without opening a Kubernetes
connection or executing authentication helpers. Arrow keys select a theme and
preview it immediately; Enter also previews. The Selected column and status text
identify the selection independently of its color.

- **Global** saves the selected global theme and the update-check checkbox.
- **Context** saves the theme for the context named in the dialog. It leaves the
  global theme and global update-check preference unchanged.
- **Back / Escape** restores the effective saved preferences. A preview or changed
  checkbox alone never writes a file or enables an external request.

A requested save finishes before the dialog can close. A save already requested
also finishes during graceful application exit. This is local configuration;
`--readonly` continues to allow appearance changes while blocking cluster writes.
Saving retains unrelated preferences and unknown fields. Runtime `--readonly`,
`--refresh`, log overrides and environment overrides are not written into the file.
A competing preference change is refused; restart to load it before saving.
Legacy Kubetrol paths require an explicit `kuberich config migrate` first.

## Which theme wins

The order is application environment (`KUBERICH_THEME`, then its legacy
`KUBETROL_THEME` alias), a matching context preference, the global `theme`, then
the built-in `k9s` default. An environment or context preference can therefore
continue to determine the effective theme after a global save; the dialog reports
that effective name. Context changes apply the corresponding theme immediately.

```sh
KUBERICH_THEME=textual-dark kuberich
kuberich --context demo-lab --command themes
kuberich --invert --command themes
```

`demo-lab` is fictional; choose an intended local kubeconfig context. `--invert`
reverses this session's resolved RGB palette and light/dark mode, repairing text
and accent contrast where needed. ANSI defaults resolve to explicit light/dark
colors for the inverted session. It does not change the terminal's own palette
or persist the modifier. The `kuberich-mono` theme provides black/white colors;
status words, selection markers and normal navigation remain available in narrow
or low-color terminals.

## Custom palettes

Add an `appearance` section to the preference file selected by `--config` or
shown by `kuberich info`. The root preference schema remains version 1; this
additive section also declares its own version. Existing files need no rewrite.

```yaml
schema_version: 1
theme: k9s
appearance:
  schema_version: 1
  check_updates: false
  themes:
    ocean:
      primary: '#5fd7ff'
      foreground: '#ffffff'
      background: '#000000'
      dark: true
  contexts:
    demo-lab: ocean
```

Custom names use 1–64 ASCII letters, digits, underscores or hyphens, beginning
with a letter. They cannot replace built-in names. A palette requires `primary`,
`foreground` and `background`; optional colors are `secondary`, `accent`,
`surface`, `panel`, `warning`, `error` and `success`. Colors are quoted six-digit
hexadecimal values. There is no executable CSS or Python in a palette.

Foreground contrast must be at least 4.5:1 against background, surface and panel;
primary/accent/status colors need 3:1 against the background. These numeric checks
and actual terminal tests complement readable state words; they do not certify
every terminal palette, font or color quantization. Limits are 32 custom themes,
128 context preferences and the existing 64 KiB total preference-file bound.
Framework CSS variables and icon preferences are not supported.

Set `background`, `surface` or `panel` to `'default'` to use the terminal's own
background, for example a transparent or blurred terminal window. Contrast checks
skip those colors because KubeRich cannot know the terminal's background. Pick a
`foreground` that is readable on it.

```yaml
appearance:
  themes:
    glass:
      primary: '#5fd7ff'
      foreground: '#ffffff'
      background: 'default'
      dark: true
```

Saved changes apply while KubeRich runs; see
[changing preferences](configuration.md#changing-preferences-while-kuberich-runs).

### Full resource titles

Set `appearance.full_gvr_titles: true` to show the API version in the title of
every resource view, for example `pods · v1`. Custom resources always show it.

An unavailable selection falls back to `k9s` with a warning. An invalid appearance
section uses working defaults, retains the original file and disables saves until
it is corrected. Run `kuberich config check` for an actionable validation error.
Loading, previewing and checking never repair or overwrite a file silently.

## About and optional version notices

`:about` or `kuberich --command about` shows original KubeRich branding, the
installed version, Apache-2.0 information and the version-check state. The content
scrolls and Back remains reachable in a 40×12 terminal.

Version checks are **off by default**. Enable the checkbox and choose Global,
or set `appearance.check_updates: true` explicitly. Context saves do not change
this application-wide option. Checks run asynchronously on terminal launch and
when requested preferences enable them; ordinary `info`, help, version and
`config check` remain offline operations.

The checker reads the public GitHub stable-release endpoint without credentials,
cookies or inherited proxy configuration. A request has a three-second deadline
and a 64 KiB response bound; redirects, unavailable/private releases, rate limits,
malformed data and prerelease announcements do not produce an update notice.
An installed prerelease/development build can still see a newer stable release.
The notice contains only a validated newer version and its canonical release URL.

Verified results may be reused for 24 hours from a private local cache. About
identifies cached results. An expired/corrupt cache, failed request or unwritable
cache cannot prevent startup. No package is downloaded, installed or executed;
follow the release notes and [installation guide](installation.md) when upgrading.

````

## docs/navigation-preferences.md

SHA-256: `673dce8087d56aaf54c8626b56f56b4090b4d466f9a72b0d228e0d264a0f759d`

````markdown
# Navigation, aliases and saved resource views

These preferences are implemented in the source checkout for the next release.
Published 0.1.0 packages do not include configurable navigation or persisted
column layouts. Existing configuration files continue to work.

## Navigation belongs to the focused view

Tables accept `j`/`k` for down/up, `g`/`G` for first/last, Ctrl+B/Ctrl+F for
pages, Ctrl+U for half a page up, `J` for half a page down, `h` for horizontal
left and Alt+L for horizontal right. Resource and namespace tables additionally
use `s`/`S` to cycle/reverse the sort. Sorting uses actual numbers, dates and
quantities, including when the sort field is hidden.

Arrows, Home/End, PageUp/PageDown and Ctrl+Home/Ctrl+End remain fixed fallbacks.
Home/End move horizontally; Ctrl+Home/Ctrl+End select the first/last row. The
additional navigation keys apply while the corresponding table or log body
has focus. Command, filter, search and editor inputs retain literal text and
their normal editing keys.

Logs use `l` for horizontal right and Ctrl+D for half a page down. In resource
tables, `l` opens logs and Ctrl+D opens the existing deletion review in write
mode; it does not execute a deletion. Read-only mode rejects that review.
In logs, `n`/`N` move between search matches; in the workspace `n` opens namespaces.
Ctrl+Y stays reserved for explicit copy in views that provide it. In container
tables, `s` continues to open a shell rather than sort. Remote shell input
continues to go to the embedded terminal.

Press `?` while a table has focus to see its effective navigation and fixed
actions. Resource help, log controls and applicable header shortcuts reflect
configured keys. Upper/lowercase keys remain distinct.

Next-release source also has an independent `text` profile for read-only
documents/help, explicit mouse opt-in, namespace favorites and bounded remote
copy. See the [complete interaction matrix](terminal-navigation.md).

## Configure keys and aliases

Use the preference file shown by `kuberich info`, or select one with `--config`.
The root schema remains version 1. The `navigation` section has its own version:

```yaml
schema_version: 1
navigation:
  schema_version: 1
  keys:
    resources:
      first: H
      last: K
      sort: u
      reverse_sort: U
    logs:
      first: H
      last: K
  aliases:
    work: pods
    lab: ctx demo-lab
    mywidgets: resource widgets.example.test/v1
```

The names and context in this example are fictional. Choose names from your own
intended context. `:work team` expands to `:pods team`. `:lab` already includes
an argument, so adding another argument is refused. Aliases also work with
`--command` when their target is a supported startup view. Cluster actions,
including aliases for them, require an interactive resource selection and the
same read-only policy as the original command. An alias never executes a shell
command, Python expression or variable substitution.

Supported key profiles are `table`, `resources`, `namespaces`, `contexts`,
`containers`, `data`, `themes`, `forwards`, `sources` and `logs`. `table` supplies
common table defaults; a more specific profile wins. Logs are independent.
Actions are `down`, `up`, `first`, `last`, `page_up`, `page_down`, `half_up`,
`half_down`, `left` and `right`. `sort` and `reverse_sort` apply to resources and
namespaces; their common defaults may be specified in `table`.

Keys use one ASCII letter/digit, `ctrl+` plus a lowercase letter, or `alt+` plus
a letter/digit. Chords such as `gg` and comma-separated keys are unsupported.
Native fallback, quit, input, help and actual per-view action keys are reserved.
Ctrl+M/J/I/H are refused because common terminals encode them as Enter, Tab or
Backspace. Duplicate effective keys or conflicts reject the navigation override
and retain working defaults. Run `kuberich config check` for the specific error.

Up to 64 aliases are accepted. Names use lowercase ASCII letters/digits,
underscores or hyphens, start with a letter and contain at most 32 characters.
Targets and supplied arguments are bounded to 256 characters. Built-in names,
cycles, ambiguous preset arguments and chains exceeding eight expansions are
refused. A name that collides with a discovered resource is not offered by
completion and produces a clear error; `:resource NAME.GROUP/VERSION` remains
available to select that resource explicitly. Completion uses the effective
aliases without making a request for each keystroke.

## Configure a resource view

Open `:views` in a Pod, namespace, standard-resource or discovered-resource table.
It lists the available field keys and the current selection. For columns, enter
space-separated `key[:width][:alignment]` entries, in display order. Omit a field
to hide it. Width is `auto` or an integer from 1 to 256; alignment is `auto`,
`left`, `center` or `right`. For example:

```text
name:24:left ready:8:center age:8
```

Choose a typed sort field separately and optionally select Descending. The sort
field can be hidden. The `name` column stays visible for stable identity;
all-namespace lists also retain `namespace` so equal names can be distinguished.
Widths and alignment affect display only. They do not convert typed sort values
into strings. Header clicks and effective sort keys change this session's sort.
Filters retain the typed row model, so hiding a field does not make its values
confidential or necessarily remove it from search. Pod/standard summaries remain
searchable, and a generic view's hidden sort field also participates. Generic
fields excluded from both display and sort are not projected into its filter.

- **Apply** updates this session only.
- **Global** explicitly saves the resource view for all contexts.
- **Context** explicitly saves it for the context named in the editor.
- **Back / Escape** closes without applying unsaved input.

A matching context preference takes precedence over a global preference, even
after a new global save. A save requested for a captured resource/context cannot
silently apply to another view. If its scope or server columns change before the
request, reopen the editor. A requested file save finishes before closing, also
during graceful exit. A save is refused if the file changed on disk since it
was loaded. KubeRich loads a valid change within two seconds; save again after
that. Saving preserves original settings, themes and unknown fields and never
persists runtime `--readonly`, connection or environment overrides.

Saved files and new preference directories use the existing private permissions.
Read-only cluster mode still permits local preference saves. Previewing, loading,
validating, scrolling and sorting do not silently write files. Invalid navigation
sections leave the original bytes intact and disable saves until corrected.
An inapplicable resource layout falls back to a valid global layout or defaults
with a visible explanation. `config check` validates known built-in fields
offline; discovered fields require the actual API's schema.

## Saved format and migration

Resources use `VERSION/RESOURCE` for the core API or `GROUP/VERSION/RESOURCE` for
a named API group. Views are pinned to the actual served version. A native view
and an explicit server-printer view of the same resource have separate keys:
server-printer keys begin with `server:`.

```yaml
schema_version: 1
navigation:
  schema_version: 1
  views:
    apps/v1/deployments:
      columns:
        - key: name
          width: 24
          alignment: left
        - key: ready
          width: 8
          alignment: right
      sort:
        key: desired
        descending: true
  contexts:
    demo-lab:
      views:
        v1/pods:
          columns:
            - key: name
            - key: age
          sort:
            key: restarts
            descending: true
```

The editor records a `printer_signature` for discovered resources. It fingerprints
ordered server column names, types, formats and priorities, without retaining
resource values. Positional `cN` references require this evidence. A changed
printer schema cannot reinterpret old positions under new labels. Old saved
preferences remain on disk while the view uses working defaults. Generic views
remain read-only; configuring columns does not enable cluster mutations.
`:columns` remains the session-only server-column shortcut.

A missing/zero navigation version is read as the earlier format: flat keys,
string columns, a widths mapping, string sort and a separate descending boolean.
It migrates in memory, including printer keys to their `server:` namespace.
The next explicit save writes navigation version 1. Loading and `config check`
do not rewrite it. Unknown future versions, duplicate migrated views and invalid
fields produce an error rather than discarding preferences. Legacy application
paths require `kuberich config migrate` before a save.

The existing 64 KiB file bound applies. There are at most 128 global resource
views, 128 context entries and 128 views per context; session view memory uses a
bounded cache. Views contain display preferences, not kubeconfig contents,
credentials or resource data. Saved column views, aliases and favorites apply
while KubeRich runs; key binding and mouse changes need a restart. See
[changing preferences](configuration.md#changing-preferences-while-kuberich-runs)
and [resource jumps](resource-jumps.md). Extended filters and Vim multi-key/count
commands remain separate work.

See [commands](command-navigation.md), [themes](themes.md),
[standard resources](standard-resources.md) and
[discovered resources](standard-resources.md#generic-discovered-resources).

````

## docs/plugins.md

SHA-256: `9ed948147921716ea927fb57587dab8f942e69232c6e5e9b780ca8589e0c2dd1`

````markdown
# Local command plugins

Plugin configuration is available in the next-release source. The published
0.1.0 package does not load or execute plugins. The next-release source loads definitions, presents typed input/review forms
and runs explicitly selected commands through the owned process services.

Plugins are trusted local programs running with your user privileges. They can
read files, use inherited credentials, contact services and change a cluster.
KubeRich does not sandbox them or infer safety from an executable's name.
Only install definitions you have reviewed.

For the precise K9s field/variable comparison, three original tested definitions
and the complete pinned community-workflow census, see
[compatibility and examples](plugin-compatibility.md). There is no automatic
K9s importer; external tool features are not native KubeRich capabilities.

## Explicit configuration

Add the independently versioned `plugins` extension to your preferences:

```yaml
schema_version: 1
plugins:
  schema_version: 1
  commands:
    inspect-pod:
      description: Inspect the selected pod using a local tool
      command: kubectl
      args:
        - --kubeconfig=${KUBECONFIG}
        - --context=${CONTEXT}
        - --namespace=${NAMESPACE}
        - get
        - pod
        - ${NAME}
        - -o=json
      scopes: [v1/pods]
      shortcut: a
      mode: capture
      confirm: true
      dangerous: false
      trusted_read_only: true
      timeout: 30
      output_limit: 65536
```

Run `kuberich --config /absolute/path/config.yaml config check` to validate every
configured context without running any plugin, loading Kubernetes credentials,
or changing the file. `kuberich info` remains usable when a plugin path is broken.

The optional `locations` list names up to eight user-selected files/directories.
Relative paths resolve from the containing preference file, never the terminal's
current directory. A directory loads only its immediate `.yaml` and `.yml` files
in sorted order. There is no default directory search, recursion, installation
from resource annotations, or current-directory registration. Final-component
symbolic links, special files, missing configured paths and invalid YAML fail
closed. Parent-directory symlinks are subject to your operating system's ordinary
path resolution; keep configured directories under your control.

Each external file uses this wrapper:

```yaml
schema_version: 1
plugins:
  schema_version: 1
  commands:
    local-inspector:
      command: my-inspector
      args: ["${CONTEXT}"]
```

External files cannot introduce more locations or context layers. A layer loads
at most 16 files and 64 commands; each file is at most 64 KiB. Directories contain
at most 128 entries. YAML aliases and duplicate mapping keys are rejected. A
duplicate plugin name within a layer is an error. A context layer deliberately
replaces a same-named global definition in full:

```yaml
plugins:
  schema_version: 1
  locations: [plugins]
  contexts:
    demo-local:
      locations: [plugins-for-demo]
      commands:
        local-inspector:
          command: demo-inspector
          args: ["${CONTEXT}"]
```

Up to 128 context layers are supported. Context names are exact local names.
Changing the active context cannot change a previously captured invocation.
When `config migrate` moves legacy preferences, it validates the plugin schema
and makes file locations and inline working directories absolute against the
original file. Migration retains the same configured programs and directories,
keeps the source unchanged and refuses an invalid definition before writing.

## Definition fields

| Field | Contract |
| --- | --- |
| `command` | Required literal executable name/path; no variable or shell parsing |
| `description` | Literal help text; defaults to the plugin name |
| `args` | At most 255 separate nonempty arguments; each at most 8,192 characters |
| `environment` | At most 64 explicit string overrides on the captured inherited environment |
| `directory` | Absolute path or path relative to the definition file; defaults to its directory |
| `scopes` | `['*']` by default, or exact `v1/pods` / `apps/v1/deployments` identifiers |
| `shortcut` | Optional single ASCII letter/digit or `ctrl+`/`alt+` letter |
| `override` | False by default; must be true to replace an existing resource action/navigation key |
| `mode` | `capture` by default, `foreground` for terminal interaction, or `background` |
| `confirm` | True by default; explicit local trust decision before execution |
| `dangerous` | True by default; dangerous definitions always require review and are blocked read-only |
| `trusted_read_only` | False by default; only explicit true plus `dangerous: false` permits read-only use |
| `inputs` | At most 16 named, validated scalar input definitions |
| `timeout` | Positive finite seconds, at most 86,400; defaults to 300 |
| `output_limit` | Combined captured stdout/stderr bytes, 1,024–1,048,576; defaults to 65,536 |

Plugin names start with a lowercase ASCII letter followed by up to 63 lowercase
letters, digits, underscores or hyphens. Unknown fields fail validation rather
than being ignored. Applicable plugins must have different shortcuts even if
`override` is true. Quit, interruption, suspension and clipboard safety keys
cannot be replaced. Non-resource screens and text inputs retain their own keys.

The executable and working directory are captured separately from arguments.
Spaces, semicolons and dollar signs in selected names remain literal argument
content. An explicitly configured shell such as `sh -c` remains local shell code:
pass values as positional arguments rather than embedding them into its script.

## Captured variables

Use `$NAME` or `${NAME}` inside each argument/environment value. Expansion runs
once. Inserted text is never parsed again, and `$$` produces a literal dollar.
Missing, malformed, control-containing or oversized values fail before execution.
An optional empty input cannot occupy an entire argv entry, because process
arguments must remain nonempty; use a prefixed value or an environment variable.

| Variable | Source |
| --- | --- |
| `CONTEXT` | Captured session's exact context name |
| `CLUSTER`, `USER`, `FILTER` | Explicitly captured view values, when available |
| `KUBECONFIG` | Private prepared connection path supplied by the invocation owner |
| `RESOURCE`, `GROUP`, `VERSION`, `NAMESPACE` | Captured view scope; a selected row supplies its exact namespace |
| `NAME`, `CONTAINER` | Captured selected resource/container; container is empty outside a captured container |
| `COL-HEADER` | Explicitly captured uppercase column identifier, such as `${COL-NAME}` |
| `INPUT_NAME` | Validated named input; uppercase with hyphens changed to underscores |

`KUBECONFIG` and `KUBERICH_` environment overrides are reserved for the captured
session. A context/UID change invalidates resource-bound work. Scope and local
guards cannot make an external tool's server-side operations atomic.

## Typed inputs and cancellation

```yaml
inputs:
  - name: count
    label: Number of lines
    type: number
    default: 100
  - name: previous
    type: bool
    default: false
  - name: format
    type: dropdown
    options: [json, yaml]
    default: json
  - name: note
    type: string
    required: false
```

Inputs are required by default. Types are `string`, finite `number`, `bool`
(`true`/`false`) and `dropdown` with unique configured choices. Defaults undergo
the same validation as submitted values. Unknown inputs and colliding normalized
names are rejected. Cancellation produces no executable request. Inputs and
expanded command values must not enter diagnostics or exception representations.

## Execution modes and output

Use `:plugins` to list applicable commands, or `:plugin NAME` to open a specific
command. Tab completes configured names after `plugin `. Configured shortcuts
work while a root resource table owns focus; text inputs and embedded pod shells
retain their keys. A plugin override replaces that resource shortcut, and root
help lists the effective plugin keys. The form defaults to Cancel. Review
validates typed values; Run is a separate explicit action. Changing a value
invalidates the previous review, and a review can run only once.

A connected context is required. An empty resource view can run commands that
need only context/scope values; `NAME`, container and column values require an
actual selected row. A selected row is captured before asynchronous loading and
checked again by GET and UID before starting. Guards cannot make a later external
program's server operations atomic.

The local contexts list has no Kubernetes resource scope or plugin hotkeys.
Explicit `:plugins` / `:plugin NAME` there can review global commands against the
currently connected context; highlighting another context does not connect it or
supply a resource `NAME`. Resource-specific commands wait until their matching
API view is ready. Shortcut validation uses the namespace table's own navigation
profile for namespace-scoped/global commands, including custom namespace keys.

- `capture`: waits for the one-shot command and shows status, exit code and bounded
  output. Cancel stops and drains the process group before returning.
- `background`: stays owned after Back closes the form. Use `:pluginjobs`, Enter
  for its completed output, or Stop selected. Output is collected until completion
  rather than streamed; stopping/cancelling can discard in-flight captured output.
  There are at most four active jobs and 32 retained jobs.
- `foreground`: deliberately suspends Textual and gives the native terminal to
  the local executable. Exit/interruption restores the interface. This does not
  change the embedded pod/container shell. It requires a real terminal and its
  direct output is outside captured-output redaction and byte limits.

Captured stdout and stderr share the configured cumulative byte limit; overflow
terminates the owned group and reports Output Limit. Timeout, nonzero exit,
signal, cancellation and start refusal have distinct visible states. Background
waiter cancellation does not detach a job. Scope/UID invalidation, context/retry
replacement and application exit cancel and drain owned work. Private credential
files stay available until processes stop and are then removed.

Each command gets a private, single-context mode-0600 kubeconfig under the owned
mode-0700 session directory. KubeRich sets `KUBECONFIG`, `KUBERICH_CONTEXT` and the
captured `KUBERICH_NAMESPACE`; it does not reload the ambient current context.
Explicit plugin cwd/environment do not alter the original authentication helper's
cwd, frozen environment or relative files. A private credential launcher retains
those separately and forwards client-go's fresh `KUBERNETES_EXEC_INFO`. Native
archives dispatch this launcher internally without an external Python install.

Read-only mode refuses an unclassified or dangerous command before helper lookup
or input preparation. Running one requires both `trusted_read_only: true` and
`dangerous: false`; that is your explicit trust decision, not inferred safety.
Both GUI entry routes still use Review and Run. At the service boundary,
`confirm: true` or `dangerous: true` always requires explicit confirmation.
`--command 'plugin NAME'` is refused before connection/authentication; execution
requires interactive review.

Captured output uses credential-pattern redaction, known captured token/input
value masking and terminal-control escaping. Display is bounded to 16,384
characters with an explicit truncation marker; retained sanitized text is at most
65,536 characters. Raw output is never logged or included in job representations.
No remote OSC sequence can become a clipboard operation. Arbitrary plugin output
can contain information KubeRich cannot recognize as sensitive; review the local
program and avoid asking it to print secrets.

K9s configuration is not currently accepted as a drop-in format. A tested field,
variable and bundled-workflow compatibility guide follows the execution work.

````

## docs/plugin-compatibility.md

SHA-256: `b317e7369d8404590fbee2df1670aa54722949be3d25f009ee4a0f0929ba88fa`

````markdown
# Plugin compatibility and original examples

This guide describes the next-release source. Published **0.1.0 does not load or
execute plugins**. KubeRich has an independent, versioned schema: a K9s file is
not a drop-in configuration file, and there is no automatic importer.

The comparison fixes K9s **v0.51.0**, commit
`558caafe7ba067467de46b320cc22ef11fef9c34`. Its pinned inventory contains **50
files: 48 YAML manifests with 108 commands and two executable shell helpers**.
This is a complete classification of that inventory, not a claim that all its
programs work in KubeRich or that an unverifiable paid catalogue is covered.

Read [configuration, trust and process ownership](plugins.md) first. Plugins run
as your user without a sandbox. The examples below are original definitions;
upstream shell programs are neither installed nor executed by our tests.

## Fields: keep, translate or reject

The authoritative upstream field definitions and defaults are in the
[pinned plugin model](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/internal/config/plugin.go).
Unknown KubeRich fields fail validation; there is no silent compatibility mode.

| K9s field or structure | KubeRich contract |
| --- | --- |
| `plugins: NAME: ...` | Translate to root `schema_version: 1`, then `plugins: {schema_version: 1, commands: ...}`. Only explicitly configured locations load. |
| `command` | Same literal executable concept. No variable expansion in the executable, implicit shell, installation or executable discovery during `config check`. |
| `description` | Supported as literal text. Terminal controls and markup are not interpreted. |
| `args` | Supported as separate **strings**, with bounded one-pass interpolation. Quote numeric YAML entries such as `"50"`. Shell statements remain shell code if you explicitly choose a shell. |
| `scopes` | Translate aliases such as `po`/`pods` to an exact served identifier such as `v1/pods`; `all` becomes `'*'`. Group/version is explicit, including CRD plurals with hyphens. Virtual `containers`, `helm` and `history` views are not root API scopes. |
| `shortCut` | Rename to `shortcut`. Translate `Shift-H` to `H` or `Ctrl-A` to `ctrl+a` only where the terminal and safety/key profile permit it. Function keys, chords and reserved safety keys are not plugin shortcuts. |
| `override` | Supported only as explicit key replacement. Scope conflicts, duplicate effective shortcuts and reserved safety keys still fail. |
| `confirm` | Recognized, with different defaults/interaction: KubeRich defaults true; its form always requires an explicit Run after review. K9s defaults to confirmation when inputs exist, otherwise false. |
| `dangerous` | Recognized, but KubeRich defaults true. Dangerous commands always require confirmation and cannot run read-only. No executable is inferred safe by name. |
| `background` | Replace with `mode: background` for an owned job. For interactive terminal use choose `mode: foreground`; the default `capture` is a separate bounded one-shot mode. This is a deliberate choice, not a boolean rename preserving all behavior. |
| `overwriteOutput` | Unsupported; reject it. KubeRich retains bounded per-job output and status rather than replacing a shared upstream output area. |
| `pipes` | Unsupported; reject it. Write and review a separate local program/script, with literal positional arguments, if a pipeline is needed. |
| `inputs` | The four type names (`string`, `number`, `bool`, `dropdown`) are recognized. Names must use the KubeRich lowercase identifier grammar; defaults/options are validated. Set `required` explicitly: KubeRich defaults true; the upstream model's omitted bool defaults false. Typed boolean defaults or `"true"`/`"false"` are accepted. |
| `directory`, `environment`, `timeout`, `output_limit`, `trusted_read_only` | KubeRich-specific explicit controls. Paths resolve from the definition file; read-only use needs `dangerous: false` **and** `trusted_read_only: true`. Do not infer that classification from an upstream flag. |

Definitions remain local trusted code even when `trusted_read_only` is true.
That setting permits invocation in the UI; it cannot stop a program writing files,
ignoring a kubeconfig or contacting another service.

## Variables and shell syntax

The comparison uses the pinned
[common environment](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/internal/view/helpers.go),
[resource table environment](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/internal/view/table.go),
[container environment](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/internal/view/container.go)
and [substitution implementation](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/internal/view/env.go).

| Upstream value | KubeRich mapping and limits |
| --- | --- |
| `$CONTEXT`, `$CLUSTER`, `$USER` | Same uppercase names when captured. These are connection aliases, not a promise about an external service's authenticated identity. |
| `$KUBECONFIG` | Same spelling, different ownership: the invocation receives a private, single-context prepared file, not the caller's ambient source path. It exists only while owned work needs it. |
| `$NAMESPACE`, `$NAME` | Selected **root API resource** namespace/name. Cluster-scoped resources have an empty namespace. Empty argv entries are rejected; choose a separate cluster-scoped recipe instead of an empty namespace flag. |
| `$RESOURCE_GROUP`, `$RESOURCE_VERSION`, `$RESOURCE_NAME` | Translate to `${GROUP}`, `${VERSION}`, `${RESOURCE}`. These are the actual captured GVR components, not aliases or an assumed preferred version. |
| `$FILTER` | Same spelling, different fallback: KubeRich captures the root filter text and leaves it empty when no filter exists. K9s falls back to a selected path/name. Use a required input when an external tool needs a selector. |
| `$COL-NAME`, other `$COL-...` | Only available captured **visible** columns, normalized to uppercase portable identifiers. Upstream hidden headers and punctuation do not imply the same column exists. Missing columns fail closed. |
| `$INPUT_NAME` | Validated input values, uppercase with hyphens changed to underscores. An inserted value is never parsed as another template. |
| `$POD`, container `$NAME` | No drop-in mapping. In K9s container views, NAME is the container and POD is its parent. Root plugin invocation in KubeRich uses the Pod as NAME; use an explicit container input, as below. There are no plugin hotkeys in the container picker. |
| `$GROUPS` | Unsupported; it is not a captured KubeRich plugin variable. Supply a reviewed explicit input/environment value if the external program needs groups. |
| `$!FLAG`, `${!FLAG}` | Upstream **boolean inversion**, not escaping. Unsupported; use a typed boolean for the desired state. That is set-state behavior, not a race-free toggle. |
| Lowercase variables, unknown names, `${NAME:-fallback}`, `${GROUP:+...}`, arithmetic and command substitution | Unsupported in KubeRich templates; fail before execution. Separate shell code into a reviewed file and pass captured values as positional arguments. |
| Literal dollar | Use `$$`. For example, `$$HOME` passes literal `$HOME`; it does not read the ambient environment. Escaped `$$!NAME` is literal text, not inversion. |

Substitution is not shell quoting and does not validate a destination language
such as JSON, LogQL or a CLI's regex dialect. A safe argument vector can still
contain an unsafe query. Prefer structured tools or validated dropdown values
when inserting data into those formats. The PVC translation fixture uses an
explicit quantity allowlist rather than unrestricted JSON interpolation.

## Three original workflows

Each example is a complete external-file wrapper and declares `kubectl` as its
only **local** executable. Install a compatible kubectl separately. Review and
copy the files into a directory you control, then add that directory explicitly
to the existing preference file. Relative locations resolve from that file:

```yaml
schema_version: 1
plugins:
  schema_version: 1
  locations: [plugins]
```

This example expects a sibling `plugins` directory; it does not search your
checkout or current directory. Keep existing preferences and extensions when
merging this configuration. Validate without authenticating or starting a tool:

```sh
kuberich --config /absolute/path/config.yaml config check
```

Connect to the intended context/namespace, select a Pod, and invoke a name with
`:plugin NAME`. The form defaults to Cancel; Review validates values, then Run
starts the command. Cancel starts no program and discards any prepared review. See the complete
[example files](https://github.com/carloshm91/kuberich/tree/main/examples/plugins).

| Example | Invocation and behavior | Prerequisites and limits |
| --- | --- | --- |
| [Inspect Pod](https://github.com/carloshm91/kuberich/blob/main/examples/plugins/inspect-pod.yaml) | `:plugin inspect-pod` captures `kubectl get pod NAME --output=json` with explicit kubeconfig/context/namespace. | Pod GET permission; 30-second timeout, 64-KiB combined output. Explicit non-dangerous/read-only classification. Arbitrary values may exceed recognizable credential redaction; review output handling. |
| [Interactive Pod shell](https://github.com/carloshm91/kuberich/blob/main/examples/plugins/pod-shell.yaml) | `:plugin pod-shell` asks for the exact container and runs literal `kubectl exec --stdin --tty --container=... NAME -- sh`. | Write mode, pods/exec permission, a container containing `sh`, and a real terminal. This **local foreground plugin** uses native handoff and restores the UI; ordinary built-in Pod shells remain embedded. Direct foreground output cannot receive capture redaction/byte limits. Timeout is one hour. |
| [Collect Pod events](https://github.com/carloshm91/kuberich/blob/main/examples/plugins/collect-pod-events.yaml) | `:plugin collect-pod-events` starts an owned background `kubectl get events --output=json`, filtered to kind Pod and the selected name in its namespace. | Event list permission. Name/kind filtering does not identify a UID atomically; the plugin's captured Pod UID guard invalidates replaced targets. Output appears at completion, not as a live log stream; Stop may discard in-flight capture. Timeout is five minutes; 64-KiB output stops the group on overflow. |

Use `:pluginjobs` to inspect or Stop background work. Closing its form keeps an
owned background job alive; scope/UID invalidation, context replacement or exit
stops and drains it. Private connection files are removed after processes stop.
Missing programs, bad permissions/cwd, denied/stale targets, timeouts, nonzero
exits, signals and output overflow produce visible failure states. No failure
triggers an automatic retry of an external side effect. `config check` validates
the manifest but deliberately does not prove that a program is installed, that
its flags are compatible or that Kubernetes permissions allow execution.

## What the translation tests establish

There are **18 original argv adaptation fixtures**, including Argo workflow
commands, selected Application patches, one duplication scope, desired-state
CronJob/Spark suspension, KubeVirt migration arguments, Pod log follow, six Loki
root-row queries, Stern with an explicit selector, bounded PVC quantities and a
restricted Deployment finalizer patch. Their
[fixtures](https://github.com/carloshm91/kuberich/blob/main/tests/fixtures/plugins/translations.json)
record the changed semantics beside each definition and exact expected argv.

These fixtures prove schema/input/scope/literal expansion and conservative trust
classification against synthetic resources. They do **not** run Argo, Loki,
Stern, KubeVirt, Spark, storage controllers or their services. Served CRDs and
external CLI versions must match your installation. Shell/PowerShell recipes,
virtual views and legacy helpers are explicitly classified below, not presented
as tested translations. No automated converter attempts to repair their code.

The three original examples additionally execute harmless owned kubectl stand-ins
with private synthetic connection files. Tests cover capture, background Stop,
read-only refusal, cancellation and actual interactive terminal input/restoration.
Downloaded upstream code and the maintainer's clusters are never test inputs.

## Complete pinned workflow census

Each source link fixes the reviewed commit. The machine-readable
[census](https://github.com/carloshm91/kuberich/blob/main/docs/plugin-compatibility.json)
records all 108 command names, field/variable spellings, classifications,
translation references, original Git blob IDs, byte lengths and SHA-256 digests.
Those digests identify the reviewed source bytes; they are not a claim about a
later upstream revision. The two extensionless files are executable helpers,
not malformed YAML manifests.

**argv** means only the named synthetic argument contract is tested;
**rewrite** needs a separately reviewed program/definition; **view** depends on
an unavailable virtual view; **legacy** is deliberately not translated.
Dependencies below include the primary programs and important platform/service
requirements. Shell recipes also use ordinary shell utilities. Alternatives are
no-fee local/native inspection paths or separately installed CLIs, with the
stated functional limits. External software retains its own license; hosting,
cloud/model services, credentials and privileged operations may have costs or
requirements. None is automatically installed or required for KubeRich itself.

| Pinned source and commands | Classification | External dependencies | Free alternative and review limits |
| --- | --- | --- | --- |
| [ai-incident-investigation.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/ai-incident-investigation.yaml) · `holmesgpt`, `custom-holmesgpt` | 2 rewrite | bash, holmes CLI, configured model/provider, editor for custom questions | Read details/events/logs and investigate manually with kubectl. External model requests may disclose cluster data and may incur provider charges; review scripts and provider terms. |
| [argo-rollouts-powershell.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/argo-rollouts-powershell.yaml) · `argo-rollouts-get`, `argo-rollouts-watch`, `argo-rollouts-promote`, `argo-rollouts-restart` | 4 rewrite | PowerShell, kubectl, Argo Rollouts kubectl extension/controller | Inspect rollout CRDs with the generic browser or kubectl. PowerShell statements and ReadKey are not literal argv; use reviewed platform-specific scripts. |
| [argo-rollouts.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/argo-rollouts.yaml) · `argo-rollouts-get`, `argo-rollouts-watch`, `argo-rollouts-promote`, `argo-rollouts-restart` | 4 rewrite | bash, kubectl, Argo Rollouts extension/controller, less | Inspect rollout CRDs; use the separately installed Rollouts CLI for its actions. Pipelines and shell interpolation need a rewrite; select the actual served Rollout GVR. |
| [argo-workflows.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/argo-workflows.yaml) · `view-workflow`, `watch-workflow`, `terminate-workflow`, `submit-from` | 2 rewrite, 2 argv | sh, argo CLI/controller, watch for watch-workflow | Browse workflow CRDs and inspect their YAML/events. CLI authentication/options and installed CRD versions must be verified; shell watch recipes need separate scripts. |
| [argocd.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/argocd.yaml) · `argocd`, `refresh-apps`, `disable-auto-sync`, `enable-auto-sync` | 2 rewrite, 2 argv | argocd CLI/server/login, kubectl, bash | Browse Application CRDs and review YAML changes with kubectl. An Argo CD server login is a separate identity; KUBECONFIG does not constrain a server-side argocd app sync. |
| [blame.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/blame.yaml) · `blame` | 1 rewrite | sh, kubectl-blame, less | Inspect managedFields in YAML; that is not a full blame history. External ownership rendering and paging require the external tool. |
| [carvel.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/carvel.yaml) · `kapp-inspect`, `kctrl-app-status`, `kctrl-app-pause`, `kctrl-app-kick` | 4 rewrite | bash, kapp, kctrl, Carvel controllers, less | Inspect Carvel CRDs/YAML and use the separately installed Carvel tools. Shell export/pipes need reviewed scripts; pause/kick change controller state. |
| [cert-manager.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/cert-manager.yaml) · `cert-status`, `cert-renew`, `secret-inspect` | 3 rewrite | bash, cmctl, cert-manager, less | Inspect Certificate CRDs/events; use cmctl explicitly for renew/inspection. Secret inspection discloses certificate content; renew changes state. |
| [crd-wizard.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/crd-wizard.yaml) · `crd-wizard` | 1 rewrite | bash, crd-wizard TUI | Browse discovered CRDs and inspect/edit their YAML. Requires an available KIND column and an external TUI; literal argv must replace the shell command. |
| [crossplane.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/crossplane.yaml) · `crossplane-trace`, `crossplane-watch` | 2 rewrite | sh, crossplane CLI/controllers, less, viddy for watch | Browse Crossplane CRDs and inspect their status/YAML. Conditional namespace handling, external watch and group-qualified kinds require reviewed scripts. |
| [current-ctx-terminal.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/current-ctx-terminal.yaml) · `open-terminal` | 1 rewrite | /usr/bin/sh, bash, kubectl | Use explicit kubectl --kubeconfig/--context flags for each command. Upstream use-context writes configuration; never run it against the caller configuration. A private config is not a shell sandbox. |
| [debug-container.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/debug-container.yaml) · `debug` | 1 view | bash, kubectl debug, permitted debug image/profile | Use reviewed kubectl debug; built-in shells connect to existing containers only. Virtual containers scope and POD/NAME meanings differ; privileged debug creation is not a native capability. |
| [dive.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/dive.yaml) · `dive` | 1 view | dive, supported local/container image backend | Inspect declared image references; use dive separately for image layers. Virtual container selection and IMAGE column are unavailable to root plugin hotkeys; image-layer analysis remains external. |
| [dup.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/dup.yaml) · `dup`, `dup_edit`, `dup_debug_pods`, `dup_debug_deploy`, `dup_debug_sts`, `dup_debug_cronjob`, `dup_debug_jobs` | 7 rewrite | bash, kubectl, kubectl-dup extension | Review an exported manifest and apply a deliberately edited copy with kubectl. Duplication/debug actions create resources; never infer read-only from the missing dangerous flag. |
| [duplik8s.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/duplik8s.yaml) · `duplicate` | 1 argv | kubectl, duplik8s kubectl-duplicate extension | Review/export a manifest and create an explicitly named copy with kubectl. Short resource aliases must become exact GVR scopes; the external extension still needs installation. |
| [eks-node-viewer.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/eks-node-viewer.yaml) · `eks-node-viewer` | 1 rewrite | bash, kubectl, jq, eks-node-viewer, AWS configuration/credentials | Inspect nodes and declared resources with kubectl; AWS billing views remain external. Do not scrape private ExecCredential launchers for AWS_PROFILE/region; configure the external AWS tool explicitly. AWS services may charge. |
| [external-secrets.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/external-secrets.yaml) · `refresh-external-secrets`, `refresh-push-secrets` | 2 rewrite | bash, kubectl, date, External Secrets controllers | Inspect ExternalSecret/PushSecret CRDs and explicitly annotate with kubectl. Timestamp command substitution and controller-specific API versions need review; reconciliation changes state. |
| [flux.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/flux.yaml) · `toggle-helmrelease`, `toggle-kustomization`, `reconcile-git`, `reconcile-hr`, `reconcile-helm-repo`, `reconcile-oci-repo`, `reconcile-ks`, `reconcile-ir`, `reconcile-iua`, `toggle-rset`, `toggle-inputprovider`, `reconcile-rset`, `reconcile-inputprovider`, `reconcile-fluxinstance`, `trace`, `get-suspended-helmreleases`, `get-suspended-kustomizations` | 17 rewrite | bash/sh, kubectl, flux, flux-operator, controllers, less, jq/tail/awk | Browse Flux CRDs/YAML and run the installed Flux CLI explicitly. Toggle/trace scripts perform lookups, conditionals and writes; select the actual served API groups/versions. |
| [get-all-namespace-resources.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/get-all-namespace-resources.yaml) · `get-all-resources-by-selected-namespace`, `get-all-resources-in-current-namespace` | 2 rewrite | sh, kubectl, less | Browse a selected resource family or enumerate/list with kubectl api-resources. Loops, suppressed failures and many API calls are not a single native all-resource view; retain explicit scope and errors. |
| [get-all.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/get-all.yaml) · `get-all-namespace`, `get-all-other` | 2 rewrite | sh, kubectl-get-all extension, less | Use kubectl api-resources and explicit resource-family listings. External enumeration and paging require the extension; namespace NAME differs from a resource namespace. |
| [helm-default-values.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/helm-default-values.yaml) · `helm-default-values` | 1 view | sh, helm, kubectl, grep/cut/tr, yq, base64, gunzip, jq, less | Use helm show values or helm get values with explicit release/context. Virtual Helm rows and release-secret decoding are unsupported; yq dialect and secret handling require review. |
| [helm-diff.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/helm-diff.yaml) · `helm-diff-previous`, `helm-diff-current` | 2 view | bash, helm, helm-diff extension, grep/cut/tr, less | Use helm history/get values; diff retained manifests with ordinary diff. Virtual Helm/history rows, revision arithmetic and release-name parsing are not available. |
| [helm-purge.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/helm-purge.yaml) · `helm-purge` | 1 legacy | kubectl-purge helper, Helm 2, Tiller, BSD xargs -J | Plan a reviewed migration to Helm 3 and use its supported uninstall command. Legacy Helm 2/Tiller purge is not translated or certified; do not execute the unquoted helper. |
| [helm-values.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/helm-values.yaml) · `helm-values` | 1 view | sh, helm, less | Use helm get values with explicit release, namespace and kube context. Virtual Helm rows are unsupported; provide an explicit release input to a separately reviewed definition. |
| [job-suspend.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/job-suspend.yaml) · `toggleCronjob` | 1 argv | kubectl, batch/v1 CronJob API | Use the built-in reviewed CronJob suspend/resume operation. Replace boolean inversion with an explicit desired boolean; this is set-state, not a toggle. |
| [k3d-root-shell.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/k3d-root-shell.yaml) · `k3d-root-shell` | 1 view | bash, kubectl, jq, Docker, k3d node containers, less | Use an existing pod shell; review node/container-runtime administration separately. Virtual container scope, runtime IDs and Docker root access are external and highly privileged. |
| [keda-toggle.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/keda-toggle.yaml) · `toggle-keda` | 1 rewrite | bash, kubectl, grep, KEDA controller | Inspect KEDA CRDs; review an explicit annotation change with kubectl. overwriteOutput is unsupported; conditional pause mutation needs a separately reviewed script. |
| [kube-metrics.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/kube-metrics.yaml) · `kube-metrics-pod` | 1 rewrite | sh, kube-metrics external tool and its metrics backend | Use kubectl top where Metrics Server/RBAC permit; unavailable metrics are not zero. External metrics aggregation is not native; explicitly pin the tool connection instead of relying on ambient defaults. |
| [kubectl/kubectl-purge](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/kubectl/kubectl-purge) · executable helper | legacy | bash, kubectl, Helm 2/Tiller, grep/cut, BSD xargs -J | Review migration to Helm 3 before using helm uninstall. Executable helper, not YAML. Legacy purge, unquoted substitutions and BSD-only xargs are not supported recipes. |
| [kubectl-get-in-shell.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/kubectl-get-in-shell.yaml) · `kubectl-get-cmd` | 1 rewrite | bash, kubectl, less | Use resource details/YAML or compose an explicit kubectl get argument vector. Printing shell text is not execution safety; shell conditionals/formatting require a reviewed script. |
| [kubectl-plugins/kubectl-jq](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/kubectl-plugins/kubectl-jq) · executable helper | rewrite | bash, kubectl, jq | Use kubectl logs with jq explicitly, or bounded native log viewing. Executable helper, not YAML; replace unquoted arguments and review raw terminal/color output. |
| [liveMigration.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/liveMigration.yaml) · `liveMigration` | 1 argv | virtctl, compatible KubeVirt controller/CRDs and migration permissions | Inspect KubeVirt CRDs; run installed virtctl deliberately for migration. Migration is an external effectful operation; the fixture tests arguments, not a real migration. |
| [log-bunyan.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/log-bunyan.yaml) · `bunyanlogsp`, `bunyanlogsd`, `bunyanlogss` | 3 rewrite | bash, kubectl, Node.js/bunyan | Use bounded native logs or kubectl logs and a separately installed JSON formatter. Pipelines and an interactive shell are not automatically translated; service/deployment log selection is external. |
| [log-full.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/log-full.yaml) · `raw-logs-follow`, `log-less`, `log-less-container` | 1 rewrite, 1 argv, 1 view | kubectl, bash/less for pager variants | Use native bounded logs or aggregate logs for active Pods/workloads. Container pager scope needs an explicit container input; foreground output is outside capture bounds/redaction. |
| [log-jq.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/log-jq.yaml) · `jqlogs` | 1 rewrite | kubectl-jq helper, bash, kubectl, jq | Use native log viewing or reviewed kubectl logs piped to jq. External helper remains required; its original unquoted shell recipe is not bundled. |
| [log-loki.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/log-loki.yaml) · `loki-container`, `loki-container-raw`, `loki-pods`, `loki-pods-raw`, `loki-node`, `loki-node-raw`, `loki-ns`, `loki-ns-raw` | 6 argv, 2 view | logcli, Loki server/credentials and its retained logs | Use native current-container logs; those do not replace Loki history/query services. Loki is a separately configured service/identity. Root-row fixtures test query argv only; container virtual scopes are unavailable. |
| [log-stern.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/log-stern.yaml) · `stern` | 1 argv | stern, Kubernetes log permissions | Use native Pod/workload aggregate logs with its documented reader limit. Quote numeric argv; use an explicit selector input because empty FILTER has no selected-name fallback. |
| [node-root-shell.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/node-root-shell.yaml) · `node-root-shell` | 1 rewrite | bash, kubectl, privileged Pod admission, nsenter, host shell | Inspect node details/YAML; review node debugging separately. The pinned script reads $1 without passing a selected host, uses an old image and privileged host namespaces; no automatic translation. |
| [openssl.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/openssl.yaml) · `secret-openssl-ca`, `secret-openssl-tls` | 2 rewrite | bash, kubectl, base64, openssl storeutl, less | Explicitly reveal the intended Secret key, then inspect a certificate with local OpenSSL. Certificate decoding is external and discloses Secret content; compatible OpenSSL commands need verification. |
| [pvc-debug-container.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/pvc-debug-container.yaml) · `pvc-shell` | 1 rewrite | sh, kubectl, head, permitted debug image and PVC access | Inspect PVC/Pod details and use a reviewed temporary Pod manifest with kubectl. Resource creation, RWO scheduling, heredocs, waits and cleanup require a reviewed script; not a native debug session. |
| [pvc-resize.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/pvc-resize.yaml) · `resize-pvc` | 1 argv | kubectl, expandable StorageClass/CSI driver and resize permissions | Review a PVC storage request change with kubectl; observe actual driver/controller status. A quantity allowlist replaces free-form JSON interpolation. No real storage expansion is certified by argv fixtures. |
| [remove-finalizers.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/remove-finalizers.yaml) · `remove_finalizers` | 1 argv | kubectl, target-resource patch permissions | Use the built-in deliberate finalizer workflow where supported, or a reviewed kubectl patch. Removing finalizers can bypass cleanup. The fixture is deliberately restricted to apps/v1 Deployments rather than global scope. |
| [resource-recommendations.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/resource-recommendations.yaml) · `krr`, `krr-ns` | 2 rewrite | bash, kubectl, awk, krr, supported Prometheus/backend | Inspect requests/limits; use separately configured kubectl top/metrics tools for observations. Recommendations remain external; the pinned namespace recipe uses RESOURCE_NAME rather than selected NAME and needs correction. |
| [rm-ns.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/rm-ns.yaml) · `rm-ns` | 1 rewrite | sh, kubectl, jq, namespace finalize permissions | Use reviewed ordinary namespace deletion and investigate finalizers first. Force-finalize is destructive; shell pipelines and missing explicit scope must be rewritten, never run blindly. |
| [spark-operator.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/spark-operator.yaml) · `toggleScheduledSparkApp` | 1 argv | kubectl, Spark Operator CRDs/controller | Inspect scheduled Spark CRDs and explicitly set suspend with kubectl. Rename the mixed-case command and replace inversion with an explicit desired boolean; verify the served GVR. |
| [start-alpine.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/start-alpine.yaml) · `start-alpine-pod` | 1 rewrite | bash, kubectl, permitted image and workload create/exec permissions | Use an existing container shell or review an explicit temporary Pod manifest. Embedded manifest creation/exec and cleanup are not a native debug workflow; a reviewed external script is needed. |
| [szero.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/szero.yaml) · `szero-down`, `szero-up` | 2 rewrite | sh, szero and workload scale permissions | Use reviewed per-workload scaling; record desired replica counts yourself. Namespace-wide down/up state storage and restoration belong to the external tool, not native scaling. |
| [trace-dns.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/trace-dns.yaml) · `trace-dns` | 1 view | bash, kubectl debug, Inspektor Gadget image/eBPF support, awk/cut, privileged node access | Inspect DNS-related events/logs; perform packet tracing with a separately reviewed diagnostic tool. Shell arithmetic/variables, virtual container scope and privileged debug Pods require review; no native DNS/eBPF tracing claim. |
| [vector-dev-top.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/vector-dev-top.yaml) · `vector-top`, `vector-top-container` | 1 rewrite, 1 view | sh, kubectl, a Vector container with vector executable/API enabled | Use native logs; Vector throughput statistics require Vector itself. Pod recipe can be rewritten as literal exec; virtual-container variant needs an explicit container input. |
| [watch-events.yaml](https://github.com/derailed/k9s/blob/558caafe7ba067467de46b320cc22ef11fef9c34/plugins/watch-events.yaml) · `watch-events` | 1 rewrite | sh, kubectl events/watch permissions | Use native related-event snapshots or the original background example in this guide. Shell conditional resource-group construction is not copied; the original example deliberately scopes to Pod events. |

````

## docs/troubleshooting.md

SHA-256: `0e9ab72dc817b0462b91db61fb3e524631641ee08ca247d90820a6164c6dcef4`

````markdown
# Troubleshooting

Start with the visible state and the operation that failed. Authentication,
permission, resource synchronization and local terminal errors have different
causes. The examples below use fictional `demo-lab` and `demo-apps` names; replace
them with an explicitly intended scope when running a command locally.

## Check the local installation

```sh
kuberich --version
kuberich --help
kuberich info
kuberich config check
```

These commands do not connect to Kubernetes or execute authentication helpers.
`info` describes the local application, dependency versions, preference paths and
resolved preferences. It does not prove that a cluster connection is healthy.
`config check` validates preferences without changing files.

If the command is missing, inspect the executable location reported by your
installer. uv and pipx tool executables must be on your shell's PATH. A locally
extracted standalone archive uses its own `./kuberich` entry point; retain the
complete extracted directory. See [installation](installation.md).

If `--version` reports an unexpected build, identify which executable your shell
resolves and which channel installed it. Upgrade through that same channel;
installing another copy does not upgrade the original one.

## A context is missing or different

KubeRich loads `--kubeconfig` when supplied. Otherwise it reads the configured
`KUBECONFIG` file list or the ordinary default. `--config` is an application
preferences file, not a kubeconfig.

Use an explicit path and context to make the intended selection unambiguous:

```sh
kuberich --kubeconfig /absolute/path/to/kubeconfig \
  --context demo-lab --namespace demo-apps --readonly
```

`:ctx` lists the loaded local catalogue; Enter selects a context. Browsing the
catalogue does not rewrite kubeconfig or authenticate. Names preserve case and
can include spaces. For merged files, relative certificate/helper paths resolve
against the file that supplied their entry.

A context switch cancels the previous connection and rejects its late results.
It does not change kubectl's persisted current context. Invocation overrides
continue to apply during that KubeRich invocation. See [context sessions](context-sessions.md).

## Authentication fails while kubectl works

Compare the explicit kubeconfig, context, namespace and inherited environment in
both commands. A kubectl invocation from another terminal can have a different
PATH, provider profile, cache directory or login session.

KubeRich captures helper identity and environment for a context session. If you
changed a profile, environment variable or kubeconfig after launching, start a
fresh invocation to deliberately use the new settings.

| Visible condition | Next step |
| --- | --- |
| Missing helper | Install the executable declared by the selected kubeconfig and make it available on the effective PATH. |
| Expired EKS credentials or SSO | Complete the intended AWS CLI profile login externally, then `:retry`. |
| Azure CLI login required | Establish the intended `az login` session for a configured `azurecli` entry, then retry. |
| Interactive exec helper required | Use explicit `:login` in a native terminal. It runs the declared helper, without inferring another provider mode. |
| Unsupported legacy credentials | Migrate the intended entry to supported exec/token/certificate configuration following the provider's instructions. |
| Helper timeout | Check provider login/connectivity. Background helpers have closed stdin and bounded execution; they cannot wait indefinitely for a prompt. |

`:login` restores the workspace after completion or cancellation. Authentication
is allowed in read-only mode because it enables reads. Provider tools own their
login caches; KubeRich does not store a second cloud identity database.

[EKS](eks-authentication.md), [AKS](aks-authentication.md) and
[credential interoperability](kubeconfig-interoperability.md) explain supported
contracts and the limits of real-provider certification.

## The session is connected but the table is empty

Connection status and resource status are separate. A successful namespace
discovery does not establish permission to list every resource family.

1. Clear the local filter: Escape leaves its input first, then clears the filter
   from the table. Confirm whether the visible count changes.
2. Check the context and namespace in the header. `:ns demo-apps` selects an exact
   namespace; `:ns *` requests an all-namespace scope that needs broader permission.
3. Distinguish **No resources** from **Permission denied**, **Stale** or a removed API.
   A successful empty list is valid; a denied list is not presented as empty data.
4. For a failed discovered API, return to `:pods` or another available resource.
   `:refresh` renews discovery and the selected watch; `:retry` reconnects the session.

When namespace listing is denied, direct selection of a permitted namespace can
still work. Changing to all namespaces does not bypass Kubernetes RBAC.

## A live view says stale or reconnecting

The view retains its last successful snapshot during a temporary watch/network
failure and marks it stale. Bounded reconnect/relist work runs in the background;
it does not establish that retained rows describe the current server state.

Check VPN/network reachability and the selected API endpoint locally. `:status`
opens connection details. `:retry` creates a new owned session; changing context
also replaces it. A quiet stream can renew normally, so absence of new rows alone
does not mean resources disappeared.

TLS errors require checking CA, hostname and client certificate configuration.
Timeout/unreachable states concern connectivity or request deadlines. Resolve
the stated cause before retrying rather than weakening TLS verification.

## Logs or a shell fail

Logs require a valid captured pod/container and permission for `pods/log`. Previous
logs may be absent even when current logs work. A replaced/deleted pod invalidates
the captured selection; return to the table and select the current object.

Shells additionally require write mode, local `kubectl`, permission for `pods/exec`
and an available configured shell in a running container. Read-only mode deliberately
blocks launch. The embedded terminal does not implement every graphics, mouse or
advanced keyboard protocol; a program using those features can exceed its scope.

`exit`/Ctrl+D returns normally; Ctrl+] closes the owned shell. During local history
review, Escape returns to remote-key routing. See [shell controls](container-shell.md).

## A key or clipboard action does not work

Terminal emulators and tmux can consume function keys or Alt combinations. Use
`:ctx` and `:ns` when F2/F3 are intercepted, and `:back`/`:forward` when Alt navigation
is unavailable. Consult the current view's `?` help.

Copy sends redacted text through terminal OSC52 support. SSH/tmux forwarding and
the terminal's clipboard permission determine whether the host receives it.
The application showing a copy result does not certify the host clipboard.
Use a reviewed explicit file export where supported if clipboard integration is
unavailable. [Terminal compatibility](terminal-compatibility.md) describes the scope.

## A change is blocked, conflicted or uncertain

Review and Confirm are separate. Missing write mode, a stale captured UID/version,
an autoscaler or insufficient permission can block a change before writing.
A conflict requires reading the current object and preparing a new review.

An uncertain outcome means a sent request may have applied even if its response
was lost. Inspect the object and `:writes` before another attempt. KubeRich does
not automatically replay writes. Leaving a review does not undo a confirmed action.

See [guarded changes](mutations.md), [editing](editing.md) and [workloads](workloads.md)
for operation-specific restrictions.

## Report a problem

Include the KubeRich version and installation channel, OS/architecture, Python
version for source installs, terminal/tmux/SSH arrangement, the visible state and
the smallest sequence that reproduces the problem. Describe expected and actual
behavior. State whether it also reproduces with an owned disposable cluster.

Use fictional context, namespace, resource and account names in a public report.
Do not attach kubeconfig, token/helper output, private certificates, credentials
or customer logs. Inspect screenshots and copied diagnostics before sharing:
application redaction cannot recognize every private business name or log message.
For vulnerabilities, follow [the security reporting policy](../SECURITY.md).

````

## docs/terminal-compatibility.md

SHA-256: `dd4fa26fe25fe64f9d8dc078305fbb99de44553875bfbdc9d9dffd8bb0124096`

````markdown
# Terminal compatibility

KubeRich runs in a local terminal, over SSH, or inside tmux. Its default container
shell stays inside the Textual interface. Explicit native tools, including Azure
login, temporarily receive the terminal and return to the workspace.

The minimum qualified workspace size is 40 columns by 12 rows. Use a UTF-8 locale
and a terminal advertising its actual capabilities. The automated tmux fixture
uses `-u` and `screen-256color`; its configuration is isolated from user settings.
Standard 16-color rendering and `NO_COLOR` input/navigation receive terminal
checks. This does not establish compatibility with every terminal emulator,
locale, Unicode font, or custom tmux configuration.

## Shutdown and reconnection

Normal exits, Ctrl+C, Ctrl+Q, external SIGTERM and external SIGHUP unwind owned
processes and streams. SIGTERM returns 143; SIGHUP returns 129. Native handoffs
restore foreground ownership and terminal attributes before returning. Embedded
shells own a separate PTY and reap their child when closed, including cancellation
while the pod preflight is still pending.

Losing SSH without a multiplexer revokes the remote terminal. KubeRich closes its
tasks and child processes, then exits 129; the SSH client normally returns 255.
The local SSH terminal can be restored, but a revoked remote TTY cannot receive
escape sequences. Its attributes may be unavailable; Darwin can retain readable
attributes while rejecting output. Evidence preserves the actual observation
instead of claiming remote restoration. Only captured output
descriptors still identifying that revoked TTY are redirected to `/dev/null`
during hangup. Live terminals, replaced descriptors and file/pipe output remain
untouched. This prevents failed buffered shutdown writes from changing the
process exit code to 120. A zero-byte write verifies output when the driver still
returns attributes; it emits no terminal input or output. The probe temporarily
blocks SIGTTOU, restores the previous mask, and surfaces unexpected errors.

Inside tmux, losing SSH detaches the client and keeps the application and an open
embedded shell running. Reattaching to the same session restores the workspace;
normal shell return and application shutdown still close owned resources.

## Tested scope and limits

Source tests cover Ubuntu 24.04 x86_64 and macOS 26 ARM with Python 3.12–3.14;
standalone and Homebrew installations have separate native host/architecture
checks. See [installation scope](installation.md#qualification-scope). Each release
candidate needs fresh qualification before its public channels are activated.

Automated PTY tests exercise actual input, output, resize, shutdown and terminal
restoration, including local SSH and tmux transports. They do not certify every
physical terminal emulator, font, SSH policy or host clipboard. macOS 14 Intel
physical trials and real cloud-provider compatibility remain separate limits.

Use `:ctx`/`:ns` if your terminal consumes F2/F3, and `:back`/`:forward` if Alt
navigation is intercepted. The current view's `?` help shows available actions.
Embedded shells forward ordinary keys to the remote program; local history
review has separate keys. [Shell controls](container-shell.md) describes return
and session closure. [Troubleshooting](troubleshooting.md) distinguishes connection,
permission and terminal failures.

## Verification

Development tests require `ssh`, `ssh-keygen`, `sshd` and `tmux`, in addition to
the locked Python development environment. These are test prerequisites, not
dependencies for an ordinary local KubeRich installation. Missing tools fail the
required suite explicitly. Hosted runners install them before testing.

```sh
uv sync --locked --group dev
uv run pytest tests/terminal/test_transports.py tests/terminal/test_shutdown.py tests/terminal/test_container_shell.py tests/terminal/test_handoff.py tests/unit/test_terminal_lease.py tests/unit/test_terminal_model.py
uv run pytest tests/packaging/test_distribution.py
```

Each transport fixture owns a loopback high-port SSH daemon, generated host/client
keys, pinned known-host file, private configuration directory and explicit tmux
socket. It disables password/PAM authentication, forwarding, ambient SSH agents,
user startup files and user SSH/tmux configuration. `StrictModes no` applies only
to this generated-key daemon because temporary-directory parents are writable;
the fixture directory is mode 0700 and private keys are mode 0600. It never
reconfigures a system SSH service or contacts a cluster outside its owned fixture.
tmux uses its own short mode-0700 temporary socket directory, so long macOS-style
test paths do not exceed Unix socket limits. Actual long-path trials exercise
this independently of unavailable macOS execution.
Loss tests terminate only a connection whose ancestry reaches that owned daemon.
An observing session owner forwards terminal signals to the actual application;
it does not immunize the application by inheriting ignored SIGHUP handlers.

Actual PTY output and separate inner/outer termios observations are retained in
`artifacts/terminal/*.ansi` and `*.json`. Fresh-wheel trials run the installed
entry point outside the checkout. Product fixes have regression witnesses for
external shutdown, private cursor queries, malformed CSI recovery and retained
normal/alternate buffer text after shrinking a rendered terminal.
Additional failing witnesses cover deferred header callbacks after view removal
and a stale queued resize event overriding the actual native TTY dimensions.

The test observer accepts private device-status queries
without injecting artificial input into the application. Actual terminal bytes
still determine the observed screen. Raw termios values remain in the evidence;
only Darwin's kernel-maintained `PENDIN` bit is normalized when comparing
restoration. Darwin sets that bit when returning to canonical mode and preserves
it across attribute updates. Every other flag, both speeds and every control
character remain exact comparisons; negative controls reject their changes.
See [Apple's tty implementation](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/tty.c)
and [macOS terminal verification](acceptance/macos-terminal-verification.md).

The workload-checkpoint six-environment source matrix passed on Ubuntu 24.04
x86_64 and macOS 26 ARM with Python 3.12–3.14. Four standalone archives and
three Homebrew hosts have separate native evidence: macOS 14 ARM and 15 Intel
are the actual Mac native hosts. Exact 0.1.0 candidate evidence remains required
before activation; see [installation scope](installation.md#qualification-scope).
Physical terminal-emulator/font/manual clipboard and macOS 14 Intel trials are
not claimed by automated PTYs. Real-provider compatibility requires separate trials.

## References

- [Textual suspension](https://textual.textualize.io/guide/app/#suspending-your-app)
- [OpenSSH server configuration](https://man.openbsd.org/sshd_config)
- [tmux documentation](https://github.com/tmux/tmux/wiki/Getting-Started)
- [xterm control sequences](https://invisible-island.net/xterm/ctlseqs/ctlseqs.html)
- [Python exit cleanup behavior](https://docs.python.org/3.12/library/sys.html#sys.exit)

````

## docs/resource-workspace.md

SHA-256: `123c264c12ba6738603966c73c78af197d83ca8ae91beb24fdba672c782071be`

````markdown
# Resource workspace

KubeRich uses a keyboard-driven resource workspace built with original
Python/Textual code. The shared header, input area and navigation trail keep
resource views in a consistent frame.

The default `k9s` theme has a black background, cyan tables/frames/selection,
yellow metadata labels/navigation, blue shortcut keys and white headings.
Explicit Textual themes remain supported. Select it for one invocation:

```sh
KUBERICH_THEME=k9s uv run kuberich
```

The top header shows context, cluster/user **aliases**, namespace, connection
state and installed application version, without credentials. View-specific
shortcuts show implemented pod, namespace, container and log actions. Inputs sit
above resources. The dedicated `:` bar shows the selected completion suffix next
to typed text, in muted italic styling; it never opens a dropdown over resources.
Tab accepts it and Up/Down cycles the bounded local candidates. Plain Enter
submits literal input; Enter after deliberate cycling accepts that candidate.
Typing makes no API requests; suggestions still use the session name catalogue.
The command row sits inside its own rectangular border. Below 16 terminal rows,
it keeps side borders so the table retains usable height; all views reserve the
same four ordinary/two compact interaction rows.

The bottom trail identifies the current view and Escape action. Escape first
leaves an input, then clears an active filter, then returns to the parent view.
Pods, contexts, namespaces, containers and logs share the same frame margins, header
columns and reserved interaction/footer rows at a fixed terminal size. Clicking
controls or changing focus does not move that frame. View actions change while
their header columns retain a fixed row count. Container/log views retain captured
pod identity and parent viewport. Embedded
shells retain their existing target frame, remote-key routing and cleanup.

## Live namespaces

Bare `:ns`, `:namespace`, `:namespaces`, `n` or F3 open a normal workspace table.
It reads real Namespace objects through the owned per-session LIST/WATCH service.
NAME/STATUS/AGE columns use UID selection and ascending name order; unknown
status/time appears as `Unknown` / `—`.

- `/` filters name/status using the same literal and bounded `re:` syntax as pods.
  Enter returns to the table; Escape there clears the filter.
- Enter opens pods in the selected namespace. The namespace filter does not
  filter pods. Escape from the unfiltered pod table restores the namespace
  filter, UID selection and viewport.
- `0` or **All namespaces** opens all pods. It is a scope action, not a fabricated
  resource row with a fake UID.
- `j/k`, arrows, PageUp/PageDown and `g/G` navigate namespace rows.
- `:ns NAME`, `:ns *`, `:po NAME`, `:po *` still select pods directly. A pod filter
  stays active when changing scope from the pod view.
- `:po` opens pods in the current scope. `:back` / `:forward` retain resource kind,
  context, namespace, filter and viewport.

Only the active resource is watched. Switches invalidate old results, await old
watches/projection/filter workers and clear obsolete navigation targets. Denied
listing is an error rather than an empty table; directly entering an allowed
namespace still works. Temporary failures retain the last snapshot with stale
status. Recreated namespaces have distinct UID selection.

Inspection uses existing captured-UID details/YAML/events services. Logs and
shells require a pod; namespace mutations remain planned.

## Local contexts

Bare `:ctx`, `:context`, `:contexts`, `c` or F2 shows a workspace table with
NAME/CLUSTER/AUTHINFO/NAMESPACE and `*` for the selected session. These entries
come from the loaded kubeconfig catalogue, not a Kubernetes resource endpoint.
Aliases are rendered as redacted literal text; no credential bodies or API URLs
are displayed. `/` filters these columns with the existing bounded literal/
regex semantics. Browsing makes no authentication request and rewrites no file.

Enter connects to the exact selected name, including case/spaces, and opens pods.
Switching keeps the existing owned cancellation and generation checks.
Escape first clears the filter, then restores the preceding pod/namespace view
and its filter/viewport. Back/forward also retains the context table state.
Direct `:ctx NAME` still connects immediately; context tables have no resource
YAML/details/events because their rows are local configuration.
Scoped `:ns NAME`, `:ns *` and `:po NAME` from contexts open pods with their own
filter; they preserve the context query/cursor for returning to the catalogue.

## Container details

Enter on a pod shows NAME, TYPE (App/Init/Sidecar), READY, STATE, RESTARTS, IMAGE,
PROBES(R:L:S), CPU REQ/LIM, MEM REQ/LIM and PORTS. Status is joined by container
name, not list position. Missing readiness/restart data is `—`, absent state is
Unknown, and waiting/termination reasons such as CrashLoopBackOff/OOMKilled remain
visible. Configured probes use readiness:liveness:startup order and on/off labels.
Ports include declared name/number/protocol, with a bounded list and `…` when longer.

CPU/MEM are specification requests/limits in Kubernetes quantity notation, with
`—` for undeclared quantities. They are not live usage. Values come from the
captured pod snapshot; reopen to refresh. Horizontal arrows/Home/End reveal wide
columns. Enter/l logs and s/x shell retain the captured UID/container and parent
cursor/scroll state. Live container refresh, ephemeral debug containers and usage
metrics are planned.

## Sizes and remaining work

At 70+ columns the header uses six rows. Narrow terminals use four rows, omitting
cluster/user aliases and the logo. Below 16 rows the three-row context/namespace/
state header preserves room for resources/inputs. Container hints and log controls
remain available; help contains secondary shortcuts. NO_COLOR retains textual cues.

The upper-right brand is an original five-row KubeRich ASCII logo from 120 columns,
or a compact wordmark at 70–119 columns. Resizing changes only the mark's reserved
width, keeping the shared view geometry consistent at each terminal size.
The project, installed version label and CLI remain KubeRich/`kuberich`.

`--headless` hides the shortcut/logo header, `--logoless` hides its brand and
`--crumbsless` hides identity/navigation bars. Log `z` hides the header/route and
frame, preserving search, controls and stream ownership.

The header shows the actual installed version. Optional real release
notices, custom/live/context themes and Kubernetes-version/CPU/memory
presentation are planned. Clipboard receipt depends on the host terminal.
This release does not establish full K9s parity.

Behavior references: [K9s commands](https://k9scli.io/topics/commands/),
[K9s skins](https://k9scli.io/topics/skins/),
[Textual themes](https://textual.textualize.io/guide/design/).

````

## docs/standard-resources.md

SHA-256: `5773e28d36ff06f92c93543ea8611df5bd5660d36f7a88cfda8411b5ce55e65a`

````markdown
# Standard resource views

KubeRich adds 15 resource families to the existing live workspace. Endpoints and
served versions come from the connected cluster's discovery response. Each view
uses the same scoped LIST/WATCH owner, stable UIDs, filter bar and history.

| Command (full resource names also work) | Main columns |
| --- | --- |
| `:deploy` | Ready, desired, updated, available replicas |
| `:rs` | Desired, current, ready replicas |
| `:sts` | Ready, desired, current, updated replicas |
| `:ds` | Desired, current, ready, available nodes |
| `:job` | Outcome, succeeded, completions, active, failed |
| `:cj` | Schedule, suspend, active jobs, last schedule |
| `:svc` | Type, cluster IP, external address, ports |
| `:ep` | Ready/not-ready addresses, ports |
| `:ing` | Class, hosts, published address |
| `:cm` | Counts of data and binary keys |
| `:sec` | Secret type and key count |
| `:no` | Readiness, scheduling disabled, roles, kubelet version |
| `:pvc` | Phase, volume, capacity, access modes, storage class |
| `:pv` | Capacity, access modes, reclaim policy, phase, claim, storage class |
| `:sc` | Provisioner, reclaim policy, binding mode, expansion |

Namespaced tables also show namespace; every table shows name and age. For a
chosen scope, use `:deploy TEAM` or `:svc *`. Nodes, PVs and StorageClasses are
cluster-scoped; a namespace argument is rejected. They preserve the session's
namespace choice for the next namespaced view. Initial commands work too:

```sh
uv run kuberich --context YOUR_CONTEXT --readonly --command 'deploy YOUR_NAMESPACE'
```

Only run that command against a context you intend to read. `:c` still offers
context commands first; additional resource aliases appear in the same inline
completion. Tab accepts a suggestion. `/` searches displayed summary fields;
Secret and ConfigMap payload values never enter rows or filter text.

Use Enter or `d` for details, `y` for redacted YAML, `e` for UID-associated events,
and Escape to return to the retained table. `s` cycles sort columns, Shift+S
reverses, and clicking a header selects that column. Counts, capacities and times
sort by their typed values. Unknown values stay last in either direction.
Kubernetes may omit zero status counters; a completely missing workload status
remains unknown. `j/k` and `g/G` navigate; Alt+Left/Right restores the prior view,
including scope, filter, sorting and viewport.

Shell and logs remain pod/container actions. [Manifest editing](editing.md),
[workload scale/rollout](workloads.md) and [port forwarding](port-forwards.md) now
have their own implemented contracts. [Deletion and Job operations](resource-operations.md)
use captured confirmation and retained results. Owner drill-down is planned.
These views do not establish full K9s parity.
Endpoints remains available when served, although modern clusters should
use the implemented EndpointSlice view for endpoint discovery.

An absent API, denied LIST/WATCH/GET, expired resource version and a successful
empty collection retain their distinct existing states. No fallback guesses a
different API group or silently substitutes an empty list.

`domain/registry.py` holds immutable definitions and pure summaries;
`services/pods.py` shares the owned background projection cache;
`ui/standard.py` renders all these families in one table. Ordinary details use
the existing [inspection policy](resource-inspection.md). Discovery, watch and
context-generation behavior remain in the existing services.

## Generic discovered resources

Browse other discovered APIs, including CRDs, with an unambiguous plural,
singular or short name: `:wdg TEAM` or `:widgets *`. Qualify a family as
`:widgets.example.test`; append `/v1beta1` to select that exact served version.
An omitted version follows discovery's preferred version, including after
`:refresh`. The title shows the actual API group/version and selected scope.
Explicit cluster-scoped namespace arguments are rejected. Built-in command
and standard-resource aliases retain their familiar meaning; `:resource NAME`
selects a discovered alias that overlaps one. `.core` explicitly selects the
core API group, for example `:resource pods.core/v1`.
Explicit `:resource pods` and `:resource namespaces` also use the generic read-only
table. Their `.core` display/completion identifier represents the API's actual
empty group; `:po` and `:ns` return to the familiar built-in workspaces.

For initial generic navigation, use an explicit resource command:

```sh
uv run kuberich --context YOUR_CONTEXT --readonly --command 'resource widgets.example.test/v1beta1 YOUR_NAMESPACE'
```

The application connects and discovers APIs before resolving this initial
command. Unknown or ambiguous families keep the available view and report the
error; no endpoint or version is guessed. Completion offers qualified names and
served versions, hiding ambiguous discovered short names. `:refresh` renews
discovery and the owned LIST/WATCH without reloading credentials or replacing
the connected client. Removed APIs remain a failure state; use `:po` or another
available resource command to recover. `r`/`:retry` still reconnects.

Server Table columns appear alongside metadata-backed namespace, name and age.
Numeric, boolean and date columns sort by their types; unknown values sort last.
Date columns order absolute timestamps newest first and elapsed printer durations
shortest first. A column containing both representations groups timestamps before
durations; reverse sorting reverses both groups while retaining unknowns last.
Equal timestamps retain name/UID order across unrelated object updates.
When Table conversion or malformed printer metadata is unavailable, the view
uses the stable metadata columns and retains full objects for inspection.
Each retained row carries its own printer schema. A renewed schema leaves
incompatible old cells unknown until their objects update, retaining selection
without interpreting old values under a different header.

`:columns` lists the server's positional keys, such as `c2=Level` and
`c3=Enabled`; the server's identity/age columns are omitted. Use
`:columns c3 c2` to choose and order fields, including optional wide-priority
fields. `:columns none` shows metadata only and `:columns default` restores the
server's ordinary columns. Invalid or duplicate keys retain the previous view.
In published 0.1.0, layouts are transient, bounded to 32 context/GVR entries and
reset when the server schema or resource descriptor changes, or when switching
context. The next-release source adds [keys, aliases and saved resource views](navigation-preferences.md).
Use `:views` to choose display order, widths, alignment and a typed sort field,
then apply for the session or explicitly save globally/per context. Server views
are version-pinned and fingerprint their printer schema; changed fields fall back
to working defaults while the original saved preference remains intact.

Enter/`d`, `y` and `e` reuse captured-UID details, redacted YAML and related events.
Unknown manifest fields remain in YAML. In 0.1.0, `/` searches displayed fields.
Next-release saved views retain the typed row model for sorting: a hidden sort
field is also searchable. Fields excluded by `:columns` and not needed for sorting
remain outside that projection. Pod filters retain their documented readiness,
status and restart fields even when a saved layout hides them; standard-resource
filters likewise use their complete non-age summary. Layouts control display,
not confidentiality; the existing redaction policy remains in force.
Alt+Left/Right and the context/namespace workspaces retain resource identity,
version, filter, compatible sort and viewport. Direct `:ns TEAM` preserves an
active generic resource. Generic browser actions are read-only in this
checkpoint. Return to `:po` for pod/container logs, exec, attach, copy and selected
port forwarding. Editing custom resources and reactive relationship jumps are planned.
Server headers and strings are displayed literally, sensitive column names and
credential-shaped cells are redacted, and opaque Secret/ConfigMap server cells
are hidden. Arbitrary custom fields are not guaranteed to be confidential;
inspect only resources appropriate for your context and access.

See [generic browser acceptance](acceptance/generic-resource-browser.md).

See [acceptance evidence](acceptance/standard-resources.md) and the
[quickstart](quickstart.md). Field semantics follow the official
[Deployment API](https://kubernetes.io/docs/reference/kubernetes-api/apps/deployment-v1/),
[PersistentVolume API](https://kubernetes.io/docs/reference/kubernetes-api/core/persistent-volume-v1/),
[Endpoints API](https://kubernetes.io/docs/reference/kubernetes-api/core/endpoints-v1/)
and [Quantity definition](https://kubernetes.io/docs/reference/kubernetes-api/definitions/quantity-resource/).

````
