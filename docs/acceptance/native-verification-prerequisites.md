# Native verification prerequisites: Q03 #50 / D10 #89

This focused prerequisite addresses two verification ordering/transport failures
and adds evidence to an unresolved backend heartbeat failure. It does not complete
Q03's large-resource/input-response/memory-soak qualification or D10's first public
activation. No application source, version, dependency, retention bound, heartbeat
limit, timeout, cleanup assertion or coverage policy changes.

## Original failed source

PR #172's release-phase preparation was frozen at
`5e43489ed51dd1dd9149c92a2e1e1ad5dbe995fc`, with actual tested PR merge
`4303f046883c6df789dd4ac0cf01c9a566cf8f10` and the same tree
`df9a8b8c6d4124467a408fa000558eca67272e53`.
Required Application run `38018066077` failed; it was not rerun or merged.

- Linux 3.14, job `114112719674`: 4,177 passed. Original artifact
  `11656854675` was independently reviewed, including production/critical
  coverage, actual runtime positive/negative/replay arc union, distributions,
  installed managers, terminal restoration and audits.
- Linux 3.12, job `114112719773`: succeeded, including its actual owned-cluster
  checks. Original artifact `11658255922` was independently reviewed: 4,177
  passed, 99.1019% lines, 96.9533% branches and all 43 critical modules at 100%;
  runtime controls/replay arc union, distribution bytes/audits, installed managers
  and 214 real terminal receipts match that frozen source.
- Linux 3.13, job `114112719717`: 4,176 passed and one failed. The actual-HTTP
  tiny-line backend heartbeat was 157.739948 ms against its unchanged 150-ms
  assertion. Original artifact `11657428113` and the failed log are retained.
  An earlier main run also failed this node at 175.395733 ms.
- macOS 3.12, job `114112719706`: 4,174 passed and three failed. Original
  artifact `11657875799` and the failed log are retained. The Pyte exception
  originated in the test PTY observer after owned SSH disconnection. Two attach
  cases read parent feedback before Textual delivered its queued return callback.
- The aggregate Quality gate failed as required. These are failed-candidate
  records, not release qualification or evidence that the backend issue is fixed.

## Corrections and unchanged contracts

The real PTY harness retains every received byte, owned process/descriptor checks,
application exit, kernel TTY restoration and transport evidence. Once its owned
transport explicitly reports disconnection, it stops projecting the no-longer
observable remote screen; interrupted output can contain a partial CSI combined
with local connection termination output. Healthy connections still feed the
actual observer and expose malformed-frame exceptions. The existing deliberate
disconnect path continues to require the appropriate SSH exit and real cleanup;
it does not claim remotely transmitted alternate-screen restoration after loss.

Attach tests await both the restored ContainerScreen and delivered `Attach closed`
feedback within the existing five-second predicate deadline. They retain the
message assertion, exact detach bytes, selection/viewport preservation, private
configuration removal and process drain. No fixed sleep or product patch is used
to conceal a failing message.

The backend node retains its exact workload and all timing/retention assertions.
Its bounded diagnostic listener observes normal generation-two collections only,
removes itself on success/failure and records source, interpreter, coverage/import
facts, sample gap/overlap and actual post-close ownership. The report explicitly
states `diagnostic_only: true` and `runtime_qualified: false`. It neither proves
the cause of the previous hosted failures nor substitutes for required checks.

## Evidence limits

Read-only local diagnosis on unchanged `422c946` did not reproduce the hosted
backend failure. Correctly bracketed full-catalog/single-node, covered/runtime and
preceding aggregate-contract sequences measured 12.4–22.8 ms gaps without a
generation-two collection overlapping the largest gap. Earlier diagnostic hooks
ran after the test body; those retained outputs are invalid for case attribution.
Normal GC, the 150-ms assertion and original failed receipts remain preserved.

## Scoped local verification

On Linux with CPython 3.12.12, the following passed 36 cases in 36.80 seconds:

```sh
uv run pytest -q tests/terminal/test_observer.py tests/ui/test_attach.py tests/terminal/test_transports.py::test_lost_ssh_connection_during_embedded_shell_reaps_child_and_private_config --no-cov --junitxml=artifacts/native50/mac-corrections/scoped.xml
```

After adding a connected-SSH healthy-observer negative case, this passed three
cases in 1.44 seconds:

```sh
uv run pytest -q tests/terminal/test_observer.py::test_healthy_terminal_rejects_malformed_projection_and_retains_raw_evidence tests/terminal/test_observer.py::test_owned_disconnect_retains_late_malformed_bytes_and_actual_cleanup --no-cov --junitxml=artifacts/native50/mac-corrections/observer-final.xml
```

Original JUnit/log/raw/mode receipts are retained under
`artifacts/native50/mac-corrections`. Independent review verified all retained
hashes and 119 final source inputs; only the observer extension differs from the
initial 36-case source. Actual local and connected-SSH malformed output raises
the observer exception. The owned lost-SSH witness retains late raw bytes,
outer exit 255, kernel TTY restoration, inner-process disappearance and owned
descriptor/server cleanup. Remote screen restoration after loss remains
explicitly unavailable, not a successful observation. These are local receipts,
not macOS qualification.

On CPython 3.13.12, this covered backend/helper cohort passed 27 cases in
10.25 seconds:

```sh
uv run --isolated --locked --python 3.13 pytest -q tests/quality/test_backend_heartbeat.py tests/contract/test_aggregate_logs.py --cov=kuberich --cov-branch --cov-report=json:artifacts/native50/backend-corrections/focused-coverage.json --cov-report= --junitxml=artifacts/native50/backend-corrections/focused.xml
```

The actual tiny-line node measured a 23.118755-ms maximum gap under CTracer,
with normal GC enabled and unchanged thresholds, no observed generation-two
event, a responsive slow source, 302 retained records, 41,114 retained bytes,
and no owned tasks/API logs/watches after close. The report binds the actual
source inputs and removes its listener. This is diagnostic evidence, not a cause
or fix claim for the previous hosted failures. Focused coverage is not a new
whole-package coverage result; changed production-line coverage is inapplicable.

The workflow retains backend diagnostics even when a native test fails. Required
frozen hosted checks remain pending before merge. Full native/platform checks and
Q03 performance remain necessary; no previous failure is converted into a passing
result by a later run.

Ruff, formatting, strict application/tooling mypy and the plan validator passed.
The workflow-policy cohort passed 19 cases, including always-retained backend
evidence. Both static surfaces build and pass validation (49 pages, 1,726 local
links/assets and 64 files); hosted browser checks remain part of the required PR
validation. These scoped checks do not qualify public distribution or upgrades.
