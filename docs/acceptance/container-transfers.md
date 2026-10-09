# S07 #48: attachment and transfer qualification

Status: **final candidate under verification** on `feat/48-container-transfer`.
[Issue #48](https://github.com/carloshm91/kuberich/issues/48) retains live results.
Whole-candidate independent coverage and every required Linux/macOS check must
pass before completion/merge. No package, tag, site or DNS publication is included.

## Delivered behavior

Attach captures the selected context/pod UID/namespace and regular, init or
already existing ephemeral container, verifies running state and delegates a
literal kubectl attach argument vector through private connection material.
The embedded terminal preserves subprocess exit status and restores its outer
terminal on EOF, error, interruption, detach, local close and application exit.
Ctrl+P then Ctrl+Q detaches; Ctrl+] closes locally. Read-only refuses attach.

Uploads/downloads require explicit absolute source/destination paths, measured
upload size or explicit download bounds, reviewed overwrite and separate Confirm.
Cancel is the default focus. Each review owns one frozen intent and captured
connection/environment; changing fields invalidates confirmation. Uploads use a
private, bounded snapshot and kubectl cp with zero retries/no preserve. Downloads
stream tar into private state before validating/extracting and publishing.

Local ancestors use anchored no-follow descriptors. Links/special files,
traversal, duplicate/colliding names, sparse/unknown PAX extensions, excessive
metadata, payload/entry/depth limits and malformed/trailing data are refused.
Implicit directories count toward the 2,048-entry bound. Files use 0600 and
directories 0700. Existing regular-file replacement requires explicit review and
identity recheck; directory merges are refused. New directory publication rolls
back known copied entries through owned descriptors on failure. Concurrent
replacement files are retained; renamed reservations/concurrent additions may
require inspection rather than unsafe pathname deletion.

Cancellation drains the actual owned child and file workers before cleaning
private state/client configuration. A cancelled pending download retains the
local destination; a publication already committed is reported honestly.
An interrupted upload reports uncertain remote partial/completed state and
never retries or deletes remote paths. Read-only permits explicit downloads.

## Focused local evidence

Actual Linux/Python 3.12.12, before whole-candidate qualification:

- 163 shell/container/log/embedded regression cases passed in 56.53 seconds.
- 18 real loopback HTTP/private-file/executable attach contracts passed in
  0.98 seconds. The first embedded inner-PTY cohort passed 14 cases in 37.20 seconds.
- The final source/fresh-installed-wheel native attach cohort passed **14** cases
  in **41.19 seconds**, covering EOF, failure 23, interruption 130, detach,
  local close, SIGTERM 143 and quit, with child/config cleanup and outer restoration.
- Source/fresh-installed-wheel copy passed **four** actual native-terminal cases.
- Corrected boundary/filesystem/transport/Pilot cohort passed **168** cases in **58.51 seconds**.
  Its focused critical `domain/transfers.py` receipt is **86/86 lines and 32/32
  branches**; attach's focused receipt is **48/48 lines and 30/30 branches**.
  These are focused receipts, not whole-production coverage.
- Cleanup/command regression cohort passed **47** cases in **20.60 seconds**,
  including Escape, quit and actual F4 reconnection during an owned transfer.
- Additional pending-review/changed-path and safe refusal/error UI scenarios
  passed with the complete **11-case UI cohort** in **33.52 seconds**.
- Actual file-worker holds verify repeated cancellation during snapshotting and
  before/after publication; short writes are completed and disk failure retains
  the reviewed destination. Malicious archive tests inspect real files rather
  than mocking extraction behavior.

The exact boundary command is:

```sh
uv run --locked --python 3.12 pytest tests/unit/test_transfers.py tests/contract/test_transfer_files.py tests/contract/test_transfers.py tests/ui/test_transfers.py -q --cov=kuberich --cov-branch --cov-report=json:artifacts/container-transfer-48/copy-boundary-corrected.json
```

The additional review exposed Python tarfile coercing malformed PAX sizes to
zero. A real crafted archive reproduced silent empty-file acceptance; validated
decimal/size bounds now reject it before parsing. The corrected cohort includes
that filesystem negative control, numeric edge cases and concurrent-review
ownership. Its transfer form also measures 114/114 lines and 14/14 branches.
A second real filesystem negative control replaced a destination directory during
publication failure: pathname cleanup deleted its concurrent replacement. Cleanup
now stays anchored to the owned descriptor and known entry identities; regular
children publish exclusively. Completion also rechecks directory identity, and
changed paths produce an inspection message. The expanded boundary/Pilot/transport cohort passed **178 cases in 56.60
seconds**, including concurrent replacements/additions/renames, failed destination
open, publication cancellation and descriptor closure even when initial cleanup
fails. Final whole-candidate qualification remains required below.
Earlier failed/superseded receipts and the interrupted superseded full suites are
retained and are not counted as passes.

## Actual owned-cluster evidence

```sh
uv run --locked --python 3.12 python -m scripts.verify_transfers_kind --kind artifacts/operations-46/tools/kind --kubectl artifacts/operations-46/tools/kubectl
```

The latest combined rehearsal passed **13 checks** with pinned kind 0.33.0,
Kubernetes 1.36.4 node and matching SHA-verified kubectl. It exercised real binary
space-containing round trips for regular/init/existing-ephemeral containers,
8 MiB streaming, a Unicode/empty directory tree, overwrite refusal/explicit
replacement, missing tar, read-only refusal, interrupted download retaining the
local destination, observed partial upload with no retry, native attach/detach/
reattach/restoration, unchanged source configuration and private-state cleanup.
The owned cluster was deleted and absence verified. No maintainer/cloud context
was used. The metadata/implicit-directory refinement passed a frozen-head rerun. The later
PAX-size correction requires a fresh frozen-head rerun and required hosted verifier.

Receipts under `artifacts/container-transfer-48` are ignored private test artifacts;
GitHub retains final-head hosted artifacts. Failed fixture setup exposed an exec
exit-code ambiguity: missing test/infrastructure errors now refuse the copy
rather than masquerading as a nonexistent remote path.

## Honest limits

The remote container needs tar; uploads also need silent POSIX test and an
existing parent. Local tar is unnecessary. Selected stdin/TTY configuration
controls attachment behavior; creating ephemeral debug containers remains #78.
The process has a five-minute deadline, 8 MiB output mailbox, 528 MiB archive,
512 MiB payload, 2,048 total entries, depth 32 and 64 KiB/header / 16 MiB aggregate
extended metadata bounds.

Kubernetes attach/exec has no UID precondition; remote pathname preflights are
not atomic against container filesystem changes. A reviewed local replacement
has a narrow POSIX check/rename race. New directory publication is not globally
atomic. Ordinary source snapshotting detects observed changes, but cannot offer a
filesystem-wide transaction against concurrent edits. Remote processes can
outlive disconnection even after local kubectl has been reaped. These limits are
explained in the [user guide](../container-attach-copy.md); provider/native release
certification and final capability parity remain their dedicated gates.
