# M03 #45 acceptance evidence

Selected workload commands provide default-Cancel Review and separate one-use
Confirm, common read-only policy and guarded captured UID/version. Scaling uses
the actual scale subresource; real narrow RBAC works without parent patch access.
HPA ownership is checked before preparation and execution. Restart and explicit
retained-history rollback respect paused/OnDelete strategies. Rollout monitoring
reads actual state and can stop without claiming a server undo.

## Final Linux qualification

Focused domain/HTTP/TLS/Pilot/CLI/CI-policy verification passed 425 cases.
Both workload and mutation decision modules reached
100% lines/branches. Five native terminal cases passed, including source scale/
restart/rollback and fresh-wheel console/module launches, with default Cancel,
separate confirmation, resize and terminal restoration.

Actual kind passed Deployment scale/restart/rollout/ReplicaSet rollback, HPA
refusal, forbidden scale writes, scale-only patch RBAC, paused refusal, timeout/
cancellation without undo, progress-deadline failure, and StatefulSet/DaemonSet
ControllerRevision restart/rollback. Its cluster was deleted and absence verified.
All complete Linux interpreter suites and independent coverage gates passed.
This is private implementation evidence, not public-release qualification.

| CPython | Passed cases | Duration | Production lines | Production branches | Changed lines |
| --- | --- | --- | --- | --- | --- |
| 3.12.12 | 2,952 | 1,955.42 s | 8,730/8,793 (99.2835%) | 2,477/2,544 (97.3664%) | 447/454 (98.4581%) |
| 3.13.12 | 2,952 | 1,456.09 s | 8,731/8,793 (99.2949%) | 2,478/2,544 (97.4057%) | 447/454 (98.4581%) |
| 3.14.3 | 2,952 | 1,053.32 s | 8,578/8,641 (99.2709%) | 2,477/2,544 (97.3664%) | 444/451 (98.4479%) |

Coverage includes all 90 production modules; every one of the 34 critical
deterministic modules reached 100% lines and branches on each interpreter.
Changed-line coverage compares with base
`79bb7bc11a8a0dfb7cef4ae70429716249b70674`. Ruff, formatting, strict mypy,
plan validation and actionlint passed. Optional actionlint ShellCheck/Pyflakes
integrations were disabled and are not claimed as separate checks.

Production is frozen at `e4aba8d8b6948553815c573935a9d91e6cdfaf76`, source tree
`6b1d17b1b626982bd56aaf74abb7efb38c3e55f5`. Test-only corrections at
`89fae0b9b74a6bf3758875fe41a96b37b0e578be` preserve that source tree and use
tests tree `24c085014b75e5e9399be58bb352e8ef8d024a45`.
The final suites contain 2,952 cases on each Linux interpreter. The frozen
repetition passed all 12 workload checks and all 12
manifest-editor regression checks; both clusters were deleted. Build/Twine and
locked/fresh installed-runtime audits passed, with 27 dependencies per audit,
no known advisories/exceptions, and verified artifact-linked provenance.
Six owned Pilot review SVGs cover scale/restart/rollback at 40×12 and 100×30,
without any write request.

## Corrected test contracts

The initial Python 3.14 suite passed 2,943 cases but failed two legacy assertions
that still treated scale as unavailable and rollout status as a write. Their
replacements enforce the implemented numeric-write guards and read-only status
contract; 250 selected guard/navigation/startup cases passed. Original 3.12/3.13
runs were stopped before completion to repeat on that corrected test tree.
The partial 3.12 run also caught a native namespace-header observer asserting
all columns after receiving only its STATUS witness. It now waits for the whole
NAME/STATUS/AGE row while retaining those assertions. All six actual installer/
navigation cases passed afterward. Original failed/interrupted evidence is retained
under `before-command-contract-update`; it is not final qualification. The three
complete suites and independent gates passed on the final test tree.

```sh
uv run python -m scripts.verify_workloads_kind --kind /tmp/kubetrol-tools/kind --evidence /tmp/kubetrol-45-evidence/kind.json
```

## Scope and limits

See [supported behavior](../workloads.md). HPAs can be created after the ownership
check; no cross-object transaction is claimed. ReplicaSet owners can reconcile
manual replicas. Failed StatefulSet pod recovery/deletion remain separate actions.
ReplicationController/generic resources and owner drill-down remain #53/#70;
this does not establish full capability-family parity. Native macOS, full hosted
matrix and cloud certification remain outstanding under the account Actions
block. No public package, tag, release or visibility change is made.
Raw evidence: `/tmp/kubetrol-45-evidence` (local).
