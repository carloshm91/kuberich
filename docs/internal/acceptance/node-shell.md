# Controlled node-shell acceptance

Issue: A01 #76. Phase: v0.5.0. Node disruption and ephemeral containers remain
separate issues. This record does not establish a completed phase or publication.

## Current status

Implementation starts from protected main
`6f3e597f5a1a36caa72c09a1193a09097ea2ce23` on `feat/76-node-shell`.
The predecessor manifest PR passed its 27 exact-head quality jobs and app-bound
Repository/DCO gates before normal signed-off squash. That evidence does not
qualify the new node-shell behavior. Planning and implementation are separate;
actual API, model/filesystem/service/UI, committed-source and installed terminal
trials pass. Complete exact-head production coverage/platform/native/protected
gates remain required before merge. Local evidence does not replace them.

## Reviewed boundaries

- Explicit enablement, one approved digest image, an existing namespace and
  bounded requests/limits/startup/session duration; no defaults that create pods.
- Fixed Linux diagnostic profile, visible host-root privileges and no policy
  relaxation, scheduler bypass, automatic chroot or application image download.
- Fresh Node/namespace/session/configuration guards and one-use dry-run review.
- Exactly one create request, trusted returned-UID ownership before admitted
  profile checks, durable private journal before exec and no unknown-UID adoption.
- Existing embedded PTY; ownership retains detached screens and drains exec before
  UID-conditioned deletion, absence observation and client/private-file release.
- Original active lease cleanup survives preference tightening; recovered cleanup
  needs write mode and a new explicit review on the matching selected connection.
- Metadata-only bounded recovery, no automatic connection and no deletion based
  solely on a name, label, fingerprint or later GET.

See [ADR 0043](../../adr/0043-owned-node-shell-sessions.md).

## Early real API and terminal proof

The first exploratory verifier run, `artifacts/issue76/early-kind-01/evidence.json`,
passes all four real API/PTY contracts in 33.77 seconds on kind 0.33.0/Kubernetes
1.36.4 with kubectl 1.36.4. It creates the exact reviewed Pod, reads the durable
returned UID, waits for placement and executes through existing ShellService and
ProcessRunner. The terminal independently observes `/host` and shared host
PID/network/IPC namespaces. Returning drains exec, deletes with the Pod UID,
confirms 404 and removes the journal. An unrelated sentinel keeps its UID.
All 300 measured runtime/helper inputs remain unchanged; caller-owned kubeconfig,
environment, local children, private files and cluster cleanup are verified.
Report SHA-256:
`ddc15374e68756bdfd91fcc1e510bc40b27cef917a8b3f8f48a766f419319c7c`.

The command is `.venv/bin/python -m scripts.verify_node_shell_kind` with explicit
checksum-verified absolute `--kind`/`--kubectl`, `--docker /usr/bin/docker` and a
fresh `--evidence artifacts/issue76/early-kind-01/evidence.json`. This frozen
working-tree proof precedes extensive UI work. It is not a committed final-source
qualification; later changes require another trial. No active operator context,
customer data or provider cluster is used.

## Expanded working-tree API proof

`artifacts/issue76/full-kind-01/evidence.json` passes 15 real contract groups in
55.06 seconds with all 303 measured inputs unchanged. It adds actual restricted
Pod Security refusal, RBAC create/exec/delete denials, read-only recovery refusal,
explicit matching recovery, normal-scheduler timeout on the owned cordoned Node,
interrupted scheduling and live exec, and a LimitRange admission change after
review. The returned UID remains available for cleanup without opening exec.

A bounded forwarding proxy commits writes to the real owned API before losing
create/delete responses. Each effect uses one request; unknown creation is never
adopted, known deletion is reconciled, and an actual same-name replacement survives
the original UID-conditioned DELETE's 409. The sentinel UID, private owners/files,
source kubeconfig/environment and independently verified cluster absence pass.
Report SHA-256:
`ce43fd890fc88e403bd14346e9c6e36772f54731eb06ecedaa19ef5e31871dcd`.

This remains frozen working-tree evidence. Subsequent final-source corrections,
tracked packaging inputs and protected exact-head qualification remain required.

## Focused development evidence

- The model/journal lane passes 238 cases in 4.05 seconds. All four new modules
  pass 100% lines and branches (534 statements, 172 branches). Only the three
  deterministic config/domain modules join the mandatory critical inventory;
  the filesystem adapter's scoped result does not replace complete coverage.
- The filesystem cases include a real child-process crash/flock release, fsync,
  rename/directory-fsync failures, exact capacity/physical-byte bounds, symlink,
  hardlink, FIFO, permissions, record replacement and repeated cancellation.
- Real loopback API/lifecycle and bounded fault-proxy checks pass independently;
  their API counts do not establish actual Kubernetes admission behavior.
- Recovery's 33-case cohort passes in 4.61 seconds, measuring 193/194 lines
  (99.4845%) and 39/40 branches (97.5%) in that service. It tests unknown creates,
  exact scope, read-only/changed policy, one-use and pre-entry cancellation,
  replacement, denial, durable-file failures and preparation ownership.
- The shared documentation/CI/CLI cohort passes 290 cases in 15.94 seconds.
  Native help snapshots are generated with actual CPython 3.12 and 3.13 in
  separate environments. Ruff and the whole private-access check pass.
- Public Pilot/local-PTY cases cover two viewport sizes, review cancellation,
  actual production loopback SDK creation, shell return, known-UID deletion and
  local drainage. Source/native and clean-installed CLI PTYs remain separate gates.

These scoped cohorts overlap; do not sum them as a complete suite or infer
whole-production coverage from module-only measurements.

## Original failures and corrections

Read-only independent review found that concurrent recovery preparation could
overwrite its task and release another capture's journal lease. A held public
journal-acquisition test reproduces the original failure in
`artifacts/issue76/control/recovery-capture-red.log`; a synchronous in-flight
guard now rejects the competing capture and passes the expanded cohort.

The original real HTTP ambiguous-POST/durability regression is retained in
`artifacts/issue76/control/journal-regression-original-failure.log`. A committed
POST with a dropped response followed by a failed journal transition could remove
the remaining prepared record. Request-outcome state now prevents that removal;
the known uncertainty stays recorded, no Pod is adopted/deleted and local failure
propagates after drainage. Its corrected log is retained separately. Malformed
cleanup observations no longer count as absence or replacement.

Local recovery fsync failures propagate after lease drainage. In particular,
unlink followed by failed directory fsync cannot truthfully promise that the
record was retained; the application reports a durability failure instead.

## Committed-source and installed qualification

Committed candidate `f898c5bbd200bf363dca4e73744066d14fac04b3` passes all
16 real-kind contract groups in 59.78 seconds, with 303 measured inputs unchanged.
`artifacts/issue76/committed-kind-01/candidate.json` records its clean commit/tree
before execution. The additional case terminates an actual certificate-only
producer with SIGKILL after creation and durable UID capture, reaps its process,
then loads the legitimate journal in a new certificate-backed SDK session.
Connection evidence matches; explicit inspection/review/confirmation deletes only
that UID and confirms absence before removing the record. The sentinel survives.
Fresh-session cleanup, process reaping and owned-cluster absence all pass.
Report SHA-256:
`285d9238851528b14bb86d54bdda3c7a94ac99c9565eb53e0851e34f218e2d09`.
Fixture teardown removes only its contained crash-left private directory after
reaping; this does not claim automatic global credential-file cleanup after SIGKILL.

The exact command is `.venv/bin/python -m scripts.verify_node_shell_kind` with
the verified absolute tool paths described above, `--docker /usr/bin/docker` and
fresh `--evidence artifacts/issue76/committed-kind-01/evidence.json`.

`.venv/bin/pytest tests/terminal/test_node_shell.py tests/packaging/test_distribution.py::test_installed_node_shell_owns_uid_cleanup_and_restores_terminal -q -x --basetemp=/tmp/kuberich-76-pty-installed-03`
passes all 11 cases in 47.34 seconds (use a fresh physical temporary path for another
trial): nine source CLI scenarios and both installed
console/module entry points outside the checkout. Source scenarios cover normal
and repeated return, Unicode, resize, Ctrl+C/Ctrl+], quit/SIGTERM, missing helper,
missing shell and exec connection loss. Actual termios, alternate screen/cursor
restoration, process reaping, UID deletion, journal/private connection removal and
unchanged owned kubeconfig are asserted. The frozen measured head is
`7623dd8879d6117cabad8c6e4fec1709a4745b46`; its trusted local wheel SHA-256 is
`12fc97df3a9d23bb62ff4e007e85eb172ca791fd86e42772e93261573047d466`.
All 299 current runtime files match that wheel byte-for-byte at the later
committed verifier head; `candidate-association-01.json` retains this comparison.
The unchanged package version is 0.4.0 for this unpublished feature candidate.

The original installed trials remain failed: the first fixture compared an entire
DELETE URL instead of separately validating the exact Pod path and Strict query.
The second assumed a closed-status phrase could not wrap at 80 columns. Corrected
checks retain the same deadlines, UID/effect/cleanup/restoration requirements.
Timestamped failure ANSI/JSON and both original logs remain retained. A real
review-text redaction issue found in those frames is corrected: the explicit
token-automount-disabled posture remains visible and passes two public UI cases.

The final focused source/contract/Pilot/legacy/docs/CI cohort passes 866 cases in
143.56 seconds. Its diagnostic changed-line profile covers 1,729/1,779 executable
lines (97.19%); it is not whole-production coverage. Actual workflow strict types
pass 351 source targets. All three newly enrolled critical modules reach 100%
lines and branches; the complete current inventory contains 124 modules.

`.venv/bin/python -m scripts.check_startup --output artifacts/issue76/startup-frozen-01`
passes all hard contracts and strict negative controls. Offline/import latency
targets pass. The five actual UI frames measure 1,061.58–1,089.73 ms against the
unchanged 600 ms target, retained as an advisory miss for 0.x. No RSS/import/frame/
deadline/cleanup contract or timing limit was weakened. Its measured commit is
the same terminal head above; all 303 startup input hashes still match the later
verifier candidate. Startup report SHA-256:
`f19517a73816877648e257564f48c340669f7e9c38f7a738624c43f802d8a394`.

## Protected qualification still required

The first hosted run, `42761940112` at
`1302f8f5705378fd386009c771a2b26ac3c104ea`, **fails** its Fast tests gate:
8,959 pass, one is skipped and one fails before fail-fast stops the remainder
(462.83 seconds). The shared navigation alias test omitted `NODE_SHELL` from its
explicit read-only rejection inventory. Production correctly raises the existing
read-only error; the test incorrectly expected it to be allowed. Add that command
to the rejection inventory, preserving every guard. The corrected navigation,
catalog and launch cohort passes 301 cases in 2.21 seconds. No production code,
threshold, exclusion or skip changes. The original hosted log and checksum-verified
JUnit artifact remain retained; its blocked matrix is not a platform pass.

The second hosted run, `42763394040` at
`ca7f9926d15ea27313032e58293990c1495b4eb7`, passes Fast (10,530 tests, one
skip), 15 of 16 source parts and three of four native targets. The remaining
Linux source/native jobs stall during package preparation, before testing or
building, with repeated Azure Ubuntu mirror failures. After approximately 25
minutes the run is cancelled; its logs and successful partial results remain
retained. The application coverage aggregation never runs, so this attempt does
not qualify the complete matrix or production coverage.

The CI-only bootstrap now selects the architecture-appropriate official HTTPS
Ubuntu mirror when the image supplies its known mirror list. An absent list
retains the image's sources. APT signature/TLS checks and the original package
closure remain intact. Strict index updates, effective Acquire timeouts/retries
and root-owned GNU timeout process groups bound preparation; failures propagate.
This addresses the [upstream runner mirror stall](https://github.com/actions/runner-images/issues/14594)
using the [documented effective Acquire keys](https://github.com/actions/runner-images/pull/14643).
No local APT or system configuration is changed during verification. All 149
fake-bootstrap, workflow-policy and qualification contracts pass in 8.63 seconds;
the additional helper passes strict typing. All platform/test/coverage gates are
retained for a fresh complete hosted run.

The next complete attempt, `42769208798` at
`4411639642a786417c22321b46fef9aef75528a8`, passes Fast (10,530 tests, one
skip), all four native targets and 15 of 16 source parts. Package setup succeeds;
the Fast runner's APT stage takes 25 seconds. macOS source part three fails one
existing native relationship/header scenario (3,338 pass, four skips). The final
application matrix is skipped and Quality gate fails, so whole-production
coverage is still unqualified. Its original log, ANSI/JSON and verified artifact
`13742540946` remain retained, with ZIP SHA-256
`1203446d4fc40aee30c4c8aaebe57a1e752c630ffcde44b12d6e8a4a3f4c89a7`.

Retained frames show a zero-match relationship filter before the last resource
arrives. The table then preserves a synthetic source-row selection/vertical
anchor, hiding the first actual matches. An independently held HTTP response and
public keyboard/Pilot regression reproduce the bug. The correction resets that
empty-to-resource vertical selection while preserving horizontal position and
the existing nonempty-resource identity rules. The original native deadline and
predicate remain intact. This shared UI correction changes a runtime file after
the earlier local wheel/verifier trials; their byte-identity association above
is historical, not qualification of this corrected candidate. Fresh exact-head
qualification remains required.

The deterministic regression is retained red (one failure in 3.04 seconds) and
passes after the three-line table correction. The unchanged header/table/navigation
cohort passes 39 cases in 37.04 seconds; the original native/fragmented terminal
file passes four cases on local Linux in 15.06 seconds with unchanged 15-second
stage deadlines. Ruff, formatting and strict module types pass. These results do
not claim a macOS pass; the next exact-head hosted matrix must establish it.

The final guide audit also corrects an unusable `:reload` instruction: no such
command exists. Valid node-shell preference changes use the implemented automatic
two-second reload, as the corrected setup steps now explain. This documentation
change leaves the corrected runtime unchanged; protected checks still apply to
the final source head.

The protected PR must pass complete exact-head hosted source/platform/native,
production/critical/changed-line coverage and app-bound repository/DCO gates.
No version bump, tag, package publication, hosting deployment or DNS change is
authorized by these feature trials. Real provider certification remains opt-in.
