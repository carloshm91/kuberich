# O06: reviewed local exports and saved-artifact browsing

## Source and delivery boundary

Issue #73 starts from protected main
`f4c34931dcf49df68f122888d028069af310c29d`, tree
`df7f4fd13ed547460e1b6172de0a59093482af6f` after #72/PR #314.
The retained Astra plan is unchanged:
`8144fed35c500390354202ed370c4fd234d79b89aadfe969c11e63298ed102f9`.
The startup supplement is
`15642c69563295503e3cc3743864d433749e96242071de8614ab56f281c94ae8`;
shared interfaces are
`e723caac8d1bdd5969b289004670c24c0feef043f97c8ce97698cd0de224fd40`.
The port revalidation bound 34 source files and 76 integration ports to the
delivered diagnostic tree before implementation. Sol agents share one issue
with explicit source ownership; no other product issue is being implemented.

Source version remains 0.3.0 during this unreleased 0.4.0 work. No tag, package,
tap, website or DNS publication is implied. Full integrated and platform
qualification remain pending; the focused measurements below are not substitutes.

## Implemented behavior

- Frozen resource/document/log/diagnostic/table captures carry context, header
  namespace, actual collection scope, UID/version and observation/export times.
- `:export` and log Save open a real review with safe preview, directory/name,
  default-Cancel overwrite and separate one-use sensitive consent.
- `:exports` supports bounded local scan/filter/view/page/copy/save-copy/delete.
  Startup opens it before context/auth/optional release checks; Back stays
  disconnected until a deliberate context selection or retry.
- Codecs re-redact untrusted files, bound parsing and preserve explicit source
  gaps. Sensitive export is restricted to fresh checked raw resource YAML.
- Support JSON is inspectable, contains fixed safe components and explicit
  opt-ins/omissions, and is never uploaded automatically.
- Physical descriptor traversal, private modes, reviewed identity/content,
  staged publication and cooperative cancellation own every local effect.
- Connection close drains and revokes every namespace generation using that
  client. Local artifact operations are independent of cluster connections.

## Focused measured evidence

The domain codec cohort passed 142 cases. Its independent production coverage
was 771/771 lines and 326/326 branches. Service consent and lifecycle tests
measured 382/382 lines and 120/120 branches; filesystem adapter measured
256/256 lines and 70/70 branches. Both domain and service are enrolled as
critical deterministic modules with enforced 100% lines and branches.

Four export UI modules passed 41 focused cases in 62.19 seconds. Their scoped
measurement was 836/874 lines and 189/254 branches; it is not described as a
per-module branch-gate pass. The integrated complete-package measurement is
still required. Ordinary log Save migration passed 26 cases in 109.33 seconds;
the performance cohort was deliberately deselected until a quiet timing window.

Owned-HTTP log capture passed 11 cases in 12.49 seconds. Held old readers prove
that changing container/head/previous/window cannot label old bytes with new
options. Capture is unavailable during handover. Ordinary arrivals, pause,
resize and scroll preserve an existing frozen capture; clear/filter/source
selection and context teardown reject stale intent.

Source and command receipts are retained under ignored `artifacts/issue73/`:
`domain/handoff.json`, `domain/diagnostic-ui-handoff.json`,
`domain/log-capture-handoff.json`, `storage/verification.json`,
`ui/evidence.json` and `ui/log-migration-evidence.json`. These local paths are
evidence locations, not distributable product files.

## Preserved integration failures and corrections

An initial startup test had no owned temporary parent; that fixture failure is
retained in `root-startup-1.log`. A subsequent CLI fixture used an explicit
missing preference file; the original failure is retained in `root-startup-2.log`
and the fixture now supplies a minimal valid file.

The original 100-column startup/browser/Back/explicit-retry case timed out while
waiting for a painted Pod row; the 40-column case passed. The original
`root-startup-3.log` remains a failure. A deterministic delayed public
`ScreenSuspend` delivery reproduces a connected live view with an inactive
foreground gate and zero painted rows after Back. A visible modal background
is not the foreground stack top in the pinned Textual version. Root screen
lifecycle events now use the public screen-stack top identity to reject stale
suspend/resume messages while preserving actual modal cover. The initial
`is_current` correction failed the existing modal-cover regression; that failure
is retained. Final controlled startup/root-screen/render-gate tests passed
14 cases in 8.51 seconds, with 15/15 lines and 4/4 branches in WorkspaceScreen.
This proves and fixes a concrete event-order defect without claiming the
original uninstrumented ordering was recorded.

Inspection source review found that an Events permission failure was displayed
as the error but exported as the empty-events document. Capture now selects
the same error text as the actual loaded page. Eight owned-HTTP cases verify
actual 403/404 pages, GET version/time rather than list provenance, all-namespace
header versus namespaced collection, immutable loaded documents and stale/page/
close rejection without extra reads or hidden-value eligibility.

Adding an explicit initial export root exposed a second validation defect:
the service caught every directory error and used `Path.exists()` to decide
that the default root was merely absent. Four concrete invalid-root cases
failed before the correction. A typed adapter exception now distinguishes an
actually missing component during the no-follow walk; unsafe lexical paths,
symlinks and permissions retain refusal. No following `Path.exists()` fallback
remains. The final 113-case follow-up passed, with adapter 261/261 lines and
70/70 branches, service 382/382 and 120/120, and reports 73/73 and 12/12.
New source bindings are in `storage/inspection/verification.json`.

Two full Root App flows passed in 7.53 seconds at 40×12 and 100×30. They exercise
the actual command, Escape draining, overwrite cancellation and subsequent
confirmation, private redacted resource publication, browser view/copy, deletion
cancellation/confirmation and Back with the same connected client and no extra
API reads. An initial fixture assertion used the wrong synthetic context name;
`root/integration-1.log` retains that failure. The corrected assertion names the
actual declared fixture context; `root/integration-2.log` contains the result.

Documentation/source enrollment passed 108 checks in 52.66 seconds, preserving
all earlier 348/351/354-document prefixes and adding exactly three current
records. The source now has 25 user pages (20 authored guides, four generated
references and the index); internal acceptance remains outside public navigation.
These are local build/check results, not website publication.

## Original large-history runtime result

The first full runtime parent invocation failed and was reaped after 111.16
seconds. Its positive child completed both original 5,000-record rounds with
a maximum heartbeat gap of 129.7 ms, meeting the original 150-ms budget. The
strict negative child executed its deliberate slow callback and was rejected
at 262.9 ms as expected. The separate covered child failed after 58.01 seconds
while the destination-change helper waited five seconds for a replacement
preview. This was not the 120-second child deadline. Its 258.3-ms heartbeat is
an unmet advisory measurement, not a strict timing pass.

The original parent and child trees remain in the runtime evidence archive;
they do not qualify the export change. Destination-only preview work is under
investigation. No workload, 150-ms negative control, five-second readiness
deadline, 120-second child deadline, coverage requirement or cleanup condition
has been relaxed.

Three deterministic controls then established unnecessary default preparation
on destination-only edits, replacement of the safe preview after a failed Save,
and repeated preparation after cancelling a held sensitive recheck. They failed
before the screen-only correction and passed afterward. The review now retains
one safe source preview, revokes consent and drains dependent work before
accepting destination edits. Save prepares a separate fresh transaction bound
to the actual destination, includes it in disclosure state and releases it on
every outcome. The public readiness observation checks processed fields and
drained jobs instead of requiring a needless new preview identity.

The final same ordinary cohort passed 58 cases in 40.86 seconds. Two intermediate
cohorts retained one failed fast-click fixture each: the pinned Textual Button
suppresses another pointer click during its native 0.2-second active interval.
The test interaction now waits for the observable class to clear; no production
debounce, sleep or deadline changed. A held committed sensitive transaction
also proves the screen stays sensitive while its visible preview stays redacted.
The frozen receipt is `ui/preview-reuse-evidence.json`. Corrected runtime
qualification follows separately; the original failed parent remains unqualified.

## Static and inherited-boundary evidence

Final source passed Ruff, formatting across 1,014 files, strict typing across
245 targets and the required test-private-dependency audit with zero findings.

An additional UI ownership diagnostic is not an active CI/phase gate. Its
direct-script invocation initially failed to import the `scripts` package; the
correct module invocation then reported 51 legacy private dependencies. An
owned protected-main snapshot, with byte-identical checker and Index source,
actually reported 52. Normalized path/member counts establish zero added
findings and one removed old log-save exception callback. Both diagnostic
invocations remain failures; neither is described as a pass or excluded. The
pragmatic/stable cleanup boundary remains the existing stable-readiness and
framework work, rather than a new implementation task here. Original outputs
and comparison are in `storage/ui-boundary-baseline/`. This diagnostic does not
replace or weaken any required check.

## Corrected runtime qualification

The corrected parent passed in 112.74 seconds, exit zero and reaped. The
unchanged child protocol produced:

| Child | Result | Maximum heartbeat gap | Duration |
| --- | --- | --- | --- |
| Positive | Both complete history rounds passed | 118.790 ms; met 150 ms | 21.442 s |
| Strict negative | Deliberate slow callback executed and expected failure was detected | 262.014 ms | 12.998 s |
| Branch coverage | Both complete rounds and behavior passed with CTracer | 236.128 ms; advisory instrumentation miss | 38.134 s |

The covered measurement is explicitly `timing_qualifying=false`, not a strict
latency pass. Positive and covered runs retain 5,000 records, 230 refill batches,
at most 22 records / 8,184 bytes per 8,192-byte batch and the original picker,
reopen, theme, failure and previous/current cycles. Every child reports unchanged
source; all 337 current file digests match. All process owners drained, child
PIDs are absent, and aggregate/read/watch counts are zero after App close.

`ui/aggregate-runtime-corrected-receipts/summary.json` binds the corrected
children, outputs, JUnit and coverage. The first failed archive remains intact.
This result qualifies that runtime protocol, not complete-package coverage or
the not-yet-run hosted matrix.

## Actual source and installed terminal trials

Source CLI tests passed at 40×12 and 100×30: two cases in 6.08 seconds. Fresh
wheel console/module trials outside the checkout passed two cases in 17.79
seconds. The first successful installed run used an inside-checkout basetemp;
its 16.51-second receipts remain supplemental. The separate outside-checkout
run establishes the installation boundary rather than relabelling that first run.

Every actual CLI trial uses explicit synthetic preferences, kubeconfig and a
current context with an exec-helper sentinel, plus `--readonly --command exports
--screen-dump-dir PATH`. It views a private artifact, emits redacted OSC52 bytes,
refreshes to observe a newly added entry, confirms deletion separately, returns
disconnected after Back, reopens and quits. API/helper/DNS/socket counters are
zero. A deliberate child network control is actually rejected, establishing
that the hook is active rather than inferring no network from an empty server.
Preferences and kubeconfig remain unchanged.

All four trials restore exact terminal modes, close alternate-screen/cursor/
reporting modes and drain their process groups/descriptors. Roots/home have
mode `0700`, artifact/audit files `0600`; regular fixture entries have one link,
and there are no publication-stage leftovers. OSC52 emission does not prove
that a user desktop accepted clipboard content. Terminal Save-copy interaction
is not covered; Pilot/service/file contracts cover that action.

The local wheel SHA-256 is
`6c9b6cb6a97008a7233161e55b90f82b57e547ed40aa122f138569955ad0cca3`.
All 244 packaged runtime files match the frozen source; the full 246-input
production inventory digest is
`906a08df6fbd8555fcbef2b61c4a2b6c1750697c7e52cb380f24237e6acd071b`.
`domain/exports-terminal-handoff.json` identifies the commands, source manifest,
filesystem receipts and all ANSI/kernel/offline evidence. These trials cover
Linux CPython 3.12 only. Full current-source coverage, the declared platform
matrix and protected delivery remain required. No artifact was published.

## First hosted candidate and corrections

PR #315 source `7fe5ea1606a685148ad7ec9d8e261e25c6c49d4d` passed Repository
validation 42119592737, including the site/browser checks. Application run
42119592699 failed Fast tests with 2,869 passed and two failures; the required
matrix correctly did not expand and Quality gate failed. That candidate remains
unqualified. The exact-head observer terminated/reaped with all 46 readers and
their groups drained and its lock released. Logs, annotations, JUnit and original
fast artifacts are retained under `hosted-pr315-7fe5ea1/`.

The new browser test still expected the old generic word “local” after the typed
missing-directory correction. It failed unchanged locally in 1.17 seconds. Its
test-only update now distinguishes a missing default's empty listing from an
explicitly chosen missing directory, proves noncreation, prevents path/clipboard
leaks and verifies recovery. The corrected case passed, followed by all 53 export
UI/path/actual App cases in 39.92 seconds. Production error handling was unchanged.
`ui/pr315-browser-evidence.json` retains red/green results and hashes.

The existing deferred authorization test also lost its invalid-command notice.
Controlled real App/HTTP evidence held discovery and the first Pod LIST separately:
the notice was emitted on observation A, revision one, then normal watch startup
replaced it with observation B of the same revision and painted “Loading pods…”.
The new assertion fails immediately after that controlled update, without a
timeout or an inferred replay of the unrecorded hosted ordering.

The authorization-navigation owner now retains only that failed deferred notice
for its exact session and workspace revision. New intent, namespace/session/
context changes and route departure clear it; normal same-revision observations
do not erase it. The generic presenter's notice policy is unchanged. All eight
new production lines and their guards were exercised. The final 142-case cohort
passed in 42.01 seconds, with owner coverage 190/195 lines and 57/62 branches;
existing gaps are retained. Ruff, formatting and strict typing passed. Original
traces and the boundary tests are bound in
`domain/deferred-authorization-handoff.json`. Superseded terminal receipts were
copied intact to `domain/qualified-7fe-terminal/` before new-source qualification.

## Complete fast-suite startup finding

The first complete local fast suite after those two corrections ran all 7,357
selected cases: 7,355 passed, one failed and one skipped in 385.15 seconds. The
skip is the explicit owned-hosted-macOS clipboard test; this Linux run does not
claim that platform behavior. The only failure was the 40-column offline export
startup followed by explicit retry. Its trace has an active foreground and
current root, but CONNECTING state, no snapshot and zero API requests. This is
distinct from the previously fixed stale-suspend/rendering failure.

Pinned Textual 8.2.8 source routes `InvokeLater` to the screen current at delivery;
that screen owns its after-refresh queue, which is not migrated when a transient
screen is removed. Two independent source reviews identified that callback
ownership risk. A controlled dropped-readiness notification reproduces the
observed unset Event, entered-but-not-returned connection gate and zero client/
API calls after an actual root refresh. Locally queued browser interleavings
that drained successfully are retained as passing diagnostics; they do not
establish the original unrecorded ordering.

App now owns the readiness Event and uses the existing verified foreground-resume
callback to request another after-refresh release while it remains unset.
Readiness is released after an actual refresh, never by mounting, reconnecting,
focus, a timer or a replacement signal in the test. A second controlled lost
notification followed by another modal also recovers. No extra WorkspaceScreen
change, framework-private hook or deadline adjustment is introduced.

The focused startup/root/foreground/coordinator cohort passed 18 cases in 5.63
seconds. All 30 unchanged real-PTY startup tests passed in 51.87 seconds, including
first-frame-before-SDK/network/helper order, opted-in release timing, pre-refresh
quit/cancellation, context replacement and terminal cleanup. Ruff, formatting
and strict typing passed. `domain/readiness-handoff.json` binds the source,
controls, traces and preserved failed diagnostics. The earlier full-fast result
remains a failure; the complete corrected suite and fresh source-bound runtime/
installed qualification follow separately.

The complete corrected fast suite then passed **7,358 cases**, with the same
single owned-hosted-macOS clipboard skip, in 372.73 seconds. No tests were removed
or failures ignored. The final Ruff, all-1,014-file formatting, strict 245-target
typing and zero-finding test-private audit passed. `root/ci-correction/fast-2.xml`
and `fast-2.log` retain this result; the earlier failed suite remains intact.
Fresh runtime and installed-wheel receipts must bind this changed App source
before the follow-up commit is described as locally qualified.

The fresh post-CI runtime parent then passed in 110.93 seconds, exit zero and
reaped. Positive completed both rounds at 127.693 ms (20.932 seconds); the strict
negative callback was correctly rejected at 262.383 ms (13.853 seconds). The
CTracer branch-covered child completed both rounds in 35.978 seconds; its
245.960-ms gap remains an advisory instrumentation miss and is explicitly not
timing qualification. All original record/batch/byte/cycle limits are unchanged.
All 337 file hashes match the corrected source, every process owner drained,
child PIDs are absent and registry/read/watch counts are zero after close.
`ui/aggregate-runtime-post-ci-receipts/summary.json` and `source-binding.json`
retain this result; binding SHA-256 is
`39ed0030a8e7dbf1b2a22b47466a15fe6b4ac8f7ac9cf7ac5c6307c5250377c1`.
Both earlier runtime archives remain unchanged.

Final-source export terminal qualification passed again: source at 40×12 and
100×30 ran two cases in 6.11 seconds; a fresh outside-checkout wheel ran console
and module cases in 17.75 seconds. All four retain zero API/helper/DNS/socket
attempts, active negative network controls, private file/root modes, redacted
OSC52 bytes, view/refresh/confirmed deletion, disconnected Back and exact
terminal/process/descriptor cleanup. All 244 packaged runtime files match all
246 current production inputs. This replaces no earlier receipt.

The final local wheel SHA-256 is
`7093876b3994eab58d36aaba1a3c3297a3f6b4191de675a9792a2651fe94b340`;
production inventory digest is
`24f2340486c8ac2810290d392faa852f2541979d8f6a4ebb64fa852186a0d509`.
`domain/post-ci-exports-terminal-handoff.json` and its source/filesystem manifests
bind the post-CI-prefixed ANSI/kernel/offline receipts. The prior
`qualified-7fe-terminal/` archive remains unchanged. Full-package/platform
coverage and required exact-head hosted checks still determine protected delivery.
