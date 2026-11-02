# Working on KubeRich

Read the live issue, its milestone, CONTRIBUTING.md, docs/architecture.md and
docs/quality.md before implementation. GitHub is the live status source;
docs/internal/backlog.json records the reviewed plan and release phases.

## Scope and delivery

- Write repository content, issues, PRs and commits in English.
- Build an independent Python terminal client; K9s is inspiration, not copied source.
- Keep unrelated experiments out of public code, documentation and history.
- Python 3.12+; use the supported Python/platform matrix in docs/quality.md.
- Textual Web and a hosted backend remain outside the current product scope.
- Repository: carloshm91/kuberich; SSH: git@github.com:carloshm91/kuberich.git.
- Use repo-local carloshm91@gmail.com for maintainer commits; never change global or other contributor identity.
- Work on ONE implementation issue globally; coordinate agent ownership within that issue.
- Select the earliest unblocked milestone task; implement behavior, not a stub or plan.
- Continue authorized implementation and verified squash merges without manual-trial pauses.
- Use an issue-linked PR, required checks, resolved review and a signed-off squash commit.
- Keep main releasable; do not bypass protection, force-push or delete protected branches.
- Respect existing authorization; do not ask again for an already authorized action.
- Repository/project visibility, tags, packages, distribution repositories, hosting, domain purchases and DNS need explicit approval.
- Prepare and verify concrete artifacts before a publication approval; phase readiness is not approval.
- Follow docs/releases.md; do not bump a version for every PR or infer publication from metadata.
- Update user guidance, capability limits, relevant evidence and docs/internal/first-preview-current.md.
- Keep capability/source inventories traceable; planned work does not establish parity.
- Use synthetic examples/screenshots; never expose customer identities, real credentials or kubeconfig contents.

## Engineering

- Follow the architecture; keep domain operations independent of Textual.
- Inject clients per context; avoid global Kubernetes configuration and singletons.
- Own and cancel every watch, log stream, worker, subprocess and forwarding session.
- Never block the active UI loop with synchronous network/process waits; follow the terminal lease.
- Use stable resource identity, preserve cursor/scroll, limit memory and reject stale generations.
- Pass explicit argv/kubeconfig/context/namespace; never interpolate resource names into shell strings.
- Enforce read-only, target identity and confirmation policy at effectful service boundaries.
- Escape remote markup/control sequences and redact credentials in display, logs and exports.
- Keep temporary credential material private and clean it up through failure and cancellation.
- Use disposable owned clusters and fixtures; never automate tests against the user's active context.
- Real provider trials and real-cluster changes require explicit task authorization.
- Prefer documented ports and public APIs; keep compatibility adaptations isolated and tested.

## Verification

- Enforce at least 90% production line, 90% branch and 90% changed-line coverage.
- Enforce 100% lines/branches for the reviewed critical modules in pyproject.toml.
- Include unimported production modules; exclude tests, never hide code with blanket exclusions.
- Run Ruff, formatting, strict types, behavior and applicable terminal/package/cluster checks.
- Required failures remain failures; retain originals and report unavailable platform evidence.
- Coordinate timing windows, freeze measured inputs and use independent temporary/artifact directories.
- For 0.x, startup and runtime/collection latency is advisory; retain unmet results and original limits.
- Actual major 1+ (including prereleases) or --strict-startup enforce all startup timing limits.
- --strict-paint remains UI-only; RSS/import absence, frames, deadlines, cleanup and coverage stay hard.
- KUBERICH_STRICT_RUNTIME_BUDGETS=1 enforces runtime/collection timing; major 1+ cannot opt out.
- Keep negative latency controls strict; policy changes never relabel an original failure.
- Coverage and test counts do not guarantee correct behavior, cleanup or installation.
- Sign off authored commits with git commit -s; never sign for another contributor.
- Optional skills in docs/agent-setup.md do not grant unrelated execution or publication authority.
