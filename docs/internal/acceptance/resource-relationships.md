# O03 #70: native resource relationships and UsedBy

## Source and qualification boundary

The selected implementation starts from protected main
`55e5937d955b91a283924650432b54ff2a0a5fc1`, which delivered #69 through PR #311.
That baseline passed all 27 selected PR jobs, Repository checks and DCO;
independent coverage measured 98.7960% lines, 95.9154% branches and 99.57%
changed lines, with all 86 critical modules passing. Its second hosted attempt
recovered a GitHub artifact DNS `ENOTFOUND` failure after a separate supported
ambiguous-Job test-timeout correction. Those results qualify the #69 baseline,
not this later #70 source. The baseline's automatic-main application run
41973484821 passed all 22 jobs; Repository run 41973485184 also passed.

Source metadata remains 0.3.0. This is unreleased 0.4.0 work. No version bump,
tag, package, website, domain or DNS publication is part of this implementation.

## Implemented contracts

The graph carries exact root identity separately from the selected search
namespace. It resolves custom owner GVKs through discovery, excludes served
version from object identity, checks expected UIDs, and preserves invalid owner
scope, replacement, missing and denied states. Path-local cycles remain
separate from shared descendants. Supported native selectors retain full
structured expression semantics and do not borrow the CLI's eight-term limit.

Pod and seven workload template families, including zero replicas and CronJobs,
provide static ConfigMap, Secret, ServiceAccount, PVC and PriorityClass
references. ServiceAccount, PVC and PV source families are also scanned.
Explicit volume/CSI fields, default service accounts, optional flags and known
ObjectReference UIDs remain explainable without retaining values. A valid
explicit endpoint/PV namespace is not rejected by owner-reference scope rules.
Unknown consuming-Pod scope for implicit PV AzureFile Secret namespaces stays
incomplete. Arbitrary CR reference discovery and proof of process consumption
remain unsupported.

Read-only graph navigation, ordered visible expansion rows, independent
per-source coverage and minimal history bookmarks share the normal workspace.
Graph/source rows are not mutation targets. `:xray`, `:usedby`, explicit
`:open`/`o`, expansion, filtering and Back/Forward integration are being
qualified through the actual App; focused widget tests alone do not establish
that integration.

## Scoped evidence recorded during implementation

| Component | Measured result | Limit |
| --- | --- | --- |
| Pure domain and declaration extraction | 133 cases passed in 8.64 seconds; relationships 355/355 lines and 118/118 branches; reference fields 152/152 lines and 100/100 branches | Focused unit selection, full-package coverage inventory, no exclusions |
| Native widget/controller | 11 focused UI cases passed in 12.27 seconds; widget 158/158 lines and 52/52 branches, controller 24/24 lines, no branches | Isolated widget/controller contracts; actual App integration remains separate |
| Collector/read-budget regression cohort | 166 combined regression cases passed; focused selection contained 40 cases; read budget measured 100% | Cohorts overlap and must not be added together |
| Collector independent coverage | 312/322 lines and 115/124 branches | These are separate line and branch measurements; combined 95.74% is not either independent metric |

A Pilot regression first reproduced source rows displaying the outer snapshot's
later publication time. The corrected widget uses each source's `observed_at`
or explicit unavailable time; root rows retain the outer observation time.
The original failing and corrected evidence remain in
`artifacts/issue70/ui-source-time-before.log`, `ui-source-time-after.log` and
`ui-source-time-coverage.json`. The earlier ten-case cohort overlaps this
selection and is not added to it.

The final pure evidence is retained in
`artifacts/issue70/domain/coverage-final-qualified.json`, with frozen-source
hashes and exact counts in `qualified-receipt.json`. The command was:

```sh
COVERAGE_FILE=artifacts/issue70/domain/.coverage uv run pytest tests/unit/test_relationships.py tests/unit/test_reference_fields.py -n 0 --cov=kuberich --cov-branch --cov-report=json:artifacts/issue70/domain/coverage-final-qualified.json --cov-report= -q
```

Ruff, formatting and strict mypy passed for both new pure production modules.
The private-access check found two collector-test uses of a private extractor;
those were reported for correction. It is not recorded as a passing whole-head
check at this checkpoint. Earlier focused measurements remain separately
retained and do not replace final current-head verification.

## Documentation checkpoint

The authored relationship guide, ADR0034, architecture/workflow/navigation links,
preview and capability summaries are enrolled. The documentation plan preserves
all 345 protected-baseline disposition records and appends exactly three sources;
105 preserved-source records, 100 relocations and three operational-source records
remain unchanged. The one new authored page accounts for the exact 21-to-22 page
budget change; a single additional page still fails the limit.

The structural/history/architecture selection passed 42 cases with five
build/reference-dependent cases deferred. A separate real selected-source binding
mutation passed in 3.58 seconds: changing `RelationshipTable.BINDINGS` changed the
isolated generated contract and both rendered reference surfaces. The generator
reads the real owner rather than a duplicated list of keys. Plan validation passed
with 939 local Markdown links; Ruff, formatting and strict documentation-helper
typing passed. These scoped selections overlap later qualification and must not
be added to a combined total.

After the command catalog became coherent, the official generator refreshed the
checked-in references from actual `xray`, `usedby`, `open`, App `o` and relationship
table declarations. The complete focused documentation/site cohort passed
142 cases in 91.20 seconds. Its command and retained evidence are:

```sh
uv run python -m scripts.site_reference --write
uv run python -m scripts.site_reference
uv run pytest tests/quality/test_documentation_structure.py tests/quality/test_documentation_checks.py tests/quality/test_internal_docs.py tests/quality/test_architecture_docs.py tests/quality/test_site.py -n 0 --no-cov -q --junitxml=artifacts/issue70/docs/focused.xml
uv run python -m scripts.check_documentation --report artifacts/issue70/docs/documentation-report.json
```

The complete test output is `artifacts/issue70/docs/focused.log`. Source checks
passed; editorial observations remain advisory. Earlier selections overlap this
cohort and are not added to it. This is documentation qualification; no deployment
or browser/platform result is inferred from it.

## Remaining guide-census correction

The initial whole-source campaign retained **4 failed, 8,088 passed and five
skipped** out of 8,097 cases in 1,220.74 seconds. Two failures came from
`tests/quality/test_user_guides.py` still expecting 21 total/rendered pages after
the enrolled relationship guide raised the exact census to 22. Its authored-guide
expectation also needed to move from 16 to 17; four generated references remain.
The original campaign remains failed, with evidence in
`artifacts/issue70/full/pytest.log` and `cases.xml`.

Only these exact census assertions changed. The strict 22-page structural limit,
existing rejection of one additional page, source-derived reference generation,
redirect/deep-link checks and byte-exact historical assertions remain in force.
The whole user-guide test file then passed **20 cases in 21.06 seconds**; Ruff and
format checks also passed. The command was:

```sh
uv run pytest tests/quality/test_user_guides.py -n 0 --no-cov -q --junitxml=artifacts/issue70/docs/user-guides-census.xml
```

Output is retained in `artifacts/issue70/docs/user-guides-census.log`. This focused
correction does not qualify the other original failures or turn the failed
whole-source campaign into a pass. Production source and coverage policy did not
change, and no additional whole-suite run is claimed here.

## Actual App and disposable-cluster checkpoint

The real App/owned-loopback cohort passed 16 cases in 22.62 seconds. It covers
native tree keys, all five UsedBy roots, exact served-version/observed-UID opening,
same-name replacement refusal, delayed graph restoration with exact viewport,
namespace changes, cancelled old-context reads and a newer Pulse intent superseding
pending history. Earlier failures and corrected receipts remain under
`artifacts/issue70/ui-navigation-*`; the final cohort is
`ui-navigation-completion-guard.{log,xml}`. Progressive graph publications must
finish before consuming a saved viewport, while collection ownership remains
explicitly distinct from an active collection.

The first owned Kubernetes trial passed in 38.026 seconds (37.232 seconds inside
the verifier), using verified kind 0.33.0, local Docker and the pinned Kubernetes
1.36.4 image. All 217 captured production/configuration/verifier input hashes
stayed unchanged. The command was:

```sh
uv run python -m scripts.verify_relationships_kind --kind /home/develop/projects/personal/kubetrol/artifacts/qualification-tools-linux-amd64-ewfuxtag/kind --docker /usr/bin/docker --evidence artifacts/issue70/kind-final-1/evidence.json
```

Nine actual checks covered owner UID chains and placement, generated Slice target
UIDs, selectorless address-only endpoints, five UsedBy targets across all seven
zero-replica/suspended workload template families, bound PV/PVC claim UIDs,
discovered custom owners and recreated custom-root rejection, restricted RBAC,
native App expansion/open/history/viewport/UsedBy, actual API paths and unchanged
private kubeconfig. The restricted reader retained ten forbidden source states
and two ready states without claiming unused. The trace contains 194 adapter
reads; two native SVGs, append-only stages, process receipts and separate logs
are retained in `artifacts/issue70/kind-final-1/`.

Cleanup verified zero App owners, completed close, absent owned cluster and
deleted private directory. Only generated local fixtures were used. This proves
the recorded owned-cluster behavior; it does not certify a cloud provider or a
whole-process memory bound. Complete current-source/global/platform verification
remains pending at this checkpoint.

## Bounds and completeness

One graph shares depth 8, 512 visible rows, 1,024 edges, 10,000 input items,
16-MiB retained input and 64 logical Reader calls. Pages and 410 restarts charge
the same request budget. A 30-second collection deadline and smaller pure
fact/text/selector limits also remain explicit. Cached branch expansion and
collapse retain the remaining per-root budget; refresh begins a new collection.
Source time describes an actual family read, not the last graph publication.

The Reader's existing 401 credential refresh can retry a logical call once,
allowing up to 128 underlying API attempts. Discovery and authentication helper
traffic have independent existing limits. These bounds are not a universal
network or process-memory guarantee. Missing/denied/truncated families and invalid
supported fields prevent an unqualified unused claim. Even a complete scan
covers only the supported declarations and selected search scope.

## Final qualification checkpoint

A later review found one production boundary defect: a valid long Node name
could exceed KubeRich's 256-character selector grammar after adding
`spec.nodeName=`. Kubernetes requires [DNS subdomain Node names](https://kubernetes.io/docs/concepts/architecture/nodes/),
whose [limit is 253 characters](https://kubernetes.io/docs/concepts/overview/working-with-objects/names/#dns-subdomain-names).
The original regression retained one boundary pass and one maximum-name failure.
The correction falls back to the same namespace-scoped, budgeted collection and
keeps exact `spec.nodeName` matching; it does not raise selector or retention
limits. The 242-character name still uses its representable 256-character server
selector; the 253-character dotted name uses the bounded fallback. A nearly
identical Node assignment and an unassigned selector-matching Pod are excluded.
Both cases retain complete source state and exactly two logical Reader calls.
The collector/read-budget cohort passed 44 cases in 2.32 seconds. Original and
corrected evidence is in `artifacts/issue70/node-name-boundary/`.

Earlier `cd4f026`/`bd98e00` measurements below do not qualify this later production
correction. The fresh owned trials are recorded below; complete final-head hosted
checks remain required. No cross-source coverage reports are combined.

The related cycle review reproduced two identity defects before correction:
Node→Pod→a name-only Node reference stayed READY on the first repeat, and an
inner name-only PVC→PV→PVC cycle lost its observed UID. Cycle classification now
uses the resolved child identity, and recursion carries observed ancestors.
Published name-only declarations keep their unspecified expected UID; a
REPLACED/error result takes precedence and sibling branches remain independent.
The original two failures and passing REPLACED control are retained alongside
the corrected 180-case cohort in `artifacts/issue70/observed-cycles/`.
The collector independently measured 326/337 lines (96.7359%) and 118/128 branches
(92.1875%); the three pure modules remain at 100%. Ruff, formatting and strict
collector typing passed. This focused measurement is not a full-source pass.

The second owned trial qualified the long-Node correction at `aaf7210` in 37.466
seconds; the final trial qualified both collector corrections at `a851a81` in
38.326 seconds (37.566 seconds inside the verifier). All nine actual checks
passed again, including native App history/viewport and restricted RBAC. The 217
captured production/configuration/verifier inputs stayed unchanged; the owned
cluster/private directory were deleted, the wrapper reaped its worker and the
process group was absent. Receipts, stages, API traces and native SVGs are in
`artifacts/issue70/kind-final-2/` and `kind-final-3/`. These are intentional trials
after production changes; earlier successful and failed outcomes are retained.

The preceding test-only head `bd98e00` passed all 27 jobs in run 41983206631,
Repository run 41983206655 and app-bound DCO. Its observer reaped 266 readers;
two transient metadata HTTP 503 results were preserved and recovered on the next
scheduled read. This establishes that earlier baseline, not the collector fixes.
Final required-check status and source binding are authoritative in
[PR #312](https://github.com/carloshm91/kuberich/pull/312/checks) and its linked
delivery closeout; a queued, cancelled or preceding-head run is not qualification.

Head `9910803` then exposed a real deferred-scroll race on macOS: UsedBy Back
restored every saved viewport field except horizontal x (0 instead of 9).
Run 41989945789 retained 21 successful jobs, the failing macOS part and its
downstream gate; the Application matrix did not qualify. Original logs and
compatible annotations are in `artifacts/issue70/hosted-pr312-9910803/`; all 151
observer/supplemental readers were reaped. This is not treated as a transient
platform failure or retried unchanged.

A controlled public widget test reproduced the same x-only loss: another render
replaced the scheduled desired viewport with the still-current x=0 before its
callback ran. Geometry was identical (max x 16, virtual size 74×61, viewport
60×12, column widths 17/6/19/24); the separate actual App geometry trace also
ruled out width padding as the correction. Pending viewports now survive
coalesced renders and yield to actual selection and horizontal/vertical user
changes. Native deferred cursor revelation uses the public region-scroll port
with synchronous geometry so it does not masquerade as a manual vertical
interaction. The original manual-y failure and unsuccessful naive symmetric
watcher are retained; exact Back/Forward viewport assertions are unchanged.

The final affected widget/App cohort passed 34 cases normally and with coverage;
the widget measured 186/186 lines and 56/56 branches, and its controller 24/24
lines with no branches. Ruff, formatting, strict widget typing and private-access
checks passed. Evidence is in `artifacts/issue70/viewport-pending-*` and
`viewport-vertical-*`. Fresh final-source owned and hosted qualification is
required; earlier successful runs do not qualify this later widget correction.

The fresh owned trial at `95668bd` passed all nine checks in 36.821 seconds
(36.003 seconds inside the verifier), including actual native expansion,
resource opening and exact history viewport restoration. All 217 inputs stayed
unchanged, the owned cluster/private directory were deleted, and the worker and
process group were absent after cleanup. Evidence is retained in
`artifacts/issue70/kind-final-4/`. Final-head hosted status remains authoritative
in the linked PR checks; previous-head successes are not substituted for it.

- Actual App/controlled-HTTP and disposable-kind behavior are recorded above.
  The corrected App cohort adds successful cross-context Back and passes 17 cases
  both normally and with coverage. The original UsedBy failure happened before
  Back: the test treated a matching request and completed backend as a committed
  filtered table. A held public controller reproduced the absent path. Tests now
  wait for actual rendered path keys/DTOs and post-filter ancestors; exact
  viewport assertions remain unchanged. Evidence is
  `artifacts/issue70/app-render-readiness-*`.
- The new lifecycle test also confused interim LIVE with collection completion.
  Its corrected waits use `relationship_collecting`; intentionally held/cancelled
  observations remain interim. The related cohort passed 121 cases in 7.34
  seconds. Evidence is `artifacts/issue70/workspace-waits-fixed-1/`. These focused
  selections overlap earlier runs and do not make the original four-failure
  campaign pass. No production file changed for these corrections.
- The original complete coverage campaign and successful instrumented replay
  measured 21,834/22,114 production lines (98.7338%), 6,426/6,700 branches
  (95.9104%), 89 critical modules at 100% and 1,353/1,382 changed executable lines
  (97.90%). Original reports/log/XML/data are preserved in
  `artifacts/issue70/full-original/`; measured gate/runtime merge records are in
  `artifacts/issue70/full/` and `artifacts/ui/`. Five local skips require owned
  native Homebrew or macOS workflows; they are not local passes.
- Ruff, formatting, private access and the actual 253-module strict workflow
  type union passed. Fresh startup contracts passed with offline RSS at most
  22,020,096 bytes. Five full-frame paint samples measured 802.97–830.29 ms,
  retaining the missed advisory 600 ms target. Offline/import targets were met,
  both strict negative controls rejected their deliberate violations, and no
  latency policy was changed. Exact receipts are in
  `artifacts/issue70/startup-final-cd4/`.
- Complete current-head hosted checks are required. Earlier run 41980688756
  failed Fast on the premature lifecycle assertion; its downstream gate failed.
  Repository and DCO passed. All failed logs/inventories and 22 reaped reader
  receipts remain in `artifacts/issue70/hosted-pr312-cd4f026/`. Current-head
  platform/terminal/package and final native-install qualification remain
  separate; no passing full local rerun or platform certification is invented.

No cloud/provider trial or ambient Kubernetes context is used by the focused
checks above. Pending work is not delivered acceptance, and baseline #69 results
are not relabelled as #70 qualification.

## Later hosted provisioning and Pulse fixture failure

The final production source at `b5eb1d0` passed every macOS behavior part,
including the original exact horizontal/vertical viewport assertions. Its first
attempt of run 41998508032 stopped two Linux parts before tests because the
pinned Python asset downloads returned HTTP 504. The retained failed jobs and
subsequent successful HTTP HEAD checks justified one targeted failed-job and
dependent-job retry without changing source; the original attempt remains failed.

Attempt two then passed all 16 behavior parts, all four standalone targets and
three Application environments. Ubuntu Python 3.13 measured 21,863/22,143
production lines (98.7355%), 6,425/6,700 branches (95.8955%) and 1,384/1,411
changed executable lines (98.09% displayed); every one of the 89 critical modules
passed its independent 100% line/applicable-branch gate. These measurements bind
to that exact production source and do not make the complete run pass.

The remaining Ubuntu Python 3.12 Application job failed the existing Pulse
owned-cluster verifier with an assertion at
`checking-all-exact-resource-drilldowns`. The artifact retained five expected
Pods and successful owned-cluster/private-directory cleanup. It did not retain
the exact failing row, so no particular controller transition is claimed as
proven. The verifier waited only five counters before checking all 44 rows
against later independent API reads; other controller and Pod classifications
could still change. The original run, safe Pulse JSON and artifact ZIP are
preserved in `artifacts/issue70/hosted-pr312-b5eb1d0-attempt2/`.

Five controlled regressions reproduced that readiness weakness: the original
five counters were satisfied while ReplicaSet, StatefulSet, DaemonSet or Pod
counters differed from the proposed complete fixture state. Their original failures
are preserved in `artifacts/issue70/pulse-readiness-red/`. No unchanged retry
is used to establish a correction.

The complete oracle was independently compared with the retained successful #69
owned-cluster result. That comparison corrected an overbroad proposed
DaemonSet expectation: the API omits optional zero counters, and the current
classifier honestly reports unknown. The oracle preserves that observation;
production classification was not changed. Four meaningful bootstrap transition
controls remain, and a separate positive test preserves the zero-desired
DaemonSet's unknown state. The final focused file passed 26 cases in 0.98 seconds;
Ruff, formatting and strict verifier typing also passed. Receipts and frozen-file
hashes are in `artifacts/issue70/pulse-readiness-green-corrected/`.

The corrected verifier requires every one of the 44 expected counts and all
eight complete, available, non-limited family sources. It records overview
observations and each actual drilldown's count, identity, selector, resource
version and collection state before enforcing completeness and the unchanged
exact equality. A partial LIST with a coincidentally matching count fails.
The original 180-second convergence deadline remains; mismatched drilldown counts
are never retried or rebased.

An initial local trial was started prematurely with the overbroad DaemonSet
oracle, then explicitly interrupted before the correction. Its source stayed
unchanged, its owned cluster/private directory were deleted, and its worker and
process group were reaped/absent after 61.472 seconds. This remains an
interrupted result in `artifacts/issue70/pulse-readiness-kind/`, not a pass.
The corrected source uses a separate fresh evidence directory.

The fresh corrected-source Pulse trial passed all 10 actual checks and
all 44 exact complete-list drilldowns in 104.959 seconds
(104.160 seconds inside the verifier). The genuinely scraped
Prometheus history, native navigation and restricted-permission checks also
passed. All 217 captured inputs stayed unchanged, the owned cluster and
private directory were deleted, and the worker/process group were reaped/absent.
The 25 readiness observations, safe pre-assertion drilldown receipts and
final process/source evidence are retained in
`artifacts/issue70/pulse-readiness-kind-corrected/`. No production file changed;
all 217 inputs of the successful final relationship trial still match. Final
complete hosted qualification on the resulting head remains authoritative in
the linked PR checks; this local correction does not relabel previous failures.
