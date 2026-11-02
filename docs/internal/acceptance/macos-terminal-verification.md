# Native terminal verification follow-up #157

## Trigger and scope

The source-opening checkpoint allowed standard public GitHub-hosted runners to
execute again. Main `d9587f1550baea3fecc34986bed81263c70cc707` received a real
[six-environment run](https://github.com/carloshm91/kuberich/actions/runs/37850244845).
Both completed macOS 3.12 and 3.14 logs establish 57 failures and 2,934 passes;
Linux 3.13 and 3.14 succeeded. These failed attempts remain part of the record.
They are not replaced by local Linux evidence or a waived gate.

The first correction affected the test observer, restoration oracle and connection
fixture, plus repository diff verification. Its actual PR attempt at
`85f199e5d24d53d92d21a839b003c5e54223c0bb`
reduced macOS/Python 3.12 failures from 57 to **5**, with **3,010 passes**.
Linux/Python 3.13 and 3.14 each passed 3,015 cases, and repository/DCO checks
passed. That failed macOS attempt remains recorded in
[run 37854767711](https://github.com/carloshm91/kuberich/actions/runs/37854767711).

The follow-up changes production shutdown detection: Darwin can retain readable
termios attributes after hangup while rejecting output. Probe only captured,
unchanged TTY output with a zero-byte write, preserve the signal mask, and discard
only recognized driver failures so buffered interpreter cleanup preserves exit
129. Requirements/version are unchanged. Full independent and changed-line
application coverage, native checks and all critical gates remain mandatory.

The next native attempt at `fe332d387f3ce1b4d20bde74d3b47a1890a57dd3`
passed **3,018 cases**, including actual workspace/native/embedded SSH-loss exit
129 and the selection-event witness. Its only failure remained tmux reattachment:
the actual transcript already contained successful `Shell closed`, but the wait
reused the first observer's byte offset against the new observer's transcript.
The correction captures the marker from the new send and requires a fresh child
resize witness after reconnecting. Same child PID, shell input, return, terminal
restoration and cleanup remain required. Original results remain in
[run 37857763042](https://github.com/carloshm91/kuberich/actions/runs/37857763042).
Its Linux/Python 3.12 suite passed all 3,019 cases, coverage and the seven
pre-install owned-cluster checks, but the installed quickstart exposed another
transient-title assumption: the namespace table had already loaded all six rows
and replaced `Namespaces` with `namespaces(all)[6]`. The rehearsal now observes
the stable table before filtering and still requires the actual filtered row,
namespace selection, pods, logs and shell behavior. No application navigation or
release gate changes to accommodate the fixture.

The subsequent native attempt at
`0773b39fc1512ec3dc0e3b05d12e2da2844fc375` passed **3,018 cases**, including
all SSH/tmux/installed-terminal checks. Its sole failure was an annotation UI
witness: the owned mutation record already reported success while the screen's
independent result waiter had not yet updated the feedback. That attempt is
retained in [run 37861030236](https://github.com/carloshm91/kuberich/actions/runs/37861030236).
The corrected witness deliberately holds feedback after the actual result,
asserts one successful write with the sending message still visible, releases
delivery and waits for visible success before checking history. Both compact
and ordinary terminal sizes retain default Cancel, explicit Confirm, redacted
history and drained shutdown assertions. No application behavior or timing
budget changes to make this verification pass.

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
- Actual readable-attribute/write-failure witnesses verify no bytes are emitted,
  only the captured TTY is redirected, and SIGTTOU's prior mask is restored.
  Unexpected write errors surface and preserve the descriptor.
- The selection-event witness waits for the initial projection's final viewport
  restore before moving the cursor, retaining its stale-event UID assertion.
  Embedded-shell fixture exceptions are retained even when the workspace repaint
  removes the traceback; they do not change the fixture's result or waive a failure.

## Measured local evidence and completion boundary

On Linux/Python 3.12.12, the final focused command
`uv run --locked --python 3.12 pytest -q tests/terminal/test_observer.py tests/unit/test_terminal_lease.py tests/contract/test_mutation_faults.py`
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
