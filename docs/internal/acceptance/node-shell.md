# Controlled node-shell acceptance

Issue: A01 #76. Phase: v0.5.0. Node disruption and ephemeral containers remain
separate issues. This record does not establish a completed phase or publication.

## Current status

Implementation starts from protected main
`6f3e597f5a1a36caa72c09a1193a09097ea2ce23` on `feat/76-node-shell`.
The predecessor manifest PR passed its 27 exact-head quality jobs and app-bound
Repository/DCO gates before normal signed-off squash. That evidence does not
qualify the new node-shell behavior. Planning and implementation are separate;
early actual API and focused model/filesystem/service/UI trials pass. Complete
frozen-source terminal, production coverage and protected gates remain pending.

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

## Qualification still required

Final committed inputs, a fresh real-kind denial/timeout/interruption/admission/
proxy/recovery trial, source/installed PTYs and complete exact-head hosted
source/platform/native/production/critical/changed-line gates remain required.
No version bump, tag, package, hosting deployment or DNS change is authorized.
