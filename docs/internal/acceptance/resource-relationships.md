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
correction. A fresh owned-kind trial and complete final-head hosted checks remain
required; no cross-source coverage reports are combined.

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
- Complete current-head hosted checks remain required. Earlier run 41980688756
  failed Fast on the premature lifecycle assertion; its downstream gate failed.
  Repository and DCO passed. All failed logs/inventories and 22 reaped reader
  receipts remain in `artifacts/issue70/hosted-pr312-cd4f026/`. Current-head
  platform/terminal/package and final native-install qualification remain
  separate; no passing full local rerun or platform certification is invented.

No cloud/provider trial or ambient Kubernetes context is used by the focused
checks above. Pending work is not delivered acceptance, and baseline #69 results
are not relabelled as #70 qualification.
