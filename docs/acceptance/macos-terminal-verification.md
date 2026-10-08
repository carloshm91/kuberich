# Native terminal verification follow-up #157

## Trigger and scope

The source-opening checkpoint allowed standard public GitHub-hosted runners to
execute again. Main `d9587f1550baea3fecc34986bed81263c70cc707` received a real
[six-environment run](https://github.com/carloshm91/kuberich/actions/runs/37850244845).
Both completed macOS 3.12 and 3.14 logs establish 57 failures and 2,934 passes;
Linux 3.13 and 3.14 succeeded. These failed attempts remain part of the record.
They are not replaced by local Linux evidence or a waived gate.

The changes affect the test observer, restoration oracle and connection fixture,
plus repository diff verification. Application source, requirements, version and
packaging payload are unchanged. Changed executable application coverage is N/A;
complete hosted application coverage and all critical gates remain mandatory.

## Regression witnesses

- Fragmented standard/private device-status queries preserve following visible
  text; unknown private requests do not crash the observer or invent input.
  The observer remains independent of the application's terminal emulator.
- Raw inner/outer termios snapshots remain recorded. Darwin comparisons normalize
  only `PENDIN` (0x20000000), which its driver sets and retains when canonical
  mode resumes. Negative controls still reject changes to each of the six
  settings words and control characters, and retain exact Linux comparisons.
- Revocation decision tests cover actual owned descriptors and all three known
  revocation errno values. A separate closed-master trial reads the real driver
  response instead of assuming Linux behavior on an unclaimed Darwin PTY.
  Actual SSH-loss tests remain required; these unit fixtures do not certify them.
- The pre-send refusal witness uses a real loopback TLS API with its private CA
  deliberately absent from the client. The connection is rejected and no HTTP
  write reaches the server. The replaced merely bound TCP socket could drop SYNs
  on Darwin, which legitimately produced an uncertain timeout instead.
- Full-history repository checkout fixes the shallow root-commit comparison.
  PR and main whitespace checks use their actual event base, including synthetic
  merge commits, with root-commit handling retained for the initial event.

## Measured local evidence and completion boundary

On Linux/Python 3.12.12, the final focused command
`uv run --locked pytest -q tests/terminal/test_observer.py tests/unit/test_terminal_lease.py tests/contract/test_mutation_faults.py`
passed **50 cases**. The actual SSH/tmux/SSH-to-tmux log navigation trial passed
all three variants with the passive observer. The shallow Git reproduction
returned status 2 at the exact main commit, then status 0 after complete history
was fetched; original logs are retained locally under
`artifacts/operations-46/qualification/f447bc1` in the operation checkout.
The actual workflow script also rejected newly introduced trailing whitespace
in an owned two-parent synthetic merge (status 2), then accepted the corrected
snapshot against the same main base (status 0). Its script, commit pins and logs
are retained under `artifacts/verification-157`.
The complete `tests/terminal/test_transports.py` run passed **49 cases**
(169.83 seconds); fresh-wheel `tests/packaging/test_distribution.py` passed
**51 cases** (148.08 seconds), including actual installed SSH/tmux shells and
native handoff. Ruff, formatting and strict mypy passed (107 checked source
files); planning validation and both static-site build/link checks passed.

Full transport/package regressions and the delivered head's hosted Linux/macOS
checks are completion requirements; their live results and exact commit pins
are retained in [issue #157](https://github.com/carloshm91/kuberich/issues/157)
and its linked PR. This report does not infer native macOS success from Linux
or qualify an older head. The all-six supported release matrix remains a later
exact-candidate gate. No cluster credentials, visibility, website deployment,
DNS, public package artifacts or tags change in this follow-up.
