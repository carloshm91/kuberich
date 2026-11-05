# O05: native and external cluster diagnostics

## Source and delivery boundary

Issue #72 is the sole active implementation task. It starts from protected main
`a3f8118e6b7bf8a55948564c80e8bdeec405c1ff`, the delivered authorization tree
`dda33fb550b95592cb3ffbc031a79a85106a49a4`. Planning used the actual requested
Astra agent; implementation agents use the requested Sol workflow. The retained
plan SHA-256 is `741af817b68ec3cfd828aeff570381b51d8ab929b745c54fada13e7ff523e533`;
the scope supplement is `8a18777f08d385e37e64aca95aeaa924ab6e2c581654867f0c6e409fe721e180`.

Source remains 0.3.0 during unreleased 0.4.0 work. No application tag, package,
tap, website or DNS publication follows from these implementation measurements.
Full current-source qualification and protected delivery remain pending.

## Behavioral scope

Native `:diagnostics` collects the header namespace or all namespaces.
`:diagnose` captures a served Pod or one of seven supported workload templates
with its actual UID; its collection namespace can differ from the header.
Image-pull, scheduling, crash-loop, readiness and volume findings retain the
observed conditions/events and explain inference limits. Source failures,
partial reads, unavailable evidence and collection/report times remain visible.
No missing evidence is treated as proof of health.

`:popeye` is an explicit optional external-tool action. Exact context-local
configuration replaces global defaults. The supported report writer is pinned
to upstream 0.22.1; reports have no UID/resourceVersion and retain name-only or
unresolved identity. A current object/log link requires fresh identity checks;
report time and current creation time remain separate. Native refresh/history
does not rerun the tool. Exit code one can carry valid findings and remains a
faithful failed process outcome, without discarding a valid bounded report.

Requests own cancellation, stale-generation rejection, source acquisition and
parser/process cleanup. Native and external publication share finding/text
budgets. Cancellation retains previous evidence times under a new request;
same-scope external collection can retain native evidence without relabelling
its age. Logs opened after fresh Pod/container checks have an independent
client/session/header/UID target lifetime across same-scope diagnostic refresh.
They drain before the owning client/private connection is removed.

## Focused evidence

The frozen native/Workspace receipt is
`artifacts/issue72/workspace-integration/source-manifest.json`, SHA-256
`5c75ad621cb8e532c3a49f73037161b808779abfebd4781f47dbb73d1089cb10`.
The 198-case cohort passed in 18.24 seconds after the explicit same-namespace
intent correction. The preceding 197-case manifest remains byte-for-byte in
`before-explicit-header-source-manifest.json`, SHA-256
`2565ba68f33839a2434f6fcee2182b909954bdfcccd6e9804e5c59bf5432b3e1`.
Independent line/branch coverage:

| Module | Lines | Branches |
| --- | --- | --- |
| Native domain, diagnostic rows and producer owner | 100% each | 100% each |
| Workspace service | 98.23% | 91.38% |
| Native collector | 99.69% | 96.88% |

Held HTTP evidence exposed a charged-call accounting gap: an in-flight Event
read had consumed the second budget slot while the last published snapshot
still reported one. The regression failed before the correction. The collector
now publishes each successful charge before awaiting transport, without
changing retained evidence times or the shared read-budget implementation.

The original eight-file Popeye cohort passed 140 cases. Settings and parser
modules measured 100% lines/branches; the process service measured 117/118
lines and 15/16 branches. Actual cancellation was covered; the uncovered
defensive process-status mapping is not described as executed.

Root integration passed 27 App/config cases in 2.50 seconds with this command:

```sh
uv run pytest tests/ui/test_diagnostic_tool_integration72.py \
  tests/unit/test_observability_preferences.py -q --tb=short \
  --junitxml=artifacts/issue72/root-integration/config-tool.xml
```

This covers actual configured helper execution through the production process
service, a valid exit-one report, native evidence/time carryover, per-context
tool replacement, explicit missing-tool state, no automatic tool run during
refresh and read-only refusal before the version probe. The initial integration
test used a nonexistent test-side `directory_path` attribute; the corrected
test observes the client's actual owned temporary directory. This was a test
fixture correction, not a production execution failure.

## Inherited viewport failure

Automatic main run 42039539793 failed Python 3.14 job 127288930908 after the
prerequisite merge. The original delayed relationship-Back case retained mode,
expansion, filter and selection but lost horizontal/vertical viewport offsets.
Its result remains unqualified; no unchanged retry is used as a correction.

A public native geometry regression at horizontal offset nine failed before
the minimal X-watcher guard correction. All 18 widget cases then passed, with
186/186 lines and 56/56 branches. Scoped lint, formatting, strict typing and
private-access checks passed. The original CI callback order was not logged;
the deterministic guard defect is proven without claiming that exact order was
replayed. Frozen prerequisite source is unchanged. Fresh App and hosted checks
must qualify the active correction.

## Remaining qualification

The first actual App keyboard cohort exposed a real focused-text binding
conflict: the current-log `l` action was consumed by horizontal text navigation.
The 40-column previous-log case passed; the 120-column current-log case timed
out without opening a log HTTP request. The evidence viewer now reserves that
action while keeping Right-arrow scrolling. The original test also selected a
waiting crash-loop container whose native evidence correctly permitted only
previous logs; the current-log case now uses an actual running, not-ready
container and its container-specific readiness finding. No native mode rule was
loosened. Original public binding-map and failed-test evidence remain retained.

The expanded App/UI/actions/navigation/log/relationship cohort passed 146 cases
in 74.30 seconds. Its new five UI modules measured 621/625 lines and 175/180
branches; the table/controller each reached 100% independently. This also covers
the original failing relationship navigation file and existing log-viewer cases.
The source manifest is `artifacts/issue72/ui/source-manifest.json`, SHA-256
`fb15f2128d931f31283155dea1e8e3f84fcef445b6fe0049a8bb4c8e7f95bf82`.
It explicitly qualifies source before the subsequent namespace-intent correction.

The fresh post-review cohort passed 162 cases in 93.72 seconds after all scope,
expected-error and cleanup corrections. Its manifest is
`artifacts/issue72/ui/post-review159/source-manifest.json`, SHA-256
`53b9628a1a34eefa8181c4fcef69bcfd63429e7cc6bc53c24f490366342a9366`.
All 232 production modules and captured test inputs matched after execution.
New UI modules measured 622/626 lines and 175/180 branches, with independent
table/controller coverage at 100%. Scoped lint, formatting, strict types and
the repository private-access check passed. The older 146-case receipt remains
unchanged and does not claim this later source.

Independent review found that an explicit same-namespace selection cleared the
root without advancing session generation. The red-first regression and narrow
correction now establish fresh final-session binding and invalidate previous
captured targets; same-scope refresh continues to preserve an already opened log
target. The fresh source-bound Workspace cohort above includes this correction.
Subsequent App command/picker cases also passed, before whole-source qualification.

Real HTTP 403/404 and timeout action tests exposed expected connection problems
escaping fatal UI worker handling. The action boundaries now handle only
application-owned `AppError` and `ConnectionProblem`, retain the diagnostic view
and allow recovery. The Root object-open notice additionally checks that its
original request is still active. Unexpected failures remain errors.

Root object and evidence-action workers now join client-close draining before
private connection files are removed. Held Root GET/context replacement and held
evidence GET/priority Retry scenarios verify the worker has drained while the
old private directory still exists, followed by its removal and a usable new
session. Parent evidence invalidation does not stop an independently captured
same-scope log viewer. Seven Root App cases passed in 5.20 seconds and ten new
UI scope/error/lifecycle cases passed in 12.03 seconds.

The final cleanup regression exposed cancellation masking an unexpected cleanup
failure after all owners had drained. Cleanup now reads and inspects every
gathered result before re-raising the caller's original cancellation. A second
red regression found an unawaited constructed coroutine when a queued Root
action was cancelled before execution. Passing an async callable creates that
coroutine only when the framework starts it. No PENDING-state exception was
reproduced, and the equivalent evidence ordering already passed; no speculative
framework fix was added. All three cleanup cases and seven Root cases passed
in 7.47 seconds. The immutable receipt is
`artifacts/issue72/client-cleanup/source-manifest.json`, SHA-256
`880c65341aca80edf32a8e8a56876f0c1e296f7bac68de9c18a38bbbb8153ca6`.
Original reds and the first development correction's wrong assumption that
`finish_owned` returns a value remain retained; the current implementation
drains that helper and retrieves the actual future result.

## Actual owned-cluster and official-tool qualification

The canonical verifier ran with checksum-verified kind 0.33.0, the existing
pinned Kubernetes 1.36.4 node image, an explicit Unix Docker executable and the
official Popeye 0.22.1 binary acquired by `scripts.diagnostics_tools`. Popeye
never executed on the host. The contained Python runtime used its own account
home; discovery caches were created only there and disappeared with its owned
container. The official tag is unsigned; no signature attestation is claimed.

Trial one passed eight runtime scenarios in 48.882 seconds. It exercised all
five native categories, UID-linked Events, actual previous/current log reads,
Deployment/ReplicaSet/Pod, Job/Pod and CronJob/Job/Pod chains, denied Event/PVC
sources, same-name UID replacement, exclusion of historical old-UID Events,
old-request/client invalidation and draining, native carryover and shared budgets
around explicit real Popeye namespace/all-namespace runs. The external API read
count remains unknown.

The trial's `artifacts/issue72/popeye-actual/trial1/evidence.json` confirms all
239 captured inputs unchanged, owned container/cluster/private-directory
deletion, unchanged caller kubeconfig/environment and unchanged unrelated
container inventory. The actual report and provenance metadata are retained
alongside it. The official binary SHA-256 is
`a9af3fd43bffbf3b4099e68a18e9b1c6a8c1ec735d33390d5fe61ddbb0ffab11`.
Source changes or a tool-pin change require fresh qualification; synthetic and
actual goldens do not replace that runtime trial.

Final global formatting changed only tuple layout in the diagnostic filtering
projection. Its AST matched the original source, but its bytes changed, so the
prior trial/UI receipt was not relabelled as current. A fresh actual trial two
then failed its first category assertion after an independent raw readiness
read. The original missing normalized category was not recorded; no exact Pod
transition or product defect is claimed. Container, cluster, client files and
caller state were still cleaned/preserved, and the failed evidence remains.

The verifier now waits for all five categories in one completed native snapshot,
recording that snapshot before checking it. It accumulates no categories across
snapshots and keeps the same 150-second bound. Controlled regressions cover the
old separate-read assertion, incomplete/complete snapshot sequences, deadline
and in-progress rejection. Only the runtime verification script changed after
trial two; all 232 product modules remained unchanged.

Fresh trial three passed eight runtime scenarios in 87.139 seconds with all
239 inputs unchanged and complete owned cleanup/caller-state preservation.
Its current-source receipt is
`artifacts/issue72/popeye-actual/trial3/evidence.json`. Trial one and its actual
golden remain byte-for-byte; failed trial two is not counted as qualified.
Required hosted whole-source/platform checks qualify the final formatted tree.

## Hosted-check corrections

Initial PR #314 source `aef8e86` received two CodeQL annotations for substring
matching of Event API paths in HTTP test fixtures. The fixtures now compare the
exact served API paths; all 27 native service contracts passed. No analysis rule
or required check was disabled. CodeQL passed on follow-up source `3ce31f7`.

The complete Fast job for that follow-up then found a fresh-process import
regression: importing the root App eagerly loaded the evidence text viewer and
Textual's document/editor modules. The matching local regression failed before
the fix. Diagnostic navigation now imports the evidence screen only after a
real selected finding, and log-mode helpers load only for explicit log actions.
Annotations use TYPE_CHECKING imports. Public interfaces and policies are
unchanged. All 124 related import/App/navigation/action/evidence/cleanup cases
passed in 70.04 seconds, with strict types, lint, format and private-access checks.
The receipt is `artifacts/issue72/ui/lazy-import-ci-fix/source-manifest.json`,
SHA-256 `846176c827041da96c75cc665ef5c6b3d7794206770430596637509cd17e1bba`.

Earlier local trial/UI receipts retain their exact source hashes and are not
relabelled after these import changes. The fresh required hosted run must
qualify the current whole source, packaging/platforms and actual owned-cluster
verifier. No unchanged failed-head retry is used.

Whole-source coverage, packaging and exact-head hosted platform checks are
still required before protected delivery. Focused and owned-cluster evidence
above does not replace them. Only synthetic
local HTTP fixtures and explicitly owned disposable clusters are authorized;
real provider certification remains opt-in in #87.
