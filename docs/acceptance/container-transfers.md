# S07 #48: attachment and transfer qualification

Status: **implementation in progress** on `feat/48-container-transfer`.
No complete issue, whole-candidate coverage or installed/platform qualification
is claimed by these first-slice receipts. File-transfer criteria remain open.
Measured progress is also recorded on
[#48](https://github.com/carloshm91/kuberich/issues/48#issuecomment-6075244355).

## Attachment progress

On actual Linux/Python 3.12.12:

- 163 shell/container/log/embedded regression cases passed in 56.53 seconds.
- 18 real loopback HTTP/private-file/executable attach contracts passed in
  0.98 seconds: captured scope, all existing container kinds, read-only/stale
  refusal, HTTP failures and preexisting connection-file preservation.
- 14 Textual/actual inner-PTY cases passed in 37.20 seconds: regular/init/ephemeral
  selection, detach/local close/quit, literal keys and retained viewport.
- The focused deterministic `domain/attach.py` measurement covered 48/48 lines
  and 30/30 branches. The module is enrolled in the critical 100% inventory.
  This focused result is not whole-production coverage.
- An explicitly owned kind cluster with the pinned node/image/kubectl exercised
  native embedded attach to a real interactive main process, actual commands,
  detach/return, reattachment to the still-running process and outer-terminal
  restoration. Cluster deletion and absence were verified. The maintainer's
  context was not used.

The retained progress probe and fixed reports are under
`artifacts/container-transfer-48`; the formal combined required verifier is still
part of this issue. Production decisions are independent of Textual. Capture
owns private connection staging and refusal; the existing process/PTY owner
drains local work and cleanup on return or cancellation.

## Remaining acceptance

Actual uploads/downloads, size/destination/overwrite review, traversal/link/special
entry refusal, interruption/partial outcomes, complete failure/cancellation cases,
installed/native platform checks, whole-package independent coverage and the
combined required owned-cluster verifier remain necessary before an issue-linked
PR can close #48. No publication is included.
