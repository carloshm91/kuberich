# O04 #71: authorization reviews and RBAC evidence

## Selected scope and baseline

The implementation starts from protected main
`64817677c20aad876489f81427a7636f0c56cc6c`, which delivered relationships through
PR #312. Its tree `e5867f0a4692dd6029e2d41504ec4c710e4604e3` exactly matches
the tested feature head. Live protected checks, parent, maintainer Gmail and
sign-off, issue acceptance and roadmap completion were verified before advancing.

That preceding head passed all 27 selected Application jobs in run 42007955008,
Repository run 42007954856 and app-bound DCO. Ubuntu Python 3.13 measured
21,862/22,143 lines (98.7310%), 6,424/6,700 branches (95.8806%) and
1,384/1,411 changed executable lines (98.09% displayed), with 89 critical modules
at 100%. These measurements qualify that baseline, not later authorization code.
Automatic-main run 42013471990 later failed one Ubuntu Python 3.14 part-four
case: the unexpected-render-fault test's real mouse click on Retry returned
false after fault state was published. The run retained 17 successful jobs;
its Application matrix did not qualify. Original job 127200848093 and its cached
log remain in the prior issue's `main-6481767/` evidence. The UI owner corrects
the actual hit-test/readiness contract within this issue, retaining mouse,
sanitized-hook and cleanup assertions. No unchanged main retry is used.

The frozen Astra planning contract remains in ignored artifacts with SHA-256
`06257a476d456cea7c8fd092a2ac99a373b70f08a49e273eb1fae7d94c907f54`.
Parallel ownership within this one active issue separates pure domain behavior,
service/HTTP/workspace, UI/commands/history, and root integration/documentation/
owned-cluster verification. No separate product issue is implemented concurrently.

## Behavior under implementation

The selected scope covers observed subjects, Roles/ClusterRoles and bindings,
current-identity review, individual SelfSubjectAccessReview, namespace
SelfSubjectRulesReview, bounded local who-can and aggregate contributor evidence.
Native routes and explicit UID-safe object opening share the existing frame.

Header and question scope are independent. Cluster resource/non-resource request
modes retain cluster intent/access scope on a namespace-header change; namespaced
questions rescope both fields together. ServiceAccount identity is preserved.
History restores both scopes atomically and recollects current evidence.

Pure authorization DTO/matching/row/command modules join the existing independent
100% critical-module gates. Existing line, branch, changed-line, ownership,
effect guards and full platform gates remain. Scope budgets, request canonical
names and honest partial/unknown semantics follow the
[authorization decision](../../adr/0035-authorization-evidence-and-reviews.md).

## Evidence status

Scoped pure, service and native UI evidence is recorded below. The first actual
owned-cluster trial passed; complete whole-source/platform qualification remains
required. Earlier focused measurements and retained failures keep their source
boundaries; no whole-package result is inferred from them.

Only synthetic fixtures and owned disposable contexts are authorized. Real
provider trials remain opt-in in #87. Source version remains 0.3.0 during this
unreleased 0.4.0 implementation; no package, tag, website or DNS publication is
part of the issue.

## Canonical literal-selector correction

Independent review compared name derivation to the pinned Kubernetes
[field parser](https://github.com/kubernetes/apimachinery/blob/v0.36.4/pkg/fields/selector.go#L390-L425).
The shared local parser normalizes whitespace that the server preserves.
Deriving `demo` from `metadata.name =demo` would describe a different request.
The new controlled regression originally retained 24 failures and one valid
literal-selector pass against the earlier pure module; evidence is in
`artifacts/issue71/literal-field-selectors/red/`.

Authorization now rejects unsupported field whitespace before POST, preserving
all valid literal selectors and existing other-verb name behavior. Label-selector
whitespace remains accepted. No shared ResourceQuery grammar or broad-scan
fallback changed. The combined pure cohort passed 215 cases in 9.48 seconds:
authorization 321/321 lines and 90/90 branches; RBAC matching 252/252 lines and
128/128 branches. Scoped Ruff, formatting and strict authorization typing passed.
The scope and complete raw coverage inventory remain in
`artifacts/issue71/literal-field-selectors/green/`; this is not a full-package
coverage or actual-Kubernetes result.

## Integrated actual Kubernetes trial

After all three source owners explicitly froze, Root verified 44 source/test
manifest entries and its own canonical-selector correction before execution.
The first actual owned-kind trial passed all seven scenario checks with 167
observed API calls in 39.082 seconds
(38.230 seconds inside the verifier). All 226 production,
asset, configuration and verifier inputs stayed unchanged. The owned cluster and
private directory were deleted, the worker was reaped and its process group was
absent. Kubeconfig and environment bytes/state were unchanged.

The trial uses actual ServiceAccount TokenRequest credentials in two namespaces,
authoritative SSAR allow/no-allow questions and real API name selectors. It
verifies materialized aggregation, reviewed current-group membership and another
user's uncertainty, partial forbidden lists with named recovery, forbidden
review/impersonation without credential fallback, confirmed application-policy
write blocking and actual restricted PATCH denial with unchanged UID/manifest.
Native App modes, drilldowns, filters, exact history, atomic namespace scope,
UID-safe Open/replacement refusal and context cancellation also pass.
The literal spaced field selector really returns HTTP 400, while the corrected
public request refuses it before a POST; no normalized alternative is submitted.

The exact invocation, stages, safe API receipts, native SVGs, input hashes and
process/cleanup records are in `artifacts/issue71/kind-trial-1/`. Its child uses
this worktree's Python 3.12.12 and pinned kind/node images, with no ambient
context. No package, tag, website or DNS publication occurred.

## Scoped component and visual evidence

The service owner's final cohort passed 350 cases in 9.49 seconds; its related
workspace/resource/session/proxy cohort passed 170 cases in 12.91 seconds. These
selections overlap other evidence and are not added to a combined total.
Independent coverage measured service 319/319 lines and 102/104 branches
(98.08%); scoped workspace 65/65 lines and 11/12 branches (91.67%); critical
ViewStore 193/193 lines and 78/78 branches (100%). Scoped lint/format/types and
private-access checks passed. See `artifacts/issue71/service/frozen-summary.json`.

The UI owner's frozen 804-case cohort passed in 68.39 seconds. Native table
113/113 lines and 34/34 branches, controller 26/26 lines/no branches, pure
commands 126/126 lines and 70/70 branches, and rows 133/133 lines and 64/64
branches measured 100%. Existing critical command/navigation/routes/actions
remain at 100% independently. Scoped navigation measured 182/187 lines (97.33%)
and 53/58 branches (91.38%). Twenty-four actual App and six native-widget cases
are included, not additional totals. Whole-source mypy, private access and scoped
Ruff/format passed; source hashes are in `artifacts/issue71/ui/frozen-manifest.json`.
The inherited Retry correction waits for actual public compositor hit testing;
the real mouse click, sanitized-hook and ownership/cleanup assertions remain.

Root rendered the actual synthetic role SVG in owned headless Chromium with
external requests blocked, closed the browser and inspected the PNG. Native
frame, scope/status and selected rule are visible. Long identities push details
beyond the initial viewport; ordinary horizontal navigation remains available.
Header-label export and compact row/column density stay explicit final-UX
review items with the preceding observability views in #75. Source screenshots
and the precise visual observation are in `artifacts/issue71/kind-trial-1/`; no
customer data or website publication was used.

## Retained original full-run failure

Root interrupted the first complete-suite attempt after independent review found
a concrete duplicate-grant defect requiring a new source qualification. The
original command also incorrectly placed pytest's temporary directory inside
the checkout. All four real uv/pipx wheel/sdist installation cases correctly
failed their existing outside-checkout assertion. The backend runtime validator
also correctly rejected a source inventory that omitted nine untracked feature
modules: the heartbeat included them, while the Git-backed receipt did not.
There were no content mismatches or weakened assertions.

The interrupted run retained 5 failures and 130 passes in 587.57 seconds.
Its controller exited 2, all measured source inputs stayed unchanged, the worker
was reaped and its process group was absent. Original logs, the explicit
controller-only SIGINT request, process receipt and copied canonical runtime
evidence are preserved in `artifacts/issue71/full/`. This is not a complete
passing suite. The corrected run will use a physically external private
temporary directory and enroll all completed feature files in Git's index
before the source freeze. Existing workload/source, installation, coverage
and cleanup checks remain unchanged.

## Equivalent-subject grant correction

A read-only integration review found that a legal binding can declare the same
ServiceAccount both as `ServiceAccount` and as its canonical `User` name. Subject
analysis normalized both to one selected identity but emitted duplicate grants
and native row keys. Six regressions failed against the original source,
including actual row projection with six grant rows but only three unique keys.

Matching now retains each semantic `(selected subject, via group)` pair once
per binding before consuming result slots. Every declared comparison remains
charged. Direct grants, distinct reviewed groups, declared who-can User versus
ServiceAccount identities, binding scope and rule provenance remain distinct.
The corrected focused run passed 249 cases in 10.04 seconds with all 228 captured
inputs unchanged: RBAC 256/256 lines and 130/130 branches, authorization
321/321 lines and 90/90 branches, and rows 133/133 lines and 64/64 branches.
Scoped Ruff, formatting and strict types passed. Red/green evidence and exact
hashes are in `artifacts/issue71/review/duplicate-subject-fix/`. This source
change requires a fresh real-cluster trial and full qualification; earlier
measurements remain scoped to their original bytes.

## Corrected-source integration preflight

The fresh corrected-source owned-kind trial again passed all seven scenarios
and 167 observed API calls: 38.290 seconds including the wrapper, 37.467 seconds
inside the verifier. All 226 captured runtime/configuration/verifier inputs
stayed unchanged. Owned cluster/private-directory deletion, environment and
kubeconfig preservation, worker reaping and process-group absence passed.
Evidence is retained separately in `artifacts/issue71/kind-trial-2/`; it does
not overwrite the original-source trial or claim release/provider certification.

Corrected-source startup contracts also passed. Offline/import latency targets
were met; the original 600 ms UI paint target was missed and retained as advisory
for 0.x. Mandatory RSS/import/frame/deadline/cleanup contracts and strict
negative controls remain in `artifacts/issue71/startup-corrected-1/`.

A focused existing documentation-history test exposed one stale live-census
assertion after adding the three authorization records: 351 actual versus 348
expected. The original failure is retained in `artifacts/issue71/docs-census/`.
Only the current census advances to 351; the append-only baseline remains 348,
with its exact records and preserved historical checksums unchanged.

Documentation preflight retained two further stale enrollment counts: 33
current user-source fragments versus 32, and 17 mandatory owned verification
steps versus 16. The 193-case run retained 2 failures and 191 passes; after
correcting the exact counts, all 55 cases from both affected files passed in
14.09 seconds. No source, history, scope or CI condition assertion was removed;
the new authorization evidence-retention path is explicitly required too.
These overlapping selections are not added into a combined test total.

Plan/source/reference checks passed. The fresh development site build/check
verified 49 HTML pages, 1,894 local links/assets and 66 files. Locked browser
tools installed without vulnerabilities; the real browser check passed all
49 pages with zero accessibility violations, preserving keyboard, mobile,
copy, no-JavaScript and external-request restrictions. Evidence is in
`artifacts/issue71/site-development/` and `artifacts/issue71/site-qa/`. These
are local development artifacts, not a public website update.

## Whole-source measurement and remaining local prerequisites

The complete six-worker local run finished with 8,624 passes, five explicit
platform/owned-runner skips and seven development-tool failures in 1,238.10
seconds. All 1,029 measured files stayed unchanged; the worker was reaped and
its process group was absent. Two capture cases require a clean committed
source, while this manual run used a staged tree. Five changed-coverage controls
resolved an unavailable global shim because the direct Python command did not
activate the checkout's tool PATH. Original tests and requirements remain intact.
The original logs, source/process receipts and copied canonical evidence are in
`artifacts/issue71/full-corrected-1/`. These seven cases must pass after the
actual commit/environment corrections; the original full run remains failed.

The same frozen runtime source passed the verified replay-only coverage merge
across all 220 production modules. Independent gates measured 23,655/23,946
lines (98.7848%) and 7,090/7,382 branches (96.0444%). All 93 critical modules
measured 100% lines and applicable branches without exclusions. Changed coverage
against fetched `origin/main` measured 1,805/1,819 executable lines (99.23%
displayed). Coverage does not relabel the seven failures as a passing suite.

The five skips require actual native Homebrew source/bottle workflows, owned
macOS clipboard access or macOS sandbox-exec. They are not local platform
certification. Exact-head hosted checks and protected delivery remain required.
