# Q02 #33 terminal qualification

This issue qualifies real local, SSH, tmux and SSH-to-tmux behavior on Linux.
The configured macOS matrix remains unavailable under the hosted Actions billing
block. Its actual execution is required before public release in #40; physical
terminal-emulator/clipboard and broader environment certification remain #61/#87.
No manual terminal or macOS result is claimed.

| Behavior | Actual terminal verification |
| --- | --- |
| Narrow windows, resize storms, Unicode paste, focus and keyboard return | `tests/terminal/test_transports.py` workspace cases on all three transports |
| Log pause/follow, first/last, search, copying redacted text, small-window help | Same suite, actual log transport cases; host clipboard receipt is not certified |
| Standard color and NO_COLOR keyboard/rendering | Same suite, explicit standard color system on all transports |
| Native child stdin/stderr, repeated return, Ctrl+C, missing executable, SIGHUP | Same suite and `tests/terminal/test_handoff.py` |
| Embedded stdin, fullscreen application, stdout/stderr Unicode, protocol queries | Same suite and `tests/terminal/test_container_shell.py` |
| Cancel while real pod preflight is blocked, then reopen successfully | Actual CLI early-close cases on local/SSH/tmux/SSH-tmux |
| SIGTERM/SIGHUP, process reaping, termios and control restoration | `tests/terminal/test_shutdown.py`, native/embedded signal cases |
| Actual SSH connection loss during workspace/native/embedded operation | Owned-daemon connection termination with ancestry validation |
| Preserve and reattach the same workspace and embedded child through SSH-to-tmux loss | Same suite, actual detach/reattach cases |
| Installed entry points outside the checkout | `tests/packaging/test_distribution.py`, native SSH and embedded SSH/SSH-tmux |
| Revoked output ownership and live-terminal restoration errors | `tests/unit/test_terminal_lease.py`; actual SSH loss supplies end-to-end evidence |
| Same-packet malformed recovery, origin/private cursor replies, rendered buffer shrink | `tests/unit/test_terminal_model.py` plus real embedded protocol cases |
| Deferred header callback after view removal | `tests/ui/test_header_lifecycle.py`; real resized log returns over tmux/SSH-tmux |
| Older queued resize cannot override current physical dimensions | `tests/terminal/test_resize_order.py`; protocol resize storms over real local/SSH/tmux terminals |

See [terminal compatibility](../terminal-compatibility.md) for exact commands,
fixture prerequisites, supported behavior and lost-terminal limits. Remote TTY
revocation is recorded as unavailable inner termios; local termios remains
measured. Escape sequences cannot be delivered through a dead SSH connection.

## Measured qualification: 2026-10-07

All required local checks exited successfully on the frozen candidate
`8df36e70ecf8f670adbb84543bb7c16a7e7b5e38`, against base
`e0da7a4394a296c608c4e3b9fefec38aa1af9079`. Final documentation-only updates
preserve these independently verified trees:

| Tree | Git object |
| --- | --- |
| `src` | `adafc145e153014c4fc0a8f74aabd1a965d034a2` |
| `tests` | `a3092572a9e6165cc46ff466e659e1e789686a0b` |
| `scripts` | `86dde75354828566d3d0e7b1e8e4ec4226c8cf84` |
| `.github/workflows` | `b035640777db9987ef518e2507710a03100fd9ef` |

| CPython | Passing tests | Production lines | Production branches | Changed executable lines |
| --- | --- | --- | --- | --- |
| 3.12.12 | 2,000 | 6,419/6,451 (99.50%) | 1,891/1,936 (97.68%) | 145/150 (96.67%) |
| 3.13.12 | 2,000 | 6,419/6,451 (99.50%) | 1,891/1,936 (97.68%) | 145/150 (96.67%) |
| 3.14.3 | 2,000 | 6,312/6,344 (99.50%) | 1,891/1,936 (97.68%) | 145/150 (96.67%) |

Each matrix independently passed all 29 critical modules at 100% line/branch
coverage, Ruff lint/formatting, strict application/gate typing, provider-verifier
typing, plan validation, source/wheel builds and Twine metadata validation.
Each retained 59 actual UI SVGs and 134 terminal restoration summaries with
corresponding ANSI transcripts. Installed-wheel trials use fresh environments
outside the checkout; no cluster or source import fallback is permitted.

The host was Linux 6.8.0-142-generic x86_64 with glibc 2.39, OpenSSH 9.6p1,
tmux 3.4, Textual 8.2.8 and Pyte 0.8.2. The complete test runtimes were
941.43 seconds (3.12), 756.95 seconds (3.13) and 624.18 seconds (3.14).
These are test-suite measurements on a shared development host, not interactive
latency or performance certification.

The executed matrix commands were, for each explicit Python minor:

```sh
uv sync --locked --group dev --python 3.12
uv run --locked --python 3.12 ruff check .
uv run --locked --python 3.12 ruff format --check .
uv run --locked --python 3.12 mypy --strict src/kubetrol scripts/check_coverage.py scripts/check_quality_gate.py
MYPYPATH=src uv run --locked --python 3.12 mypy --strict --explicit-package-bases -m scripts.verify_aks_auth -m scripts.verify_eks_auth
uv run --locked --python 3.12 python scripts/validate_plan.py
uv run --locked --python 3.12 pytest -x --basetemp /tmp/kubetrol-33-evidence/full-3.12 --cov=kubetrol --cov-branch --cov-report=term-missing --cov-report=xml --cov-report=json
uv run --locked --python 3.12 python scripts/check_coverage.py coverage.json
uv run --locked --python 3.12 diff-cover coverage.xml --compare-branch origin/main --fail-under 90 --total-percent-float --format json:diff-coverage.json
uv build --python 3.12
uv run --locked --python 3.12 twine check dist/*
```

The same commands used 3.13 and 3.14 in separate worktrees and owned temporary
directories. Raw logs, coverage, distributions and terminal/UI evidence are
retained locally under `/tmp/kubetrol-33-evidence/py312`, `py313` and `py314`.
The PR records unavailable hosted checks rather than manufacturing green status.

## Actual Kubernetes and failing witnesses

The owned kind 0.33.0 / Kubernetes 1.36.4 / kubectl 1.36.4 check passed actual
two-container exec, configured/missing shells, fullscreen vi, keyboard/resize,
Ctrl+C, repeated return, TLS overrides, captured kubeconfig identity,
impersonation and real RBAC denial. Synthetic AWS/Azure-shaped helper refresh
and delegated actual kubectl reads also passed; this does not certify EKS/AKS.
Nine actual terminal records accompany the report. The owned cluster was deleted
and the pre-existing cluster inventory was preserved.

The cluster trial tested `bf7befff39216a54e2d6c36a33071b71ec0eaddc`; its application
and scripts trees match the final candidate exactly. The later commit changes
only the workspace test's transient-title observation.

Before correction, actual failing witnesses demonstrated external shutdown
without restoration, SSH loss changing exit 129 to 120, failed native cleanup
on a revoked TTY, a deferred header querying detached children, and an older
queued resize overriding the actual TTY. Loading the baseline emulator into
isolated negative-control tests produced four failures for same-packet malformed
recovery/private cursor replies and shrinking an already rendered buffer; the
corrected equivalents passed. Earlier failed candidates remain archived and
were not merged or counted as qualified.

The final workspace trial waits for the first asynchronous view projection,
then checks the final navigation row after a resize storm. Requiring mount's
transient `Resources` title to survive a legitimate `pods(all)[0]` update had
caused an unrelated test failure; the corrected test still exercises real
resize, Unicode input, focus and terminal restoration on all transports.

## Remaining platform limits

DCO passes on the authored/sign-off commits. Hosted Linux/macOS application jobs,
Repository checks and Quality gate cannot start under the account billing/spending
block. The maintainer-authorized local workflow applies; macOS execution remains
required before public release in #40. No physical emulator/manual clipboard,
real-cloud, full xterm or complete K9s parity result is claimed. Follow-ups
#61/#87/#123/#124 retain their separate scope.

No version bump, tag, release, publication or visibility change is part of Q02.
