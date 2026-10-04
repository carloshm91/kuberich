# Quality and coverage

Coverage is a release requirement and one part of correctness. A high percentage
does not establish correct Kubernetes semantics, responsive terminal behavior,
or reliable installation.

## Required gates

| Gate | Requirement |
| --- | --- |
| Production line coverage | At least 90%, measured independently |
| Production branch coverage | At least 90%, measured independently |
| Changed-line coverage | At least 90% against the PR merge base |
| Critical deterministic modules | 100% line and branch coverage |
| Lint and formatting | Ruff check and format check pass |
| Types | Strict mypy over application source passes |
| Behavioral tests | Applicable unit, UI, contract, and integration tests pass |
| Artifacts | Build, metadata validation, and clean-environment installation pass |
| Dependencies | No unresolved actionable high/critical vulnerability without a documented, time-bounded mitigation reviewed in the PR |

Critical modules are the context-generation/target-identity checks, mutation
guard and command construction, redaction/control-sequence handling, and the
resource-state transition/reconnect decisions. Keep those decisions separate
from transport and widget glue so exhaustive tests are practical. The critical
module list is explicit in CI and changes with code review.

Configure coverage over the entire src/kubetrol package, including modules not
imported by tests. Do not include tests in the denominator. Do not omit entire
UI, client, or subprocess modules. A combined coverage.py percentage is not the
independent line/branch gate: parse coverage JSON totals for each metric. Zero
branches are not a fabricated 100%; report them as not applicable. Empty
production source does not establish product coverage.

Use a 90% minimum changed-line gate (for example diff-cover). Exceptions for
unreachable or platform-specific lines require an explicit narrow justification;
the global line and branch floors remain unchanged. Do not add assertions that
merely mirror implementation details or blanket no-cover directives.

## Test layers

- Unit: domain rules, typed sorting, quantities, validation, redaction, command
  arguments, transition logic, and retries with a controllable clock.
- Contract: a local fake Kubernetes HTTP/WebSocket server for pagination,
  list/watch continuity, 410, 403, disconnects, malformed payloads, and cancellation.
- UI: Textual Pilot tests for navigation, focus, keybindings, selection stability,
  details, modal dismissal, resizing, and error states. Add selected snapshots
  for meaningful layouts; do not replace behavior assertions with screenshots.
- Integration: isolated kind fixtures for real API behavior, container logs,
  exec, RBAC denial, and subsequently mutations/port-forward/CRDs. Every test
  owns its context and cleanup; never fall back to the user's active context.
- Terminal: real PTY/subprocess tests for handoff, Ctrl-C, window resizing,
  terminal restoration, process exit, SSH, and tmux. Headless tests cannot prove
  terminal restoration.
- Packaging: test the built wheel, source distribution, Homebrew formula, and
  later standalone artifacts in clean environments. Check help, version, missing
  kubeconfig, bundled assets, and a disposable-cluster smoke workflow.

The fast required PR suite covers every supported Python minor on Linux and
the declared macOS baseline. Cluster, PTY, and install checks are required for
changes affecting those paths; the release gate runs the complete matrix.
Use stable check names and a required aggregate quality-gate job that cannot
pass when a required dependency fails, is cancelled, or is incorrectly skipped.

## Performance evidence

Record the runner, terminal size, Python/dependency versions, dataset, and
measurement method. The initial qualification workload is 10,000 synthetic
resource rows, 100 resource events/second, and 2,000 log lines/second with a
10,000-line retained buffer. Target p95 input response below 100 ms on the
documented reference machine and a memory plateau during a 30-minute soak.
These are acceptance targets, not claims about current performance. Investigate
failures before changing the budget; preserve comparable benchmark results.

## Current repository stage

Only planning, community files, and repository validation exist initially.
Application coverage is not applicable. F01 creates the package and F02 enables
the application quality gates before feature implementation begins. The README
must never show an unmeasured coverage badge or imply planned checks already run.

## Sources

- [Coverage configuration](https://coverage.readthedocs.io/en/latest/config.html)
- [Textual testing](https://textual.textualize.io/guide/testing/)
