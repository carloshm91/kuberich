# Forward presets and transport: S08 #62

This extends the existing owned Pod/Service forward controller. It does not
publish a package or change the immutable 0.1.0 distribution.

## Captured behavior

- Pure mapping resolution accepts literal numeric/named TCP ports and explicit
  regular-container qualification. Missing/ambiguous/UDP declarations fail;
  Service names resolve to Service ports, not guessed backend numbers.
- Versioned local preferences own named presets, exact-context replacement and
  auto-annotation permission. Cluster metadata never grants that permission,
  chooses a bind address or initiates work while listing resources.
- The existing Start guard applies before preparing credentials or launching
  children. Non-loopback presets need their own unchecked-by-default opt-in.
- Automatic annotation shortcuts apply only to an explicit forwarding action
  after local opt-in. Without it, annotations populate the ordinary review form.
- The child transport flag preserves captured environment in auto mode, sets
  `KUBECTL_PORT_FORWARD_WEBSOCKETS=true` for WebSocket preference (including
  kubectl's documented fallback), and `false` for SPDY. No wire negotiation
  observation is claimed from an environment flag.
- Zero retries remains the default. Explicit budgets 1–3 reconnect only after
  process disconnect. The old ownership stack cleans up first; each new process
  gets fresh delegation and preflight. UID/403/404/context/readiness/collision
  failures, cancellation and Stop are terminal for that controller.

Captured named mappings are rechecked at preflight, readiness and monitoring.
Reassigning a Service port name under the same UID requires new review rather
than forwarding to an unreviewed number. Backend target-port changes retain
the captured Service port and can be picked up on an opted-in restart.

## Verification sources

`tests/unit/test_forward_presets.py` covers literal grammar, container/Service
resolution, unsafe and oversized values, duplicate local ports, annotation
precedence, transport isolation, explicit local permission and context scopes.
`tests/contract/test_forward_reconnect.py` uses real owned subprocesses and TCP
listeners to verify payloads after reconnect, old PID/listener removal, fresh
private paths, finite retry budgets and failures/cancellation during backoff.
The original numeric/IP/readiness/cancellation/history contracts remain required.

Pilot exercises the forms at 40×12 and 100×30, local presets, named ports,
remote-bind refusal, invalid preferences, default review and explicit exact-context
annotation permission. Source and genuinely installed wheel console/module PTYs
exercise named annotation defaults, traffic, navigation, resize, Stop/exit and
the unchanged terminal restoration oracle.

The extended `scripts.verify_port_forwards_kind` uses only its own disposable
cluster. It resolves declared Pod/Service names and annotation syntax, sends HTTP
through both selected kubectl transport modes, changes a Service selector/backend
port, then induces a real process disconnect and verifies the distinct backend
response on reconnect. It also verifies non-loopback opt-in, namespace retention,
resource/context invalidation and process/listener/file cleanup. These owned
fixtures are not real EKS/AKS/GKE certification.

## Measured results and delivery

The initial focused command passed **218 tests in 98.18 seconds**, including pure
contracts, owned HTTP/process listeners, compact/normal Pilot forms and actual
source/installed-console/module terminals. Both new deterministic modules and
the original forward domain measured **100% line and branch coverage**. Strict
application/owned-kind-verifier types, Ruff and formatting passed.

```sh
uv run pytest -q tests/unit/test_forward_presets.py tests/unit/test_port_forwards.py tests/contract/test_port_forwards.py tests/contract/test_forward_reconnect.py tests/ui/test_port_forwards.py tests/ui/test_forward_presets.py tests/terminal/test_port_forwards.py tests/packaging/test_forward_presets.py --cov=kuberich --cov-branch --cov-report=xml --cov-report=json
uv run python -m scripts.verify_port_forwards_kind --kind /absolute/path/to/pinned/kind --kubectl /absolute/path/to/pinned/kubectl
```

The final owned-kind run verified named annotation defaults, both transport
selections, real HTTP, owned/external listener collisions, explicit remote bind,
Service backend replacement (8080 to 8081), reconnect, deletion, namespace
retention, context replacement and exit. Source kubeconfig bytes remained
unchanged. All processes/listeners/private files closed and the owned cluster
was deleted with absence verified. Pinned node, BusyBox and tool hashes and
actual per-scenario receipts remain in the original qualification artifacts.

Initial retained failures caught an incorrect CLI test expectation (invalid
preferences exit 2, not 3) and a kind fixture inspecting the newest deliberately
failed collision record instead of its captured live-forward identity. Correcting
those observers preserved the original behavior assertions. A later review added
same-UID Service-name reassignment checks; the final 218-case run and fresh kind
run qualify that additional protection, not just the earlier source.

Original focused reports, PTY transcripts/restoration receipts and failed/successful
kind logs are retained under `artifacts/forward62-*`, `artifacts/terminal` and
`artifacts/cluster`. The protected PR checks retain the complete platform/native,
whole-production and changed-line qualification separately; this focused result
is not a claim that every production module was exercised by these 218 cases.
The phase gate and public release activation remain separate work.

## Startup failure regression

A final review distinguished a disconnected established forward from a child
that never became ready. Two real-process negative controls reproduced the old
behavior: initial and replacement configuration errors consumed all three retries
(2 failures in 4.62 seconds). The controller now allows reconnect only after
READY; an initial or replacement startup failure terminates without another
helper invocation. No output matching, deadline or retry-budget limit was relaxed.

The corrected source passed **220 focused tests in 79.79 seconds**, including
both regressions and the original unit/HTTP/Pilot/source/installed-terminal cases.
Both new deterministic modules and the existing forward domain retained 100%
line and branch coverage. The earlier full local suite remains frozen on original
commit `2af1b83`; it is supplemental baseline evidence, not a full-suite result
for this correction. Fresh complete protected source/native/owned-kind checks
qualify the corrected PR head before merge.

## Required-check UI regressions

Run `39187185271` retained a genuine Python 3.13 runtime failure: a 152.761-ms
heartbeat gap during the fourth resource route, including a 119.516-ms generation-two
collection of 22,139 objects. The callback measured 150.700 ms of main-thread CPU.
The test's unchanged 150-ms limit rejected the candidate; an unchanged rerun was
not used as evidence of correction.

An independent native-control weak-reference test reproduced a concrete retention
source: clearing Textual's LRU owner left its linked ring and render values waiting
for cyclic collection. The owned table cache now unlinks discarded native entries
on clear/discard/owner retirement. Lookup, eviction, key order, counters and all six
original capacities remain native. Nine ownership/API cases passed, and the new
deterministic module measured 100% lines and branches.

The first corrected local Python 3.13 runtime control passed both full retained-history
rounds with an 89.312-ms maximum heartbeat. Its deliberate 200-ms negative callback
still failed at 202.963 ms; the required instrumented coverage replay completed.
GC stayed enabled with its original `(2000, 10, 10)` thresholds. These local results
do not replace fresh full hosted qualification after subsequent source changes.

The same original run's macOS installed-console trial retained a real `tok` paint
where the metadata key was `token`, followed by a cleanup failure that masked the
initial assertion. The original ANSI transcript confirms application clipping,
rather than merely a missing observer substring. A held native content-width scan
reproduced header-width clipping in Pilot before correction. Configuration columns
now use widths from the captured metadata before painting; values remain hidden.
The corrected ownership/configuration cohort passed 21 tests in 22.84 seconds.
Source and installed PTYs keep their original visible-name and restoration controls.

Original failed source artifacts and exact digests remain under
`artifacts/failed62-python313` and `artifacts/failed62-macos`. A fresh complete
source/native/owned-cluster run must qualify the final source; earlier passing
native archives and the two passing source environments belong to the earlier
tree. The original full local baseline on `2af1b83` completed with 5,774 passes
and three skips in 4,317.23 seconds; it does not qualify these later corrections.

## Owned terminal failure cleanup: #208

The original macOS failure above first rejected a clipped `token` label. Its
subsequent three-second owner wait and denied `killpg` replaced that assertion.
The same masking boundary recurred in required standalone macOS x86_64 run
`41282379945`, job `124777431135`. That later trial first rejected missing
`PLUGIN_BACKGROUND`; the application output-refresh correction belongs to #272.
The terminal harness keeps both visible assertions and their original deadlines.

The later original artifact `13074266572` was downloaded and independently
verified against SHA-256
`d8f095ef9ab240b1adb4e4303a0399843b66676371d5dd9294362e841a3cce66`.
Its original failure receipt had no application completion record, followed by a
three-second owner wait and Darwin `EPERM`. The retained raw log, archive and
extracted ANSI/JSON remain under `artifacts/wayland220` in the integration
checkout; the archive is `standalone-macos-original.zip` and the extracted
receipt is `macos-original/terminal/failure-1793516195943669000.json`.

### Ownership and failure policy

The disposable session owner captures the actual application exit and terminal
modes before waiting for an acknowledgement. The parent releases it only after
a fresh, bounded process-group observation finds just that owner. This pins the
session identity while group termination may still be necessary. Every real
TERM/KILL verifies the original unreaped `Popen`, PID, process group and session;
the test process and its own group are refused. After reaping, only a read-only
signal-zero probe is permitted. An owner exit or `EPERM` alone never proves
group disappearance: only `ESRCH` does.

Cleanup retains the existing three-second TERM and three-second KILL phases.
Membership observation that exhausts a phase advances to its existing escalation
step; it does not report an empty group. Successful KILL disables acknowledgement
because it also kills the guard. Darwin's short disappearance checks stay inside
the current phase deadline. A live or persistently denied group remains a failed
cleanup even if the known direct-child fallback can reap the owner.

Failure cleanup drains bounded raw terminal output without invoking the failed
screen observer. It records observed completion, owner status, group status,
termination stages, acknowledgement, descriptor closure and errors separately.
The original exception object and traceback propagate, with a note identifying
cleanup and its receipt. Cleanup-only errors raise a group of the real errors.
Evidence-write failure cannot skip cleanup or replace a body exception. Each
allocated descriptor receives at most one close attempt, including constructor
failure and repeated teardown, so a reused descriptor number is never closed.

The receipt retains completion both before and after cleanup. No exit status or
terminal restoration is invented when completion was not observed. Existing
successful `finish()` checks still require actual before/after terminal modes,
alternate-screen closure, cursor restoration and reporting-mode restoration.

### Owned controls and limits

The controls exercise a real disposable session with Linux and injected Darwin
errno sequences. They distinguish verified disappearance, an actually live group,
persistent denial and changed ownership. They preserve the exact first
`AssertionError`, cancellation and `KeyboardInterrupt` through acknowledgement,
polling, evidence and descriptor failures. Real owner hangs reproduce the original
three-second wait followed by successful or denied KILL after the application has
already been reaped, without creating an orphan as a fixture side effect.

A second real group member proves that acknowledgement waits for a fresh
owner-only observation after that member has actually been reaped. Further
controls cover an early reaped owner, closed acknowledgement pipe, completed but
KILL-escalated guard, constructor allocation failures and repeated teardown with
an unrelated recycled descriptor. They never send a signal to another group.

The source and genuinely installed wheel cohort passed **21 tests in 68.01
seconds**, covering navigation, shutdown, shell handoff, resize, plugin modes,
installation outside the checkout and original terminal-restoration controls.
The final cleanup/observer cohort passed **74 tests in 30.64 seconds**. Ruff,
formatting and strict typing of the terminal helper and standalone verifier
passed. Logs and JUnit XML are retained under `artifacts/issue208`; the
source/installed result precedes the final narrow phase-timeout and post-KILL
acknowledgement controls.

An initial final-control run retained **73 passes and one failure**: an expired
membership observation at the TERM boundary was recorded as an error instead of
advancing to the existing KILL phase. The correction retains that timed-out
stage, performs actual escalation, and still requires a reaped owner and verified
group disappearance. No deadline was raised. The corrected 74-case result above
includes this regression and the original denied/live controls.

The added errno controls are not native Darwin qualification. This Linux host
cannot qualify the actual macOS kernel behavior; protected native required checks
remain necessary. Test-support changes add no production code or feature-parity
claim, and these targeted results do not replace the full application coverage,
installed-platform or release gates. No real Kubernetes context was accessed.

### Platform sources

Apple's pinned XNU source
[`kern_sig.c`](https://github.com/apple-oss-distributions/xnu/blob/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea/bsd/kern/kern_sig.c)
distinguishes an absent group (`ESRCH`) from a POSIX group iteration with no
eligible target (`EPERM`), excluding zombie processes from signal delivery.
This supports conservative handling; it does not prove the exact kernel race
behind either retained incident. Apple's
[`kill(2)`](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/kill.2.html)
documents that signal zero performs checks without delivering a signal.
Python's
[`subprocess`](https://docs.python.org/3.12/library/subprocess.html)
documentation explains waiting, reaping and the need to drain child output;
[`BaseException.add_note`](https://docs.python.org/3.12/library/exceptions.html#BaseException.add_note)
keeps cleanup evidence beside the preserved original exception.
