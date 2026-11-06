# Contributing

KubeRich is an independent Apache-2.0 Python project. Contributions, bug reports
and terminal workflow feedback are welcome. You retain copyright in your work;
contributions use Apache-2.0 unless agreed otherwise. See
[licensing and attribution](docs/licensing.md).

## Delivery contract

### Definition of ready

Choose an unblocked issue in the earliest unfinished [milestone](docs/backlog.md).
Read its outcome, scope, acceptance criteria, dependencies and verification plan.
Identify any missing access or publication authorization before dependent work.
GitHub is the live task status; the checked-in backlog is the planning map.

### Definition of done

- Implement observable behavior, including relevant failure and cancellation paths.
- Pass Ruff, formatting, strict types, behavioral tests and applicable package checks.
- Meet 90% line, 90% branch and 90% changed-line coverage; critical modules require
  100%. The [quality policy](docs/quality.md) defines inventories and measurement.
- Include relevant headless/real-terminal UI tests and disposable-cluster API tests.
- Update user guidance, capability limits, acceptance evidence and the changelog.
- Leave no placeholder behavior, suppressed required failure, leaked work or secret.

Documentation changes use relevant repository/site checks; they do not invent an
application coverage result. Coverage does not establish correct Kubernetes
behavior, cleanup, terminal restoration or installation by itself.

## One issue at a time

1. Assign a ready issue and keep its project status current. Keep ONE implementation issue globally;
   coordinate agent ownership within that issue.
2. Branch from current main: `feat/<issue>-<slug>`, `fix/<issue>-<slug>` or
   `docs/<issue>-<slug>`. Keep independent discoveries in separate issues.
3. Implement and verify the acceptance behavior. For user changes, update the
   authored guide and relevant generated references in the same PR. See
   [source enrollment](website/README.md#keep-documentation-current-in-each-product-pr).
4. Open an issue-linked PR: `Closes #<issue>` only when all criteria are complete;
   otherwise use `Refs #<issue>`. Include actual results and useful UI evidence.
5. Resolve review and pass required checks before squash merging. Preserve the
   sign-off, retire the issue branch, close the issue and update the project.
   Do not bypass protection.

A sole maintainer can deliver without a second reviewer when branch rules permit.
The maintainer's authorized autonomous workflow does not require intermediate
manual trials. Existing publication boundaries still apply.

## Architecture

Read the [architecture overview](docs/architecture.md) for layers, data flow,
concurrency, cleanup and security. Use the [decision index](docs/adr/README.md)
and its template when changing a boundary. Keep domain logic independent of
Textual, clients per context, and asynchronous tasks/processes under clear owners.

## Toolchain

Use Python 3.12–3.14, a src layout and the committed `uv.lock`.
Before source-history checks or local qualification, explicitly fetch the existing
histories from the canonical repository, including when `origin` is your fork:

```sh
git fetch --no-tags https://github.com/carloshm91/kuberich.git refs/pull/277/head refs/pull/290/head
```

This changes no remote configuration. Validators stay offline and fail closed.
Use focused tests during development. Before running the complete qualification,
stage new files and create a signed-off implementation commit with `git commit -s`.
The runtime inventory uses tracked paths, and application-image capture requires
clean committed source. Keep that candidate unchanged throughout measurement;
test artifacts belong in the ignored output directories.
For the full current strict-target, private-access, startup and coverage stages,
use `uv run python scripts/qualify.py 0.3.0`; see [phase verification](docs/releases.md#reproduce-phase-verification).
The individual tools include:

```sh
uv sync --locked --group dev
uv run pytest tests/unit tests/contract tests/ui -m fast -n 12
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check_private_access.py
uv run mypy --strict src/kuberich scripts/check_coverage.py scripts/check_quality_gate.py
uv run pytest --cov=kuberich --cov-branch --cov-report=xml --cov-report=json
uv run python -m scripts.merge_runtime_coverage
uv run python scripts/check_coverage.py coverage.json
uv run diff-cover coverage.xml --compare-branch origin/main --fail-under 90 --total-percent-float
uv build
uv run twine check dist/*
```

Use fewer workers on smaller hosts. Fast tests give early feedback; the complete
selected suite and independent coverage gates remain required. See
[test layers](docs/quality.md#test-layers-and-local-parallel-runs) and
[parallel parts](docs/quality.md#parallel-test-parts) for isolation and commands.
Fetch the base before checking changed lines; no changed production code means
not applicable, rather than a new 100% result.

Package checks rebuild artifacts and install them outside the checkout through
fresh environments and isolated uv/pipx tool directories. They need uv, the
locked pipx tool and package-index access. Installed help/version need no cluster.
See [quality policy](docs/quality.md) for current runners, protected checks,
startup/runtime controls and full release qualification. Preserve original failed
logs; an unchanged retry that passes does not establish a correction.

## Commits and releases

Use Conventional Commit PR titles (`feat`, `fix`, `perf`, `refactor`, `test`,
`docs`, `build`, `ci`, `chore`). Mark incompatible changes with `!` and describe
migration. The squash commit follows the final PR title and scope.

Sign off your commits with `git commit -s` using your contributor identity; do
not sign for another contributor. The [DCO](https://developercertificate.org/)
trailer certifies your right to contribute and is separate from cryptographic
signing. Preserve it when squash merging.

Change versions only in release PRs. Patches repair behavior; minors follow the
reviewed cumulative 0.x plan. Incompatible 0.x changes need a reviewed minor and
migration notes; 1.0 introduces stable contracts. Write concise user changes using
[the note template](docs/release-notes/TEMPLATE.md). Follow the
[release procedure](docs/releases.md) for exact source, tags, packages and channels.
Publishing artifacts, websites or DNS changes needs the relevant authorization;
a prepared candidate is not permission to publish it.

## Safety and attribution

Use synthetic examples, disposable clusters and private temporary files. Never
automate tests against a user's active context or commit kubeconfigs, tokens,
Secret values or recordings with customer data. External helpers use explicit
argument vectors and selected scope; display and logs must hide credentials and
escape hostile terminal content. Own and drain every stream, task and process.

Real cloud/provider trials remain deferred to the maintainer's opt-in installed
preview tests; local contracts and disposable-cluster behavior are verified now.

Report vulnerabilities privately through [SECURITY.md](SECURITY.md). Use original
code and documented APIs; copied third-party code needs compatible licensing,
attribution and a recorded source. K9s is design inspiration, not a source tree.

Current source limits and measured evidence are in the
[maintained checkpoint](docs/internal/first-preview-current.md),
[guide acceptance](docs/internal/acceptance/task-guides.md) and
[architecture acceptance](docs/internal/acceptance/architecture-overview.md).
