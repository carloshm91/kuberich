# Working on KubeRich

Read the selected GitHub issue, CONTRIBUTING.md, docs/architecture.md,
docs/quality.md, and the relevant release milestone before implementation.

## Current stage

This repository starts with a reviewed plan and a GitHub backlog. Product
implementation begins only after the maintainer starts the first implementation
issue. The requested model workflow is Astra for planning and GPT-6.1 Sol for
implementation; do not claim to switch models without actual environment support.

## Scope and ownership

- Build a new Python terminal application. K9s is a design inspiration, not a
  source tree to copy. Keep the README attribution short.
- Keep unrelated experiments and their history out of public documentation,
  tickets, source, and commit messages.
- Python 3.12+; initially test CPython 3.12, 3.13, and 3.14. Linux and macOS first.
- Textual Web and a hosted backend are out of scope. Prepare a simple landing
  page and initial documentation before the public launch; the expanded,
  versioned documentation website remains a separate later milestone.
- Repository: carloshm91/kuberich. SSH remote:
  git@github.com:carloshm91/kuberich.git.
- Use repository-local author email carloshm91@gmail.com for the maintainer's
  commits. Do not change global Git identity or overwrite another contributor's
  identity. Never include credentials or kubeconfig contents in commits.

## Delivery workflow

- The maintainer authorized continuous implementation, local verification
  and autonomous squash merges: finish each issue/PR and proceed to the next
  unblocked task without waiting for intermediate manual trials or feedback.
  Keep progress updates and docs/first-preview.md current, but do not ask the
  maintainer to test between tasks. They will test and provide feedback later.
- Real cloud/provider trials are deferred to the maintainer's later installed
  preview tests. Implement and verify local contracts and owned disposable-cluster
  behavior now, record limits honestly, and retain opt-in certification in Q05 #87.
  This does not authorize using the maintainer's active context for automated tests.
- On 2026-10-08 the maintainer explicitly authorized opening carloshm91/kuberich
  with Apache-2.0 in #155. This authorization covers the source repository and
  its repository issues/history, not the separate GitHub project, hosting or
  distribution channels. Do not request the same visibility permission again.
- The first public product release remains 1.0.0. Intermediate milestones are
  engineering checkpoints, not instructions to publish 0.x artifacts or tags.
- On 2026-10-09 the maintainer explicitly authorized #166 to publish the current
  development landing and initial docs to two Cloudflare Pages provider hosts,
  using the protected `release` secrets. Custom domains/DNS, `www`, packages and
  application tags remain outside this authorization. Resume the preserved
  B06 #53 implementation after this focused deployment task.
- Ask before changing repository/project visibility, publishing a website,
  creating a public distribution repository, or publishing package artifacts.
  Prepare and verify the concrete result first, then request approval for the
  publication step. Domain names are proposals until the maintainer chooses one;
  do not purchase domains or change DNS without explicit authorization.
- Notify the maintainer at each usable checkpoint in docs/first-preview.md, with
  the exact tested command and honest feature status. B01 is prioritized early.
- Keep docs/capabilities.json and the pinned source inventory traceable to issues;
  do not claim parity from planned work or an unverifiable paid feature catalog.
- Work on one implementation issue at a time. Select the first unblocked issue
  in the earliest unfinished product milestone; see docs/backlog.md.
- Use a short-lived issue branch, an issue-linked pull request, required checks,
  and squash merging. Keep main releasable.
- While hosted Actions cannot start because of the account quota/billing block,
  follow the maintainer-authorized temporary local verification workflow in
  docs/quality.md. Record real local evidence and unavailable platform checks;
  preserve coverage gates and qualify full platform CI before a public release.
- Sign off authored commits with the repository identity (`git commit -s`) and
  preserve the sign-off in squash commits; satisfy the DCO check.
- A plan, stub, or mocked demonstration does not complete a behavior issue.
- Update documentation and acceptance evidence with the implementation. Treat
  GitHub as the live status source; the checked-in backlog is the planning map.
- Create tags and publish releases only as part of an explicitly requested
  release task, following docs/releases.md. Do not bump a version for every PR.

## Engineering invariants

- Follow the architecture in docs/architecture.md. Inject a per-context client;
  avoid process-global Kubernetes configuration and singletons.
- Keep domain operations independent of Textual. Own and cancel every watch,
  log stream, subprocess, and port-forward session.
- Never block the Textual event loop with synchronous network or process waits
  during normal UI operation. Terminal handoff is an explicit exception.
- Use stable resource identity, preserve cursor/scroll state, bound log memory,
  and reject results from previous context generations.
- Pass subprocess argument vectors and explicit kubeconfig/context/namespace;
  do not interpolate resource names into shell command strings.
- Escape untrusted markup and control sequences before display. Redact secrets
  and credentials in logs, diagnostics, exports, and default views.
- Use disposable local test clusters. Do not use the user's active Kubernetes
  context for tests or mutate a real cluster without task-specific authorization.

## Verification

- Enforce at least 90% line coverage AND 90% branch coverage over all production
  code, plus 90% changed-line coverage. Target and enforce 100% for the critical
  deterministic modules described in docs/quality.md.
- Run Ruff, formatting, strict type checking, behavioral tests, and applicable
  integration/terminal/package checks. Required checks must not ignore failures.
- Coverage excludes tests, but includes unimported production modules. Do not
  add broad exclusions or meaningless tests to increase a percentage.
- Publish measured results honestly. Coverage is not a substitute for testing
  reconnects, cancellation, terminal restoration, permissions, or installations.

## Skills

Relevant optional Codex skills and reproducible installation instructions are
documented in docs/agent-setup.md. They support this workflow and do not grant
permission for unrelated publication, cluster operations, or configuration changes.
