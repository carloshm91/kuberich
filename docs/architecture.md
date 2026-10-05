# Architecture decisions

Status: accepted planning baseline, 2026-10-04. Changes require an issue and an
updated decision record in this document. The product is a new implementation.

## Product boundary

Kubetrol is a local, keyboard-driven Kubernetes terminal application. It also
runs inside a terminal reached over SSH. There is no application server,
database, hosted control plane, telemetry service, or Textual Web deployment.
The later documentation website is separate from the product.

The initial operating systems are Linux and macOS. Python source installations
target CPython 3.12, 3.13, and 3.14. See distribution.md for qualification rules.

## Chosen stack

| Concern | Decision |
| --- | --- |
| Interface | Textual, with its built-in DataTable, screens, workers, themes, and Pilot tests |
| Kubernetes API | kubernetes_asyncio behind a narrow application-owned adapter |
| Interactive exec and editor handoff | Explicit kubectl/editor subprocesses with Textual suspension |
| Port forwarding | Managed kubectl subprocess with an owned lifecycle |
| Python packaging | src layout, Hatchling, pyproject.toml, uv and a committed uv.lock |
| CLI entry point | Standard-library argparse; command and import package named kubetrol |
| Configuration | Versioned YAML schema, validated dataclasses, platformdirs paths |
| Verification | pytest, pytest-asyncio, pytest-cov/coverage.py, Ruff, strict mypy |
| Local regex filters | regex VERSION1 with a total match timeout, owned background work and stale-result guards |
| Cluster integration | Disposable kind clusters and a controllable fake API server |

uv manages development environments, locked dependency resolution, and build
invocation. Hatchling is the configured build backend that produces wheels and
source distributions; `uv build` delegates to it. This retains standard Python
packaging and the Hatchling approach shown in Textual's packaging guide without
requiring contributors to manage two environment tools.

B03 adds `regex` for local filtering because matching supports an actual timeout
and releases the GIL for immutable strings. A thread alone cannot stop an
unbounded standard-library regex match. Queries remain bounded and matching uses
a total 50 ms budget per snapshot; cancellation drains the worker before exit.
This does not establish the separate maximum-workload performance gate.
See [filter semantics](command-navigation.md) and the
[engine's timeout/threading documentation](https://pypi.org/project/regex/).

The generated async client is selected for explicit API coverage and control
over watches and cancellation. Do not mix clients throughout the UI or rely on
the development branch of an unreleased client. Pin a released compatible
dependency set during bootstrap; uv.lock is the development/test resolution.
An alternative client requires a demonstrated gap and a decision update.

## Why Python and Textual

This is a product decision, not a promise that every upstream behavior is supplied
by the UI framework. Textual supplies widgets, layout, reactive UI, workers and
test tooling; Kubetrol must implement Kubernetes semantics, streaming, permissions,
plugins and release engineering. Terminal suspension supports the chosen shell
handoff design. Pilot tests are complemented by real PTY tests.

| Option | Fit and tradeoff |
| --- | --- |
| Python + Textual | Chosen: strong fit for Python contributors and a rich terminal UI; requires careful async lifecycle, bounded rendering and platform packaging |
| Python + prompt_toolkit | Strong for interactive command editing; more application-specific work for a full resource browser |
| Python + curses/urwid | Viable, but more layout/state/test infrastructure to assemble for this product |
| Go + tview or Bubble Tea | Strong alternative if native distribution and direct client-go behavior become dominant; changes the project's Python contribution model |
| Rust + Ratatui | Strong performance/control option; higher implementation effort for this team's stated Python preference |

The early delivery gates must demonstrate credential compatibility, real-terminal
exec, and watch correctness before the UI expands. Performance measurements and
clean-machine installations determine whether the implementation is viable. If a
concrete gap cannot be solved in the adapter, record evidence and revisit the
client or language decision rather than hiding the limitation.

## Authentication and delegated tools

Treat kubeconfig as trusted local configuration: its exec credential helpers can
run local code. Never fetch and execute a kubeconfig from a cluster resource.
EKS uses the configured AWS exec helper; AKS uses the configured Azure kubelogin
helper. Honor expiration and interactive behavior, and distinguish authentication
failure from API authorization. Qualification tasks cover the Python SDK's gaps
relative to client-go; using the SDK alone is not proof of compatibility.

Build an effective per-session connection specification from file/environment/CLI
precedence. Both SDK calls and delegated kubectl/Helm commands must use it,
including impersonation, proxy and TLS overrides. When a temporary kubeconfig is
needed, use restrictive permissions, do not log it, and clean it up. Never fall
back silently to another context or user. See [CLI contract](k9s-cli.md).

## Dependency direction

```text
CLI -> Textual UI -> application services -> Kubernetes/process adapters
                         |                          |
                         v                          v
                  domain state/models       API and process events
                         ^                          |
                         +--------------------------+
```

Use src/kubetrol/{ui,services,domain,adapters,config}, with tests grouped into
unit, contract, ui, integration, terminal, and packaging. Keep this structure
small initially; create modules when real behavior needs them.

Domain code imports neither Textual nor generated SDK models. Normalize SDK
responses to application-owned resource snapshots. Preserve Kubernetes field
names when retaining raw manifests, and use separate derived display values.

## Cluster sessions and watches

Each context has an explicit client configuration, session generation, task
owner, resource store, and cleanup path. Do not mutate process-global client
configuration or the user's current kubeconfig context.

LIST returns an initial snapshot and collection resourceVersion. WATCH starts
from that version. Handle ADDED, MODIFIED, DELETED, BOOKMARK, timeout, EOF,
expired versions (410 with relist), retryable failures with bounded exponential
backoff/jitter, and non-retryable permission failures. Follow pagination without
losing the collection's consistent snapshot. Resource versions are opaque.

Switching context or scope cancels and awaits old tasks, closes streams, and
rejects late results using the captured session generation. Show stale or
disconnected state explicitly. Do not turn permission or transport failures into
empty resource lists. Watch only resources needed for active views and bounded
background features.

## Terminal behavior

B01 implements `ui/app.py` as the disconnected Textual workspace and
`ui/launch.py` as its synchronous CLI/TTY boundary. Settings and an owned
diagnostic logger are injected; no Kubernetes configuration or client is loaded.
Packaged TCSS styles resolve relative to the application module, including in
installed wheels. Shortcut focus changes use the public `App.set_focus` API
immediately, with priority bindings disabled inside inputs, so the next queued
key reaches the selected input even when the terminal batches keystrokes.

Textual 8.x's default fatal-error display includes exception values, source and
locals. Two narrowly scoped private overrides preserve its exception handling,
test propagation and terminal cleanup while routing errors to the sanitized
logger and suppressing raw console tracebacks. The launcher reports an owned
message/exit code. Pilot and real PTY failure tests qualify this boundary; each
Textual upgrade must recheck those hooks against the pinned implementation.
There are no custom background tasks or blocking I/O in B01 event handlers.

Use stable resource identity (context, group/resource, namespace, UID); derive
row order separately. Preserve selection and scroll position while applying
batched incremental updates. Sort quantities and timestamps by typed values.
Respect focus, terminal resize, narrow screens, Unicode width, and plain-color
fallbacks. Key hints must reflect actions actually available in the current view.

Keep normal UI event handlers free of blocking I/O. Capture the target context,
namespace, resource, and container before starting an action. Each stream or
process has a lifecycle owner. Log storage and render queues have bounded
capacity; implement explicit overflow and backpressure behavior.

For an interactive shell, suspend Textual and hand the real terminal to kubectl
with an argument vector, explicit kubeconfig/context, namespace, and container.
Restore the terminal on normal exit, failure, Ctrl-C, and exceptions. A fully
embedded terminal emulator is outside the initial scope; the supported shell
experience is full-terminal handoff and return.

## Actions, configuration, and trust

Mutations go through services that capture identity, enforce read-only mode,
present the target and consequences, handle permissions/conflicts, and return a
typed outcome. Never retry an uncertain non-idempotent mutation blindly.

Configuration has a schema version, validated defaults, atomic writes, unknown
field handling, and migration tests. Secrets are hidden in ordinary views and
redacted from exports and diagnostics. Escaping resource markup and terminal
controls is separate from Kubernetes authorization.

F03 implements a flat schema-v1 dataclass for theme, refresh, read-only and
diagnostic settings. Its bounded safe YAML loader rejects duplicate/nonstring
keys and aliases, retains unknown fields, and migrates v0 names in memory.
Global file/environment/CLI precedence is explicit; context-specific overrides
arrive with the context implementation. Atomic writes never happen on load.
The owned rotating logger uses private files, a process lock, credential
redaction and bounded records; debug traceback values/source/locals are omitted.
CLI diagnostics use an allowlist and never load Kubernetes credentials or run auth helpers.
See [configuration](configuration.md) for the implemented contract and exit codes.
Startup filesystem work runs before Textual; future UI reads/writes must use
an owned worker rather than blocking a normal event handler.

Plugins are trusted local executables declared by users. Resolve bindings and
resource scope before invocation, pass selected-resource context deliberately,
and own foreground/background process cleanup. Never auto-discover executable
plugins from a cluster response or the current working directory.

F04 adds literal bounded Rich text, shared control escaping, immutable argv and
client/UID target snapshots. Diagnostic redaction uses the shared control helper.
Per-client UUIDs distinguish even reopened contexts with the same name/generation.
These helpers do not authorize writes or make a local staleness check atomic:
future services must enforce read-only policy, bind the captured client and use
appropriate API preconditions. Tests trap ambient SDK loaders and permit only a
qualified owned loopback fixture. See [security integration contracts](security-primitives.md)
and the [focused threat model](kubetrol-threat-model.md).

The maintainer validated the K9s-style local execution model for F04 on
2026-10-04: configured authentication helpers may run automatically for login
and credential renewal; ordinary plugins require operator invocation. Both
run with the launching user's privileges, without an application sandbox.
Provider interaction, process ownership and read-only enforcement remain
separate implementation/qualification requirements in their existing issues.

F05 stage 1 registers the audited CLI contract while retaining explicit
unavailable gates in `config/launch.py` for absent transport/export/theme behavior.
Gates run before filesystem work or authentication. A frozen `AccessPolicy` and
`CommandService` in `services/` are shared by initial CLI and interactive command
resolution; unknown typed actions fail closed. Future effectful services must use
this guard before their adapters. This stage does not prove API/RBAC enforcement
for operations that do not exist yet, and F05 remains open pending integrations.
Session-only `ui/presentation.py` controls widget visibility, independent of
settings/policy. Read-only status survives hidden headers and input updates.
Refresh can be validated by local diagnostics but explicit UI use fails until
live synchronization exists. See the [current CLI contract](k9s-cli.md).

## C01 session adapter decision

`config/catalog.py` owns bounded read-only kubeconfig merge/provenance.
`domain/connections.py` defines validated requests and safe state observations.
`services/sessions.py` owns client replacement, generations and namespace scope;
`adapters/kubernetes.py` owns explicit SDK configurations/private TLS material;
`adapters/credentials.py` owns noninteractive bounded exec-token processes/cache.
`ui/scopes.py` and the app render these contracts without SDK models.

The pinned SDK's default loader can run helpers with unbounded sequential pipe
reads, log raw helper errors, refresh/persist provider configuration and use
process-global defaults. C01 constructs explicit configurations without those
loaders. Its namespace adapter uses the SDK-created TLS connector and API-owned
pool with bounded streaming reads, disabled redirects/decompression and explicit
proxy configuration. It replaces the pool before requests to disable ambient
netrc/proxy identity, using a narrow SDK `rest_client.pool_manager` boundary.
Transport tests qualify this boundary and must be rerun on SDK upgrades.
Generic exec tokens are implemented; interactive provider login and exec
certificate rotation remain explicitly unavailable for C08 qualification.

The UI owns its connection task chain. Context replacement cancels/awaits the
previous task before opening the next client, rejects late observations and
awaits final session cleanup on unmount. File preparation runs in an owned
shielded thread task: cancellation waits for it before deleting TLS files.
See [supported behavior and bounds](context-sessions.md).

## C02 discovery and snapshot decision

`domain/resources.py` contains validated discovery descriptors, scoped endpoint
construction, alias resolution and immutable typed metadata/raw manifest records.
`services/resources.py` negotiates modern/legacy discovery and reads complete
atomic, version-consistent collections using an existing explicit session.
`adapters/kubernetes.py` shares its authenticated, bounded read-only JSON transport
between namespace and resource discovery. Owned JSON-decoding tasks are awaited
even on cancellation; HTTP failures expose safe status codes without server bodies.

Partial discovery is explicit, list errors never become successful empty rows,
and expired pagination restarts the entire snapshot once. Optional UID/version
values on non-watch aggregate APIs remain absent rather than fabricated. This
backend does not start UI workers or live watches; C03/C04/B02 integrate those
behaviors. See [resource discovery](resource-discovery.md) for the contract and limits.

## C03 synchronization decision

`domain/watches.py` owns event/Status normalization, UID-indexed state, bounded
replay memory and pure retry decisions. `services/watches.py` owns an awaited
list/watch loop and its explicit sink, response closure, cancellation and retry
timing. The adapter shares authentication/TLS requests between bounded JSON reads
and watches. It yields complete JSON lines without a producer queue; owned
decoding and normalization workers are awaited on cancellation.

EOF/transient failures resume the last fully applied opaque version. Expiration
invalidates the cache and relists; permission/protocol failures stop. Slow sinks
apply backpressure and consumer failures propagate. Context-generation routing,
UI subscriptions and batched presentation remain C04/B02. See the implemented
[resource synchronization contract](resource-watches.md).

Preview correction #107 separates ordinary request/header deadlines from watch
body lifetime. Server expiry happens before the bounded client lifetime; no
bookmark traffic is assumed. Clean EOF after a healthy established interval
renews the checkpoint while keeping LIVE. Immediate EOF/transport failures keep
stale/retry behavior; only an established healthy stream resets prior failures.
The interval starts after headers, so failed slow establishment cannot mask outages.

## C04 active-view ownership decision

`domain/views.py` owns immutable view observations and pure generation/freshness
decisions. `services/workspace.py` connects explicit sessions, per-client discovery,
one active watch and bounded latest-state subscriptions. Selection invalidates
snapshots immediately, coalesces intent, cancels once and awaits obsolete work.
Captured client/session/scope and revision reject late results/errors. Published
problems copy safe fields without transport traceback/client references.

The Textual app subscribes on mount, checks current revisions and updates status
on the event loop. Unmount awaits watch/transition/client/subscription cleanup.
Pod counts and stale/failed states are visible; rendering rows, sort/cursor
preservation and commands remain B02/B03. See [active resource views](resource-views.md).

## Sources

- [Textual workers](https://textual.textualize.io/guide/workers/)
- [Textual focus API](https://textual.textualize.io/api/app/#textual.app.App.set_focus)
- [Textual app suspension](https://textual.textualize.io/api/app/#textual.app.App.suspend)
- [Textual packaging with Hatch](https://textual.textualize.io/how-to/package-with-hatch/)
- [uv build backends](https://docs.astral.sh/uv/concepts/build-backend/)
- [Kubernetes API concepts](https://kubernetes.io/docs/reference/using-api/api-concepts/)
- [kubernetes_asyncio](https://github.com/tomplus/kubernetes_asyncio)

- [AWS EKS kubeconfig and authentication](https://docs.aws.amazon.com/eks/latest/userguide/create-kubeconfig.html)
- [AKS kubelogin authentication](https://learn.microsoft.com/en-us/azure/aks/kubelogin-authentication)
- [Bubble Tea](https://github.com/charmbracelet/bubbletea)
- [Ratatui](https://ratatui.rs/)

## B04 resource inspection

`domain/inspection.py` produces bounded redacted plain-text documents and literal
search coordinates without SDK or Textual types. `services/inspection.py` captures
an explicit client/API descriptor/target, verifies the individual GET's UID and
name, reads bounded UID-associated core/v1 events, and drains owned serialization
work on cancellation. `ui/inspection.py` owns the read task and read-only TextArea
modal, preserving the underlying table while rejecting invalidated targets.
See [ordinary-view policy and controls](resource-inspection.md).

## S01 log transport

`domain/logs.py` validates query options and frames/redacts bounded UTF-8 lines
with consumer-owned retention. The adapter opens a scoped `text/plain` stream
with bounded headers and an explicit indefinite quiet-follow body. `services/logs.py`
verifies captured pod UID/container before and after opening, awaits each consumer
and closes its generator on cancellation/failure. Logs have no watch checkpoints
and are never automatically replayed. UI ownership/presentation follow in S02.
See [the transport contract](container-log-transport.md).
