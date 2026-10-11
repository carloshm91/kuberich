# Workload engineering checkpoint: D06 #51

Base main: `595e9a40cfcf7fe502a0e52be59a86d019dc72b5`. Qualification is in
progress; this checkpoint does not publish packages, tags, a tap or websites.

Every original prerequisite is closed, including the complete core checkpoint
[#40](https://github.com/carloshm91/kuberich/issues/40), four native executables
[#49](https://github.com/carloshm91/kuberich/issues/49), measured performance
[#50](https://github.com/carloshm91/kuberich/issues/50) and shell history
[#123](https://github.com/carloshm91/kuberich/issues/123). Actual early generic
resource and aggregate-log work is included; planned later capabilities remain
identified in the maintained capability inventory.

## Shell teardown correction

The original full local #123 run retained **one failure, 4,755 passes and two
documented skips**, in 3,337.49 seconds. The history test's five-second helper
expired while consuming 9,000 real PTY rows under coverage. During subsequent
Textual teardown, the still-owned output task queried a History button already
removed from the screen and raised `NoMatches`. Original evidence remains
`artifacts/shell123/full-v2-original.log`; passing hosted checks do not erase it.

The screen now retains its controls directly and checks actual DOM attachment
before updating them. A real-child regression removes the toolbar or either
individual control while output continues, verifies that the session remains
owned, then closes and requires process reaping, endpoint removal and cleared
history. The bulk-output completion wait has a dedicated 30-second deadline;
the independent uninstrumented maximum-heartbeat requirement remains 150 ms.
The completion deadline is not a responsiveness or performance claim.

The first regression assertion incorrectly expected Textual's `is_mounted` to
reset after removal. The pinned implementation retains that flag. Its failed
log is preserved as `artifacts/qualification51/history-regression-v1.log`; the
corrected assertion and production guard use public DOM attachment semantics.

The corrected focused cohort passed **40 cases in 154.01 seconds** with branch
instrumentation. The negative control ran the same toolbar-removal test on
original merge source `f1f23e363ece935f72531c0a92d84629f34ba101` and failed with
the original `NoMatches` in 32.67 seconds. Its complete output remains
`artifacts/qualification51/history-negative-original.log`; this establishes that
the regression rejects the former behavior. The targeted coverage report is
partial UI evidence, not an aggregate production or critical-module result.

Ruff/format passed over 530 files, strict source/gate types passed over 114 files,
and the plan and regenerated two-surface site checks passed: 49 pages, 1,728
local references and 64 files. Browser qualification and the complete source/
native matrix remain required on the frozen correction.

## Required final evidence

The first correction's [PR run 38124841363](https://github.com/carloshm91/kuberich/actions/runs/38124841363)
retains a real-kind shell verifier failure after **4,759 ordinary tests passed**
on Linux 3.12. Its original artifact ZIP SHA-256 is
`e444e445f2a5f8ef4018e4804182077a2cb36eeb1ba4dee2be7003e412ce808d`.
The failed PTY capture shows `Review 6/362` and a clipboard payload containing
the echoed command fragment rather than its eventual output row. The original
fixture waited for `password=owned-secret`, which also occurred literally in
the command, and for a prompt already visible before command completion.
This admitted a frozen review before the full 1,100-row output completed.

The fixture now emits the credential-shaped row through separate printf arguments
and waits for an assembled completion marker absent from the command source.
It also waits for the exact redacted OSC52 payload after its own copy request,
instead of assuming a matching footer establishes clipboard completion. The
console/module/installed helper uses the same fresh-payload wait. Actual copy
content, redaction and source/input ownership requirements are unchanged.

The interrupted first repetition retains one complete 992-contract/thirteen-kind
round and a partial second round. Its active owned cluster was deleted and
absence verified during graceful cancellation. These partial results do not
count as three consecutive corrected rounds. New qualification must use a
fresh frozen correction, retaining the failed original and cancellation logs.

The [native Homebrew run 38124866302](https://github.com/carloshm91/kuberich/actions/runs/38124866302)
passed all three hosts on the original correction. The independent reader matched
all original ZIP and bundle checksums and both installed version payloads to
that frozen production source, alongside normal upgrade, actual upgraded PTY
behavior, configuration invariance and uninstall. A later source identity must
retain applicable qualification; this does not waive the failed PR gate.

Before closing this issue, retain the correction's negative control, complete
supported source/native matrix with actual original audit/install bytes,
independent line/branch/changed-line and 45 critical-module coverage, installation
upgrade/removal/configuration invariance, and three consecutive repetitions of
the thirteen current owned rehearsals. Record candidate source, artifact and
receipt hashes and unavailable provider/platform scope honestly.

Follow [integration qualification](../integration-testing.md) and
[quality policy](../quality.md). The reviewed first release is 0.1.0; its version
PR, immutable public channels, owner approval and installed-channel checks remain
[#89](https://github.com/carloshm91/kuberich/issues/89). Exact-candidate initial
site preparation remains [#150](https://github.com/carloshm91/kuberich/issues/150).
