# B07 terminal navigation acceptance

Issue: #61. Implementation and qualification record for
[PR #206](https://github.com/carloshm91/kuberich/pull/206). The protected PR retains
the exact source/native matrix, independent coverage and artifact digests.
Published 0.1.0 remains unchanged.

## Implemented source contracts

- One shared parser handles local navigation controls; startup refuses selection
  and recall controls before authentication. Memory-only command/filter histories
  are bounded to 32; Alt arrows restore drafts and `!!` rechecks normal policy.
- Inverse/fuzzy, local label/allowlisted fields, observable errors with unknown
  counts, transient wide columns, exact-context favorites, bounded UID ranges
  and marked batch review preserve existing sorting and confirmation.
- Read-only documents/help have an independent configurable text key profile;
  input and remote-shell ownership remain separate. Shared chrome and nested
  bars preserve captured identity and drain streams before scope transitions.
- Coalesced owned container projection refreshes the already-open list from the
  Pod watch. UID/session/scope/fatal permission invalidation is sticky and closes
  covered readers/shells before client teardown; worker cancellation is drained.
- Native macOS/X11 writes and trusted OSC52/tmux framing have strict UTF-8/size
  limits. Ordinary PTYs force OSC52; Pilot uses memory. Native reads occur only
  after synthetic writes on an owned display/ephemeral hosted runner.
- Mouse reporting requires explicit preference opt-in. A no-mouse launch owns
  a known disabled reporting state; existing terminal-restoration checks remain
  unchanged and required.

## Measured local and hosted evidence

The initial domain clipboard/history/range/selector trial passed 87 tests with
195 executable statements and 90 branches, all covered. Further model and
optimistic-save tests passed 98 tests in 1.01 s. Strict production/new-kind/native
verifier type checks passed. These focused results are not whole-package
qualification.

Owned Linux Xvfb roundtrips retained exact Unicode, embedded controls, NUL,
RTF/EPS-looking text, empty text and replacement; owners were drained. Hosted
macOS early probe passed in run 39120007142. The failed original 39119729712
rejected newlines in the constant script argv before spawning; the corrected
script is one constant line and keeps payloads exclusively on stdin. The
original job log is retained locally; it was not an unchanged retry.

Owned kind v0.33.0/node v1.36.4 passed readiness/restart/waiting/running/terminated
API-status patches with the container view open, preserved selected name/offset,
invalidated a deleted/recreated UID under logs, drained nested namespace/context
transitions and verified Escape cleanup. The fixture Pod is deliberately
unscheduled; this is API/watch/navigation evidence, not running-container or
real restart/exec certification. The separate shell qualification remains required.

Source PTYs passed six navigation/inspection trials in 20.15 s, including direct,
SSH, tmux and SSH-to-tmux exact OSC52 receipts and actual capital-G bytes. Two
additional physical mouse-mode trials passed in 3.52 s. Receipt proves framing
reached the owned outer terminal, not acceptance by a personal clipboard.

The first unpaced `g:copy` trial exposed queued navigation losing ownership when
colon moved focus. Navigation bindings now complete in their focused owner before
the next key. A narrow-terminal fixture initially looked for clipped status text;
it now observes the visible resource frame/count. The shared container Back
control shares the caption above the frame, retaining a visible data row plus its header/scrollbar at 40x12
after the new command bar displaced it. Blank mark-gutter header clicks no
longer sort by a negative column index; real header clicks retain typed sorting.
Unmarked batch review preserves its previous ordering and explicit selections;
marked batches follow visible UID order. Original logs
remain under ignored artifacts; no restoration/performance/coverage gate was
weakened. Help now deliberately has a command bar, so Escape leaves that input
before returning from help; the behavioral test verifies both steps.

## Qualification requirements and retained failures

The initial broad diagnostic run found two strict source-identity rejections:
new production files were still untracked by git ls-files, and a lifecycle trial
observed edits during its interval. Index the complete source and keep it frozen
for qualification; neither original is a performance success. Visual inspection caught the horizontal scrollbar consuming the last compact
container row. Compact status now uses the existing bottom status line; Pilot
checks the scrollable body below the header, and source/installed/native PTYs
require an actual container name at 40x12. No GC, workload,
latency budget or identity guard is relaxed. Focused fixes also retain the old
batch-review ordering, above-frame Back control and actual header hit regions.

The early 3.14 draft passed 5,530 tests but failed changed-line coverage at 78.69%
(native application and refusal paths were not yet exercised). New inert-driver
application tests cover dispatch, bounded fallback, replacement/coalescing and
exit cancellation; real native clipboard evidence remains separately owned.
The 3.13 draft exposed child output preceding atomic SSH-owner ready.json
publication. The observer now waits for the bounded owner record before reading
it; a deliberate delayed-publication SSH test reproduces the order and retains
all original cleanup/restoration assertions. Original job logs and failures are
retained; no unchanged retry is treated as a correction.

Acceptance requires complete broad regressions, independent line/branch/changed-line
and critical 100% coverage, full source/installed/native matrix, repository/docs/browser
and protected checks on the same tree. The linked PR records measured results;
do not close the issue or merge a subset before that complete acceptance. No tags/releases/distribution/hosting
publication is part of this implementation.
