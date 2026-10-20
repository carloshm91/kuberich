# Current preview

**KubeRich 0.1.0 is published** on [PyPI](https://pypi.org/project/kuberich/0.1.0/),
[GitHub Releases](https://github.com/carloshm91/kuberich/releases/tag/v0.1.0) and
[Homebrew](https://github.com/kuberich/homebrew-tap).

```sh
brew install kuberich/tap/kuberich
# Alternative with Python 3.12–3.14:
uv tool install --python 3.12 kuberich
kuberich --version
kuberich config check
```

Choose one installation method. Start with
`kuberich --context YOUR_CONTEXT --namespace YOUR_NAMESPACE --readonly`, using
your intended context and namespace. The [installation guide](installation.md)
covers pipx, standalone archives, updates and removal. The
[website](https://kuberich.com/) and [documentation](https://docs.kuberich.com/)
now serve the verified public 0.1.0 content. The maintainer approved the protected
deployment, which passed on 2026-10-13 UTC. Independent custom-domain HTTPS reads
matched all 42 published files and all 26 direct guide URLs to the checked build.
The landing links to the dedicated documentation host; four legacy `/docs`
routes return the expected 301 redirects. Both custom 404 routes passed too.
The former development-version and unavailable-package notices are gone.

Final hosting acceptance remains open. Read-only verification on 2026-10-19
confirmed the HTTPS `www` redirect to the apex, but HTTP `www` still returned
522 without a redirect. Both docs-host assets now return `index, follow`; three
unchanged apex-host assets retain the earlier `noindex, nofollow` header. Their
bodies match the approved build. The HTML pages already serve `index, follow`.
Ordinary-URL reads must verify the remaining redirect/cache responses before
claiming final custom-domain acceptance. No zone/DNS/cache change was made by
that inspection.

## Source checkpoint toward 0.2.0: context edits and pod cleanup

In `:ctx`, `:rename NEW` renames the selected context and Ctrl+D or `:delete`
deletes it. Review shows the file and the change first; a backup is written
before the file is replaced. In a pods view, `:cleanup` reviews deleting the
completed and failed pods shown. Published 0.1.0 remains unchanged.

```sh
uv run pytest tests/unit/test_kubeconfig_edit.py tests/unit/test_cleanup.py tests/contract/test_kubeconfig_files.py tests/ui/test_context_cleanup.py
uv run python -m scripts.verify_cleanup_kind --kind /absolute/path/to/kind
```

See [context edits](context-sessions.md#rename-or-delete-a-context),
[finished-pod cleanup](resource-operations.md#clean-up-finished-pods) and
[acceptance evidence](acceptance/context-cleanup.md).

## Source checkpoint toward 0.2.0: forwarding presets

The next-release source adds named/container-qualified TCP mappings, local and
exact-context presets, explicit local permission for annotation shortcuts,
kubectl child transport selection and optional bounded reconnects. Non-loopback
binds still need separate confirmation; resource listing never starts a listener.
Published 0.1.0 remains unchanged.

```sh
uv run pytest tests/unit/test_forward_presets.py tests/contract/test_forward_reconnect.py tests/ui/test_forward_presets.py
uv run pytest tests/terminal/test_port_forwards.py tests/packaging/test_forward_presets.py
```

The final focused command passed 220 cases in 79.79 seconds, including real
source/installed terminals and initial/replacement startup failure regressions. Both new deterministic modules measured 100%
line/branch coverage. Fresh owned-kind trials verified HTTP, named annotations,
both transport modes, listener collisions, deliberate remote bind, Service backend
replacement/reconnect and full cleanup. Required platform/native PR checks and
the cumulative phase qualifier remain independent gates.
See [forwarding behavior](port-forwards.md) and
[acceptance evidence](acceptance/forward-presets.md).

Required checks also exposed a table-cache collection pause and a configuration
key-name clipping race. The source now releases retired native cache entries
promptly and sizes key columns from captured metadata before painting. Both have
owned negative controls. The local Python 3.13 runtime trial retained an 89-ms
maximum gap with the original 150-ms limit and active GC; fresh full platform/native
qualification remains required. The maintainer requested stopping after this
ticket's verified delivery, before starting the next implementation issue.

## Source checkpoint toward 0.2.0: terminal navigation

The next source checkpoint adds command/filter recall, inverse/fuzzy/metadata
filters, wide/errors controls, bounded UID ranges and explicit namespace
favorites. Read-only workspaces share chrome and nested command routing;
container status refreshes from the owned Pod watch. Native macOS/X Window System writers and
OSC52/tmux clipboard requests have explicit UTF-8 bounds. Published 0.1.0 is unchanged.

```sh
uv run pytest tests/unit/test_interactions.py tests/unit/test_selectors.py tests/unit/test_metadata_filtering.py
uv run pytest tests/ui/test_interactions.py tests/terminal/test_interactions.py
```

Focused deterministic clipboard/history/range/selector modules passed 100% line
and branch coverage. Pilot verified controls at 40 and 120 columns, live
container status and fatal permission invalidation. Owned kind verified status
patches, same-name UID replacement, nested namespace/context drain and Escape;
that Pod was deliberately unscheduled and is not a real exec/restart trial.
Owned Xvfb and ephemeral hosted macOS verified synthetic plaintext clipboard
roundtrips. Source and installed console/module PTYs verify navigation and exact
OSC52 receipts. The [implementation PR](https://github.com/carloshm91/kuberich/pull/206)
retains the successful protected platform/native and coverage qualification.
See [behavior and limits](terminal-navigation.md).

## Source checkpoint toward 0.2.0: plugin compatibility and examples

The source classifies all 50 pinned community plugin files and 108 commands,
including two executable helpers. It adds three original reviewed definitions
for Pod inspection, an interactive local kubectl exec and finite background
event collection; 18 synthetic argv adaptations record their changed semantics.
Upstream scripts/virtual views/legacy tools are not automatically imported,
installed or claimed as native features. The published 0.1.0 package is unchanged.

```sh
uv run pytest tests/contract/test_plugin_examples.py tests/unit/test_plugins.py
uv run pytest tests/terminal/test_plugin_examples.py
```

See [compatibility and examples](plugin-compatibility.md) and
[acceptance evidence](acceptance/plugin-compatibility.md). Runtime prerequisites,
read-only trust, output/Stop behavior and separate service identities are explicit.

## Source checkpoint toward 0.2.0: plugin execution

The next-release source adds `:plugins`, `:plugin NAME`, typed Review/Run forms,
resource-scoped shortcuts and `:pluginjobs`. Capture, background and native
foreground commands use owned processes, explicit read-only trust, bounded
captured output and private single-context credentials. Context/UID invalidation
and exit drain processes before removing connection files. The published 0.1.0
package is unchanged; no package/tag/site publication is part of this checkpoint.

```sh
uv run pytest tests/contract/test_plugins.py tests/ui/test_plugins.py
uv run pytest tests/unit/test_credential_child.py tests/unit/test_plugin_commands.py
uv run pytest tests/terminal/test_handoff.py
```

See [the invocation guide](plugins.md) and [acceptance evidence](acceptance/plugin-execution.md).
Foreground local plugins deliberately use native terminal handoff; pod/container
shells remain embedded. Arbitrary local programs are not sandboxed, and direct
foreground output cannot be redacted by KubeRich.

## Source checkpoint toward 0.2.0: plugin configuration

The source validates explicitly configured global/context plugin files, exact
resource scopes, shortcut overrides, typed inputs and captured literal variables.
This configuration checkpoint executes no command; interactive invocation and
owned process execution follow in the next task. Published 0.1.0 is unchanged.

```sh
uv run pytest tests/unit/test_plugins.py tests/contract/test_plugin_files.py
```

The offline CLI test also runs `kuberich --config <owned-fixture> config check`,
verifies no sentinel command was executed and confirms the file is unchanged.
See [configuration and trust](plugins.md) and [evidence](acceptance/plugin-contract.md).

## Source checkpoint toward 0.2.0: navigation preferences

The next-release source supports per-view navigation keys, literal command aliases
and resource-specific column order, visibility, width, alignment and typed sort.
`:views` applies a session choice or explicitly saves globally/per context.
Help/completion reflect effective settings; invalid overrides retain working
navigation and the original file. Server-column signatures prevent stale saved
positions from being interpreted under a changed schema.

```sh
uv run pytest tests/unit/test_navigation_preferences.py tests/contract/test_navigation_preferences.py
uv run pytest tests/ui/test_navigation_preferences.py tests/terminal/test_preferences.py
```

The source PTY verifies actual remapped keys, alias completion, private saves,
reopening and terminal restoration against an owned local API. Published 0.1.0
packages remain unchanged. Expanded filters, resource jumps, reactive reload and
plugins remain later work. See [the guide](navigation-preferences.md) and
[measured acceptance](acceptance/navigation-preferences.md).

## Source checkpoint toward 0.2.0: appearance

The next-release source provides `:themes`, `:theme` and `:about`, custom opaque
palettes, environment/context/global precedence, explicit preference saves and
runtime `--invert`. Version notices are disabled by default; opt-in checks are
asynchronous, bounded, cached and offline-safe. See [the guide](themes.md).

```sh
uv sync --locked --group dev
uv run kuberich --command themes
uv run kuberich --invert --command about
```

The commands were exercised through actual source/installed-console/module PTYs,
including NO_COLOR, preview/cancel, a real save, 40-column About and terminal
restoration. Owned HTTP/cache and Pilot cases cover errors, cancellation,
precedence and private persistence. [Appearance acceptance](acceptance/appearance.md)
records measured scope; the issue-linked PR retains exact-head platform gates.
These features are not in the published 0.1.0 package. No real cloud was used.

## Source checkpoint toward 0.2.0: configuration data

The next-release source adds Enter / `v` on ConfigMaps and Secrets: a key/size
index with values hidden by default, explicit per-key reveal/copy, UTF-8/Base64
selection, bounded output and fresh UID/version-bound reads. Secret manifests
use the existing deliberate editor disclosure, redacted review, strict dry-run
and separate conditional Apply. Ordinary inspection stays redacted.

```sh
uv sync --locked --group dev
uv run kuberich --context YOUR_CONTEXT --namespace YOUR_NAMESPACE --readonly
```

These commands run the checkout, not an upgrade to the published 0.1.0 package.
Owned-loopback Pilot and real PTY verification cover the controls; disposable-kind
verification covers actual Secret/ConfigMap reads and guarded edits. Measured
final acceptance is retained in [configuration-data evidence](acceptance/configuration-data.md).
No maintainer cluster was used; real-cloud certification remains deferred.

## Available workflows

The current implementation supports live pods, context and namespace tables,
standard resource views and discovered custom resources. Commands complete
inline, filtering uses `/`, and Vim-style navigation retains the selected
resource as the table refreshes.

Enter on a pod opens its containers; Enter on a container opens its logs.
Current, previous and aggregate logs, embedded shells, pod/Service forwarding,
captured attach and guarded file transfers are implemented. Reviewed changes
include annotation updates, manifest dry-run/Apply, scale/restart/rollback,
deletion and Job/CronJob operations.

Metrics, user plugins and advanced node/debug operations remain planned.
Complete K9s parity and stable 1.0 compatibility are later milestones.
The next planned public phase, 0.2.0, includes themes, configurable navigation
and views, external plugins, deliberate secret editing, terminal refinements
and verified Homebrew bottles to reduce installation compilation. These remain
planned until implemented and qualified; 0.1.0 currently installs from source
through Homebrew.
The [guided workflow](everyday-workflow.md) describes the current controls,
and the [release phases](releases.md) explain what belongs to each version.

## Current validation

The website and documentation contain fictional examples and actual application
renders from owned fixtures. Both generated surfaces passed checks across
57 offline-preview pages, including desktop/mobile navigation, accessibility
and local links. The public build has 30 pages without duplicate guides. Its
exact deployed artifact passed all 30 desktop and 30 mobile browser cases,
keyboard/copy/no-JavaScript navigation and zero automated accessibility
violations. Live custom-domain checks independently matched the served content;
the remaining asset-header cache finding above is retained without a waiver.
Exact main `3dbf9c0118193aa11635baea6ae2a0b36bee4c6e` passed all six source
Python combinations and all four native executables. Original audits and native
provenance passed independent review. Measured coverage was 99.0987–99.1296%
lines and 96.8382–96.9721% branches, with 100% for designated critical modules.
Three fresh consecutive rounds passed all thirteen owned-cluster scenario
families with caller configuration preservation and cleanup.

Actual TestPyPI/PyPI uploads, SBOM/build attestations, immutable annotated tag and
all 24 public GitHub attachment digests passed verification. Public PyPI-by-name
uv and pipx installs passed version/help/default-preference checks, no-op upgrade
and uninstall in owned environments. The public Linux x86_64 archive also passed
CLI checks outside the checkout. The other archive bytes match their native
hosted qualification. The published Homebrew formula passed Linux/macOS style,
online audit, source install, CLI tests and uninstall before protected merge.
There is no prior public release to claim as a version-upgrade baseline.

These safe local commands have been verified against the candidate:

```sh
uv sync --locked --group dev
uv run kuberich --version
uv run kuberich --help
uv run kuberich config check
```

They do not contact Kubernetes or execute authentication helpers. Connecting
requires an explicitly intended kubeconfig/context; see [first launch](quickstart.md).
The default preference permits writes. Use `--readonly` for a first connection;
write actions require the corresponding Kubernetes permissions and their
operation-specific target/review controls.

The [candidate evidence](acceptance/first-release-preparation.md) retains measured
results and limits. [Historical engineering checkpoints](preview-history.md)
remain available separately. Real cloud-provider and physical-terminal
certification still require their later opt-in trials.
