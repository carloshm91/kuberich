# Current preview

KubeRich's first release candidate is **0.1.0**. It is under validation;
there is no published tag, PyPI package, public Homebrew tap or final website
deployment yet. The existing development website retains its earlier deployment.
The [installation guide](installation.md) distinguishes trusted local builds
from the public channels that still require activation.

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
The [guided workflow](everyday-workflow.md) describes the current controls,
and the [release phases](releases.md) explain what belongs to each version.

## Current validation

The website and documentation contain fictional examples and actual application
renders from owned fixtures. Both generated surfaces passed checks across
57 pages, including desktop/mobile navigation, accessibility and local links.
The preceding frozen candidate passed Python 3.13/3.14, all four native archives
and all three Homebrew installation/upgrade/uninstall hosts.
Three local rounds also passed all thirteen owned-cluster scenarios per round.

That candidate failed two checks: a macOS cancellation test raced its
deliberately short connection deadline, and a Linux aggregate-log fixture did
not observe the required waiting-container snapshot. The corrections pass
95 focused cases and an actual owned-cluster aggregate trial locally.
Fresh frozen platform checks remain required before publication review.
The successful earlier checks do not qualify the corrected candidate.

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
