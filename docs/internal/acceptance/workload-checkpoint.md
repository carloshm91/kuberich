# Workload engineering checkpoint: D06 #51

Qualified main: `7cb3c6bab12c65f6ad76b6ee02af914d009a7315`. D06 #51 is
complete. This checkpoint does not publish packages, tags, a tap or websites;
the prepared `0.1.0` version retains its own candidate qualification.

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

## Completed PR checks and retained main findings

[PR #186](https://github.com/carloshm91/kuberich/pull/186) passed all protected
checks and merged as `560032a841b230805d2b0b69df192cc6ed8291a4`. Its complete
tree equals branch `56e056eb63c252a2a1a8566c90047fde222efbc4`; the tested PR
producer is `63dee25c9ee6bbcad1b1d4b2c6845bfa5e8de66d`. Independent reading of
all eight original archives in
[run 38127302020](https://github.com/carloshm91/kuberich/actions/runs/38127302020)
verified ZIP digests, original wheel/sdist audits, all four native enrollments
and the private development bundle. Four source jobs measured 99.096–99.128%
line and 96.858–96.966% branch coverage; all 45 deterministic critical gates
passed. Four jobs do not substitute for the six-environment release matrix.

[Native installation run 38127365939](https://github.com/carloshm91/kuberich/actions/runs/38127365939)
passed Linux, ARM macOS 14 and Intel macOS 15. Original archives verified both
immutable version payloads, normal manager upgrade, upgraded PTY behavior,
configuration preservation and uninstall. Three consecutive frozen branch rounds
completed 992 contracts and all thirteen owned-cluster scenarios each: 44
successful commands including build/metadata, 48.066 minutes. Independent review
verified all original logs, fault/cancellation cleanup and caller configuration.
Wheel SHA-256: `b415e6680d0b904404bceea14d4ac0d922a45bce3e33348fe6e8eba893a1bc67`;
results SHA-256: `3bb0365aea905a8685ea78c033063bcda5e6b84b13ea00a801e449ffbfe9bf7b`.
Those rehearsals are honestly branch-produced, with complete-tree equality to
the squash source recorded separately.

The complete [main run 38130866046](https://github.com/carloshm91/kuberich/actions/runs/38130866046)
then retained **two failures, 4,755 passes and four documented skips** on
macOS/Python 3.12 in 2,395.99 seconds. Its original artifact ZIP SHA-256 is
`534d9f3e5ab31a1ea69e7e5136458981877ffa3856d029f0b9f22a44309e8b46`, independently
matched to GitHub's digest. This run does not qualify the checkpoint.

The lifecycle test observed the PID path after the child's write opened it but
before its contents arrived, and `int('')` failed. The owned child now writes
the full record to a sibling pending path and atomically replaces the published
path. The 39-cycle cancellation/reaping/configuration/resource-count contracts
remain unchanged. No production PID/file behavior is changed.

The quiet-watch PTY failed before receiving its first pod and its retained frame
shows `State: Timeout`. Its 250-ms request timeout also bounded initial discovery;
the original does not measure the runner's scheduling delay or prove a broken
watch renewal. The revised scenario uses a 2.5-second request budget and verifies
three actual requested three-second quiet watches, each outliving that budget,
with identical resource versions and no stale/reconnecting/timed-out hints.
It additionally holds initial namespace discovery for 350 ms using an owned
gate. The separate 100-ms protocol tests still enforce short-deadline renewal.
Production request deadlines and latency/memory requirements are unchanged.

The focused cohort passed **96 cases in 46.10 seconds**. An owned negative
control reapplied the former 250-ms CLI argument to the same delayed-discovery
scenario and failed with the original initial-timeout behavior in 15.96 seconds.
The former negative-control collection attempt failed before executing a test;
its log is retained separately and is not regression evidence. Focused and
negative-control originals remain under `artifacts/qualification51-repair`.
At that repair checkpoint, fresh PR and six-source/four-native main qualification
were still required. Passing other jobs did not erase the failed originals.

## Completed qualification

[PR #187](https://github.com/carloshm91/kuberich/pull/187) passed protected
checks and merged as the qualified main above. Its complete tree equals frozen
branch `fe69af58a4cd6fc2609499a3f32f20f77ea4d47c`. The independent reader
verified all eight original source/native archives from
[PR run 38133853019](https://github.com/carloshm91/kuberich/actions/runs/38133853019)
and three native Homebrew archives from
[installation run 38133872760](https://github.com/carloshm91/kuberich/actions/runs/38133872760),
including both immutable payloads, normal upgrades, upgraded PTYs, configuration
preservation and uninstall. These are owned local versions, not public releases.

The complete exact-main
[run 38137221192](https://github.com/carloshm91/kuberich/actions/runs/38137221192)
passed **all six source environments and four native archive jobs**. Source
jobs ran Ubuntu 24.04 x86_64 and macOS 26 ARM on CPython 3.12, 3.13 and 3.14.
Independent original-byte reading verified each GitHub ZIP digest, original
wheel/sdist audits, native enrollment and the complete private development bundle.
Production lines measured **99.105–99.128%**, branches **96.858–96.966%**;
all **45 critical deterministic modules** met 100% line/branch requirements.
PR #186's eight changed production lines measured 100%; the test-only PR #187
and final-main comparison contain no changed executable production lines.

Three fresh consecutive rounds on the frozen repair branch passed **992
contracts and all thirteen owned-cluster scenarios each**: 44 successful
commands including build/metadata, **50.758 minutes**. Independent review
verified all 39 scenario receipts, fault/cancellation/reaping, cleanup, pinned
node/tools, caller configuration and retained original logs. Branch production
and complete-tree equality to main are recorded separately.
Wheel SHA-256: `b415e6680d0b904404bceea14d4ac0d922a45bce3e33348fe6e8eba893a1bc67`;
results SHA-256: `9540eb32146833717db7ed45d06fbf5ca5b535936da47ad94e9dc5c76c66d0ef`.

Original receipts remain under `artifacts/qualification51/run-38137221192-originals`
and `artifacts/qualification51-repair/consecutive` in their retained producer/
reader worktrees. Real EKS/AKS/GKE, physical terminal/font/clipboard combinations,
physical macOS 14 Intel, final `0.1.0` artifacts and public channel/domain/site
verification are not established by this development checkpoint.
