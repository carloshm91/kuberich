# Contributing

KubeRich is an independent Apache-2.0-licensed Python project. Contributions, bug
reports, and practical terminal UX feedback are welcome.

Contributors retain copyright in their own contributions. Unless explicitly
agreed otherwise, contributions submitted for inclusion are under Apache-2.0;
the DCO sign-off below certifies your right to contribute. See
[licensing and attribution](docs/licensing.md).

## One issue at a time

1. Choose an unblocked task from the earliest unfinished product milestone in
   [the backlog](docs/backlog.md). Read its parent epic and acceptance criteria.
2. Assign the task when starting and move its project card to In Progress.
   Maintainer implementation work has a work-in-progress limit of one task.
   Epics group work; they are not implementation branches.
3. Branch from an up-to-date main: feat/<issue>-<slug>, fix/<issue>-<slug>, or
   docs/<issue>-<slug>. Keep the branch focused on that task.
4. Implement the behavior with relevant tests and user-facing documentation.
   Small prerequisite corrections belong in the same PR only if needed for it.
   Record newly discovered independent work as a separate issue. For user-facing
   behavior, update its authored guide and capability limits in the same PR;
   [website source enrollment](website/README.md#keep-documentation-current-in-each-product-pr)
   explains the automatic CLI/resource references and two-surface docs build.
5. Open a pull request with “Closes #<issue>” when all criteria are complete
   (otherwise “Refs #<issue>” and keep remaining criteria open), acceptance evidence, test results,
   and screenshots or a terminal recording when the visible interaction changes.
6. Merge with squash only after the required checks pass and review is resolved.
   Delete the branch, close the issue, and update the project card.

For the initial solo-maintainer phase, a PR and passing checks are required;
a second person's approval is not mandatory. A contributor cannot be expected
to approve their own PR. Add mandatory independent review when another active
maintainer is available.

While the documented account quota/billing restriction blocks hosted Actions,
the maintainer has authorized merges backed by measured local checks. Follow
the [temporary verification workflow](docs/quality.md#temporary-private-development-workflow-when-actions-is-unavailable),
record unavailable platform checks honestly, and retain the full public-release
qualification requirement.

GitHub issues and project status are the live record. The checked-in backlog
captures scope and dependencies; update it when the plan changes materially.

## Definition of ready

- The issue has an outcome, scope, acceptance criteria, verification plan,
  priority, release milestone, and parent epic.
- Blocking dependencies are closed or the issue explicitly has independent scope.
- Any needed account or release permission is identified before work starts.

## Definition of done

- Acceptance behavior works, including relevant failure and cancellation paths.
- Ruff, formatting, strict mypy, tests, and required package checks pass.
- Line and branch coverage each meet 90%; changed lines meet 90%; critical
  deterministic modules meet 100%, as defined in [quality policy](docs/quality.md).
- UI changes include headless behavior tests and relevant real-terminal evidence.
- Kubernetes changes include fake-API tests and disposable-cluster verification.
- Documentation and changelog entries describe the resulting user behavior.
- No placeholder behavior, suppressed required failures, leaked tasks/processes,
  secrets, or undocumented new runtime prerequisites remain.

Documentation-only changes run documentation/repository checks; application
coverage is not fabricated for a repository without application code.

## Toolchain

The development package uses a src layout, pyproject.toml, a committed uv.lock,
and the following commands. Python 3.12 through 3.14 is the qualified range:

```sh
uv sync --locked --group dev
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict src/kuberich scripts/check_coverage.py scripts/check_quality_gate.py
uv run pytest --cov=kuberich --cov-branch --cov-report=xml --cov-report=json
uv run python scripts/check_coverage.py coverage.json
uv run diff-cover coverage.xml --compare-branch origin/main --fail-under 90 --total-percent-float
uv build
uv run twine check dist/*
```

The packaging tests check complete wheel/source contents and rebuild equivalence,
then run installed entry points in fresh virtual environments and real isolated
uv tool/pipx installations outside the checkout. pipx comes from the locked dev
group. They require uv on PATH and package-index access for dependencies; tool
state/configuration is confined to owned temporary directories. Installed CLI
help/version require no cluster. Real UI checks use owned APIs and PTYs.

The coverage script independently checks lines and branches, the complete
production inventory, and the maintained critical-module list. diff-cover checks
changed executable lines against the merge base; fetch the current base branch
before running it. Its local invocation includes staged and unstaged edits;
CI compares committed code against the exact event base. A diff with no changed
executable production lines is not applicable, not a new 100% coverage result.
See [quality policy](docs/quality.md) for the required check names and the current
private-repository branch-protection limitation.

Every PR runs Linux on Python 3.12/3.13/3.14 and the macOS/Python 3.12 baseline.
Main pushes repeat Linux; manual Application quality dispatches on main qualify
all six combinations before release. Every selected environment retains the full
suite and independent coverage gates. Do not use a manual dispatch as a substitute
for PR checks or a routine development matrix as release qualification.

## Commits and releases

Use Conventional Commit PR titles: feat, fix, perf, refactor, test, docs, build,
ci, or chore, with an optional scope. Mark incompatible changes with ! and
explain the migration. The squash commit follows the PR title.

Sign off your own commits with `git commit -s` using your contributor identity.
The repository has a DCO check; a sign-off certifies the contribution under the
[Developer Certificate of Origin](https://developercertificate.org/). This is a
commit trailer, separate from cryptographic commit signing. Preserve the trailer
in the squash commit and do not sign off on behalf of another contributor.

Version changes happen in release PRs. Patches repair behavior; minor versions
add capabilities. The first public product is 1.0.0; intermediate 0.x labels are engineering
checkpoints and are not published. Incompatible public changes require a major
version and migration notes. See [the exact release procedure](docs/releases.md).

## Safety and attribution

Use disposable test clusters and sanitized fixtures. Do not commit kubeconfigs,
tokens, real secret values, terminal recordings containing credentials, or
cluster-specific private data. Report vulnerabilities via [SECURITY.md](SECURITY.md).

Prefer original implementation and documented public APIs. Any copied third-party
code requires compatible licensing, attribution, and a recorded source.
