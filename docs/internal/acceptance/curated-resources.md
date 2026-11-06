# Curated resource and Events acceptance

This record documents the implementation and scoped verification checkpoints for
[issue #232](https://github.com/carloshm91/kuberich/issues/232). Focused cohorts do
not establish complete acceptance or release qualification. The reviewed base is
protected main `5060b4dcd35968e3b990bd833eba731539938cff` after PR #319.

## Protected delivery

PR [#320](https://github.com/carloshm91/kuberich/pull/320) delivered this behavior
at protected main `389babca15ab15e0ef8317a815afbeda1e8e9f73`. Its final head
`fa20bc6424e62f93f65e0d98bb851481fca9fda7` passed all 27 expected Application
job keys in [run 42274318207](https://github.com/carloshm91/kuberich/actions/runs/42274318207),
plus Repository checks and DCO. Three unacquired macOS jobs in attempt one were
rerun at the same source; completed same-head outputs were reused. Original
runner-capacity cancellations and earlier helper-oracle failures remain retained.
The protected squash tree matches the tested merge tree, with maintainer email
and sign-off verified.

The clean complete local cohort passed 11,664 tests with five explicit skips.
Verified runtime replay and independent gates measured 98.6012% lines,
95.5241% branches, 98.62% changed lines and all 113 designated critical modules
at 100% lines/branches across 264 production modules. Final source and installed
terminal replays passed four cases each in 30.19 and 37.72 seconds; all 266 wheel
payload files matched source. The wheel SHA-256 is
`cebcae508dc6509dd79eef3fd620bbc7ff4723e133bbbce58407abc10b96bfac`.
These results deliver the scoped issue; cumulative 0.4.0 qualification remains
separate in #75. Statements below about pending #232 delivery are historical.

## Scope

Eighteen ordinary resource families use the standard table, with a separate
Events workspace. Full descriptor matching, typed values, meaningful details,
guarded links, read-only effect boundaries, history/viewport, cancellation and
privacy are required. The
[public-source comparison](../curated-resource-inventory.json) retains all 19
named families and additional menu gaps without inferring complete product parity.

## Measured focused evidence

All reports below use owned synthetic inputs and isolated artifact directories.
They do not use the maintainer's active Kubernetes context.

| Cohort | Result | Scope and limit |
| --- | --- | --- |
| Scaling extractors | 136 passed; 100% lines/branches | Six families; serialized budget, credential-shaped Lease text and truncated HPA metric pairing controls |
| Policy extractors | 147 passed; 100% lines/branches | Seven families; escaped JSON/action payload accounting and concealed webhook trust/URL values |
| Policy API-default controls | 167 passed in 2.90s; 100% of 375 lines/118 branches | Optional EndpointSlice collections omitted or serialized as null retain API-defined empty semantics; malformed values remain unknown |
| Access extractors | 50 passed; 100% lines/branches | Five families; existing RBAC parser reuse, omitted/default fields and complete serialization accounting |
| Navigation service | 80 passed; 100% lines/branches on its initial source | Owned HTTP, exact API/UID/scope, finite reads, cancellation and caller/client ownership; the later version-anchor delta passes the final Inspector/navigation cohort below |
| Ordinary whole-App views | 35 passed in 45.27s | All 18 families, typed pairs, sorting/filtering, watch updates, API availability, exact HPA versions, compact metadata, held reads and stable UID/viewport |
| Events model/projection/table/controller | 124 passed in 10.68s | Model/table/controller 100% lines/branches; projection 99.29% lines/92.50% branches; same-worker bookmarks, full scope/query guards, held/latest/cancel/cache controls included |
| New critical-module cohort | 1,694 passed in 87.34s | All nine newly enrolled modules at 100% lines/applicable branches; this scoped report does not satisfy complete-production floors |
| Snapshot source clock | 7 passed in 0.59s; 100% of 27 lines/4 branches | Quiet/repaint timestamp stability, source mismatch and payload weak-reference collection |
| Inspector compatibility | 89 passed in 74.93s | Exact unchanged 264-production-module input pin; source hash manifest `source-pin-full-03.json`; later corrections are scoped separately below |
| Final Inspector/navigation controls | 157 passed in 44.20s | Exact unchanged 264-module input pin; critical inspection 83 lines/32 branches and navigation 231 lines/102 branches at 100%; oversized Event reporters, overlay completion and actual watch changes around held/queued target navigation |
| Integrated App | 63 passed, one fixture failure in 64.41s; corrected Events cohort 10 passed in 8.42s | All ordinary families, native history, Event source/metadata/exports and inspectors; the compact fixture initially did not enable metadata responses and the original failed run remains unqualified |
| Relationship API-default controls | 97 passed in 1.82s; 100% of 358 lines/118 branches | Faithful native EndpointSlice omission/null shapes, target UID and unknown readiness; unrelated Core Endpoints and generic parsing remain strict |
| Events viewport and activation | 21 passed in 15.75s; table 100% lines/branches | Actual App Back restores horizontal position; genuine wheel/cursor/new intent controls and stale warning-option activation are included |
| Native source terminals | 4 passed in 28.53s | Ordinary families and Events at 100×30 and 40×12; source-06 predates the later EndpointSlice correction and is not relabeled as its final source pin |
| Installed terminals | 4 passed in 36.86s | Console/module entry points outside the checkout, all families and Events; wheel SHA-256 `6ecab8f25cb06b85b5cf8bd263e0869966dc6cab07a60ab0722f1361c67223c6`; 266 installed payload files match the corrected source |
| Disposable kind API/App rehearsal | Passed in 51.43s | `kind-008`: all 18 ordinary families plus Events, native Table/full-object observations, typed sorting, watch/details/read-only App behavior and representative links; 270 input hashes unchanged and owned session/App/cluster/private directory closed |
| Verifier receipt controls | 101 passed in 4.72s | Nested actual-family result serialization, strict declared DTO conversions and rejection of unsupported/nonfinite values; preparation-only evidence is not API execution |
| Final shared navigation/export/lifecycle controls | 38 passed in 25.39s | Actual App/owned HTTP server selectors, collection membership, Event warnings/groups/members, Back/Forward, saved/reopened report metadata and queued sort messages after frame removal |
| Horizontal intent controls | 30 passed in 18.88s; Events table 204 lines/34 branches at 100% | Home/End after pending animation, no-movement intent, next-arrow targets and earlier viewport-restoration controls; correction is Events-only |
| Corrected native source replay | 4 passed in 30.88s | `source-08` retains the original strict left-edge, group-member, Back/viewport, resize and terminal cleanup assertions on unchanged final inputs |
| Final disposable kind replay | Passed in 53.36s | `kind-010`: all 19 families on the Home/End-corrected product, 270 unchanged measured inputs and verified owned lifecycle cleanup; earlier passing sources are retained separately |
| Final installed terminal replay | 4 passed in 37.26s | `installed-03`: outside-checkout console/module flows, 373 unchanged outer inputs, strict child-origin/negative controls and cleanup; wheel SHA-256 `cebcae508dc6509dd79eef3fd620bbc7ff4723e133bbbce58407abc10b96bfac`, all 266 installed payload files match final source |
| Completion compatibility | 12 passed in 21.25s | Eight finite provider candidates retain actual narrow App/Pilot cycling, wrap, focus, placeholder, cursor and Tab behavior without coupling geometry to the growing catalog |
| Standard-view privacy compatibility | 38 passed in 55.47s | All 33 families retain actual LIST/WATCH/GET and annotation privacy; webhook Details conceal complete URLs, while deliberate redacted YAML preserves ordinary paths and conceals credentials, trust material and sensitive payloads |
| Shared export and artifact fixture contracts | 64 passed in 3.47s | Existing export fake supplies the required curated/EventOptions defaults; the raced directory fixture explicitly establishes its own mode and retains the strict no-chmod assertion under restrictive umasks |
| Authorization, relationships and documentation compatibility | 54 passed in 52.45s | New Standard routes retain exact GVR, namespace, observed UID, read-only, Back and viewport checks; all 105 historical documentation pins and the protected 361-entry prefix remain intact with three explicit O09 additions |
| CLI launch compatibility | 189 passed in 2.04s | NetworkPolicy is now a supported read-only startup view, including an explicit namespace; genuinely unavailable or unscoped actions retain their rejection controls |

Private local reports live under `artifacts/issue232/`. These are scoped receipts.
Final acceptance requires complete production/changed-line coverage, all required
exact-head platform jobs and protected PR delivery. Consult the live issue and its
linked pull request for the exact global results and protected-delivery state.

## Original failures and corrections

Original reports are retained rather than relabeled as successful retries.

- Initial root contract fixtures omitted watch resource versions; corrected
  fixtures preserved the actual resource identity requirement.
- Registry expansion invalidated old 15-only test fixtures and literal command
  completion expectations. Updated fixtures retain the original families and
  independently test the new served schemas.
- Four actual HPA App cases showed generic current-usage enrichment replacing
  the family's own metrics column. Enrichment now respects curated ownership;
  actual corrected HPA version cases pass.
- Compact mode initially rejected a curated selection before any request.
  A named read-only scope may now negotiate metadata without becoming a printer
  view; the corrected App cohort verifies genuine PartialObjectMetadata.
- One Inspector replay overlapped incomplete root Events constructor wiring:
  66 passed and 20 failed. That run remains failed. After composition was complete,
  the unchanged-input 89-case compatibility cohort passed.
- Independent App controls reproduced the wrong default Event API and Escape
  failing to return from group members. Corrections preserve explicit APIs and
  native history; the integrated replay is recorded separately above.
- Independent owned-HTTP review reproduced an excessive Event reporter detail
  cell/serialized payload. Presentation clipping and complete payload accounting
  preserve the original reporter identity and lookup UID.
- An overlay completion could dismiss a newer modal; a top-screen guard has a
  controlled red/green regression. Same-UID source version changes during a
  held target reads are rejected by the verified fresh/observed version-anchor correction.
- A valid Event collection bookmark could expand to the full Event collection.
  Same-worker predicate enforcement has a controlled two-case red; corrected
  124-case contract/UI and 10-case integrated Event cohorts now pass.

- Native source trials preserved two helper-readiness failures and then reproduced
  a real horizontal viewport regression: the grouped parent saved x=60 but
  returned at x=0. A framework-generated vertical scroll was incorrectly counted
  as new user intent. Events now tracks actual wheel input separately; the
  21-case App/table control cohort and native source replay verify restoration
  without scrolling again after Back.

- Actual kind attempts `kind-001` and `kind-002` failed during VPA fixture setup,
  before any family was qualified. The first received API 422 because a protected
  API group requires an approval-state annotation; the fixture now truthfully says
  `unapproved, experimental-only`. The second encountered initially null CRD
  conditions while waiting for establishment. Both original failures retain
  unchanged-input evidence and verified cluster/private-directory cleanup; neither
  is counted as actual API acceptance.

- `kind-003` rejected a fixture label containing a slash; the fixture now uses a
  valid label value. `kind-004` failed an EndpointSlice count assertion without
  sufficient raw diagnostics to establish its exact cause. Preserved `kind-005`
  API and Table observations then proved that an empty collection can be emitted
  as null. The narrow policy/relationship correction retains malformed-value
  rejection and explicit unknown readiness; controlled original failures remain.
- `kind-006` completed all 18 native pairs but used Textual's mounted latch as a
  close predicate. Public lifecycle evidence proved the screen detached and all
  operations drained; the verifier now checks actual stack attachment and owned
  operation counts. `kind-007` completed functional stages but failed final JSON
  serialization of a nested frozenset. It remains failed without a fabricated
  final receipt. A strict tested writer and the fresh complete `kind-008` run
  establish the passing outcome.
- The first installed-terminal invocation placed its temporary installation
  inside the checkout and correctly failed all four isolation guards. The fresh
  second run uses an owned outside-checkout directory and passes without
  weakening those guards.

- Final independent review reproduced server-query changes clearing the
  authoritative local membership and Event options: five original red cases
  remain preserved. The narrow fix updates the bookmark's query and restores its
  predicate/options after display setup. The 24-case owner cohort passes; compact
  representations keep their existing rejection or honest unknown behavior.
- Saved/reopened report controls reproduced missing warning/group/member and
  ordinary local-membership provenance. Constant-size option notices and complete
  predicate digests now identify the captured subset without copying raw selector
  or Event text into metadata. Eleven new cases pass, including large identities
  and pending-option lease revocation. A broader initial run retained an actual
  queued-sort teardown failure; it is not labeled as passing.
- A valid lifecycle regression then reproduced a queued sort message querying an
  already removed frame. Presentation ignores only a missing frame and preserves
  normal active-frame updates and other errors. The final 38-case combined cohort
  passes. One earlier lifecycle test used a nonexistent public App attribute; that
  diagnostic is preserved separately from the valid controlled red.
- The first complete-suite attempt was deliberately interrupted before these
  review corrections: exit 2, six cases passed in 137.43 seconds, measured inputs
  unchanged. Its partial coverage and logs are retained and never qualify the
  complete production gates.
- Source terminal attempt `source-07` passed three cases and failed the narrow
  Event flow at its strict left-edge frame assertion. Cleanup completed. A public
  App/Pilot control demonstrated the pinned DataTable behavior: Home set x=0,
  but the previous animation target remained 60 and later moved x back to 60.
  End and no-movement boundary input had matching controlled failures. Two narrow
  Event actions now cancel pending motion and record actual boundary-key intent;
  no vendor or shared FrameTable implementation changed. The 30-case focused
  cohort passes. The native framework characterization does not qualify boundary
  navigation in other workspaces; final source/installed receipts are separate.
- Complete-suite attempt `full-002` retained four failures and 546 passes before
  an intentional stop at 934.74 seconds. All 1,216 selected file hashes stayed
  unchanged. Its backend provenance guard correctly rejected 264 actual modules
  against 252 Git-indexed modules: the 12 new files had not yet been staged. The
  original backend/UI child receipts and partial coverage are archived. The other
  failures exposed a completion test coupled to the previous capped catalog and
  two overly broad explicit-YAML canary assertions; their precise contracts are
  corrected in the separately recorded completion and privacy cohorts above.
  This run does not qualify the complete production gates.

## Final acceptance contract

The completed `full-003` run retained 31 failures, 11,632 passes and five explicit
platform/native-install skips in 1,536.60 seconds. All 1,216 input hashes remained
unchanged. Eighteen failures were an export fake missing newly required ports;
seven were old Custom-table expectations for newly curated Standard resources;
two pinned the previous documentation inventory size; one treated NetworkPolicy
as unavailable; and one raced-directory fixture assumed the caller's umask.
The other two correctly refused image capture from uncommitted source. Original
reports, coverage and runtime receipts remain archived; the passing scoped
corrections above do not relabel that complete run as successful. Complete
qualification starts from a signed-off, clean committed candidate, as described
in the contribution and quality guidance. The native-install/macOS skips require
their owned platform workflows; they do not establish those platforms' results.

The final source must pass the complete local suite and coverage gates,
user/reference documentation and inventory checks, independent coverage merge
and exact-head hosted platform jobs before protected squash delivery. The live
issue and its linked pull request record those final results; the scoped evidence
here does not substitute for them. Publication and the cumulative 0.4.0 qualifier
are separate.
