# D01 #34 distribution qualification

This task prepares local wheel/source artifacts and verifies actual installations.
It publishes no package, tag, release, Homebrew tap or website and changes no
repository visibility. Installed version remains `0.0.1.dev0`.

| Acceptance behavior | Verification |
| --- | --- |
| Complete runtime assets and metadata/license/version | `tests/packaging/test_artifacts.py`, whole archive payload and metadata assertions |
| No tests, development scripts, caches or undeclared private files | Same suite; actual synthetic file traps in a copied build tree |
| Rebuild from sdist | Same suite; identical wheel member payloads |
| Real uv tool and pipx install of wheel and sdist | `tests/packaging/test_installers.py`, independent pip backend for pipx |
| Exposed PATH command and module origin outside checkout | Same suite, actual installed CLI plus isolated `python -I` probe |
| Actual installed UI navigation/shell and terminal restoration | Same suite plus existing `tests/packaging/test_distribution.py` |
| Uninstall and installer timeout cleanup | Actual managed uninstall, process-group timeout and child reaping |

Exact commands and local content policy are in
[distribution](../distribution.md). All installers use owned temporary tool,
binary, cache/configuration directories and an explicit matrix interpreter.
Synthetic APIs and fake kubectl fixtures qualify local behavior, not a real
cloud-provider environment.

## Measured qualification: 2026-10-07

All required local checks exited successfully on frozen candidate
`c5ad4dc1084270e23ac587788f6fb263c72100cd`, against base
`7bb6b8e0d3bb7fe0bc967f610cd37cd4ac9404ec`. Final documentation-only changes
preserve its source/tests/scripts/workflow trees and artifact input files.

| CPython | Passing tests | Production lines | Production branches | Changed production lines |
| --- | --- | --- | --- | --- |
| 3.12.12 | 2,009 | 6419/6451 (99.50%) | 1891/1936 (97.68%) | N/A (0 changed executable lines) |
| 3.13.12 | 2,009 | 6419/6451 (99.50%) | 1891/1936 (97.68%) | N/A (0 changed executable lines) |
| 3.14.3 | 2,009 | 6312/6344 (99.50%) | 1891/1936 (97.68%) | N/A (0 changed executable lines) |

Each minor independently passed all 29 critical modules at 100% line/branch
coverage, Ruff lint/format, strict application/gate/provider-verifier typing,
plan validation, coverage gates, wheel/source build and Twine metadata checks.
Each retained 59 actual UI SVGs, 140 terminal summaries/ANSI records and four
installation records. The whole packaging preflight also passed 46 tests on
Python 3.12; final full matrices include those checks with their final fixtures.

The Linux x86_64 host used kernel 6.8.0-142-generic/glibc 2.39, uv 0.10.4,
pipx 1.17.11, Hatchling 1.32.4, OpenSSH 9.6p1 and tmux 3.4. Complete test runtimes
were 1068.15 seconds (3.12), 830.99 seconds (3.13) and 705.19 seconds (3.14).
The 30-minute hosted job bound accommodates this measured suite, cold installs
and the required cluster checks; it does not promise hosted execution speed.

## Artifact and installation identity

The tested wheel contains 80 regular files and has SHA-256
`66efc09eab7d9f9d0b2a00eb87bee9f690179db415955a139c2acbd959df78e0`.
The tested source archive contains 81 regular files and has SHA-256
`b9c6d9fe125826cee2ce672386259fd753e06215fb45a9248e811bc9b9c3c361`.
All three interpreter builds and both managers installed identical bytes per
format. Source-to-wheel rebuild tests compare every member payload. The source
archive includes Hatchling's required `.gitignore`, which the backend includes
automatically; it does not include development tests/scripts/lock.

Twelve managed installations passed: wheel/source × uv tool/pip-backed pipx ×
three interpreter minors. Probes verify installed module origin, interpreter,
metadata, typing/CSS, CLI exposure from PATH, missing-config/non-TTY errors,
actual owned-API navigation, wheel-installed shells and uninstall cleanup.
An actual timeout case verifies child process-group cleanup. The synthetic
private-file trap fails under the pinned baseline build policy and passes under
the corrected policy; negative evidence is kept separately from successful gates.

Fresh installs resolved Textual 8.2.8, kubernetes-asyncio 36.1.0, Pyte 0.8.2,
aiohttp 3.14.4, platformdirs 4.12.3, PyYAML 6.0.3 and regex 2026.9.29 on all
three interpreters. The development lock uses aiohttp 3.13.3. These measured
fresh-install resolutions qualify the tested package; a dependency range does
not promise that future index resolutions will return identical versions.

## Actual installed Kubernetes trial

An additional fresh uv tool installation of the same wheel passed the maintained
owned-kind harness with every observed CLI child launched from its installed
Python. The parent harness uses the matching source tree. The isolated interpreter
probe confirms the CLI module comes from that installation, and cleanup removes
its managed environment and exposed binary.

kind 0.33.0 / Kubernetes 1.36.4 / kubectl 1.36.4 passed two-container exec,
configured/missing shells, fullscreen vi, resize/Ctrl+C/repeated return,
TLS/alias/impersonation overrides, captured identity and actual RBAC denial.
Synthetic provider refresh/delegated reads also passed; actual EKS/AKS remain
unqualified. Nine actual terminal records accompany this report. The owned
cluster was deleted and the previous cluster inventory was preserved.

## Exact qualification commands

For each explicit minor in separate worktrees/owned temporary directories:

```sh
uv sync --locked --group dev --python 3.12
uv run --locked --python 3.12 ruff check .
uv run --locked --python 3.12 ruff format --check .
uv run --locked --python 3.12 mypy --strict src/kubetrol scripts/check_coverage.py scripts/check_quality_gate.py
MYPYPATH=src uv run --locked --python 3.12 mypy --strict --explicit-package-bases -m scripts.verify_aks_auth -m scripts.verify_eks_auth
uv run --locked --python 3.12 python scripts/validate_plan.py
uv run --locked --python 3.12 pytest -x --basetemp /tmp/kubetrol-34-evidence/full-3.12 --cov=kubetrol --cov-branch --cov-report=term-missing --cov-report=xml --cov-report=json
uv run --locked --python 3.12 python scripts/check_coverage.py coverage.json
uv run --locked --python 3.12 diff-cover coverage.xml --compare-branch origin/main --fail-under 90 --total-percent-float --format json:diff-coverage.json
uv build --python 3.12
uv run --locked --python 3.12 twine check dist/*
```

The same commands used 3.13 and 3.14. The installed-kind driver was executed as:

```sh
uv run --locked --python 3.12 python -c "import runpy; runpy.run_path('/tmp/kubetrol-34-evidence/installed_kind.py', run_name='__main__')"
```

Raw logs, coverage, candidate inputs, built bytes, installer versions/resolutions,
negative-control evidence, the complete local driver, cluster report and terminal
records are retained under `/tmp/kubetrol-34-evidence`.

## Remaining platform/publication limits

DCO succeeds on signed-off authored commits. Hosted application, Repository and
Quality gate jobs cannot start because of the billing/spending restriction. The
maintainer-authorized local workflow applies. Linux x86_64 results do not certify
macOS/arm64 or public installation channels; the release gate #40 must qualify
or explicitly narrow its advertised platform matrix. PyPI/Homebrew publication,
protected-main enforcement and release version/tag remain separate tasks.
