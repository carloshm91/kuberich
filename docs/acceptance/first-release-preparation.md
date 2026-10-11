# First 0.1.0 preparation: #150

The source/lock version is `0.1.0`; authored notes cover features, fixes,
compatibility/migrations, installation, upgrades/uninstall and known limits.
This prepares a candidate, without a tag, package upload, public tap, final-site
deployment or DNS change. The completed development qualifier is
[D06 #51](workload-checkpoint.md); exact candidate qualification remains separate.

## Measured local preparation

The new installation guide distinguishes a trusted local wheel, conditional
public Python/Homebrew channels and four standalone archives. Source scope is
Ubuntu 24.04 x86_64/macOS 26 ARM on Python 3.12–3.14; native archives and Homebrew
have their separate measured hosts/floors. Provider/physical-terminal and macOS
14 Intel limits remain explicit. Both websites reuse the maintained guides.

The actual application generated new workspace and owned-kind CoreDNS SVGs
with installed metadata `0.1.0`. The producer used synthetic loopback resources
and an explicitly owned disposable cluster; cluster deletion and caller isolation
passed. Original commands/logs and media remain under `artifacts/launch150`.
The tracked media inventory retains application tree/version and image digests.
No screenshot text/version was hand-edited.

Local checks passed:

- 126 initial site/native-parser/UI cases in 134.17 seconds.
- 307 release-notes, phase-policy and Homebrew checks in 14.41 seconds.
- Two real uv/pipx upgrade trials in 58.32 seconds, from immutable owned
  `0.1.0rc1` into the real `0.1.0` wheel. Normal upgrade, actual upgraded
  navigation/shell, preference/caller preservation and uninstall passed. This is
  an unpublished source baseline, not a fabricated earlier public release.
- Seventeen site behavior/negative-control cases with the final captured media
  in 28.19 seconds. Changing a source version does not imply package availability.
- Ruff/format over 532 files, strict types over 146 application/gate/site files,
  whitespace and plan validation; locked Node QA audit reported zero vulnerabilities.

The two-surface static build passed **53 pages, 1,988 local links/assets and
68 files**. Real Chrome 143.0.7499.169 with locked Playwright 1.64.0/axe 4.14.0
checked every page at desktop/mobile widths, 320px overflow, keyboard skip/menu,
clipboard success/denial and navigation with JavaScript disabled. There were
zero automated A/AA violations, browser failures or external runtime requests.
The retained desktop/mobile images were visually reviewed. Automated checks do
not establish physical screen-reader/terminal/font/clipboard certification.

Site manifest SHA-256: `5ff40620cd06e8dfef7651d9aa27973bf11d712e58e02197f3b38ed62bdf44b8`.
Browser report SHA-256: `27c4542e55245536d17ac5c2281b672e86e0720cb11c4146798e4d1bd949ea2e`.
These are local preparation bytes. The protected candidate/main run and original
audited distribution/native/installation artifacts need their own retained IDs
and independent reading before this issue closes. Local checks do not substitute
for the six-source/four-native release matrix or three consecutive owned rounds.

## Publication handoff

The existing [hosting procedure](../website.md#final-product-hosting-cloudflare-pages)
proposes the two Direct Upload projects, `kuberich.com`, `docs.kuberich.com` and
an explicit `www` redirect, with HTTPS, immutable manifest/deployment association
and rollback. The approved development provider hosts retain their earlier
published bytes; source preparation does not redeploy them.

#89 still owns concrete publication approval, actual PyPI/TestPyPI publisher
ownership, the public `kuberich/homebrew-tap` and limited update credential,
public installed-channel verification, final website/custom-domain activation
and verified redirects. The GitHub organization already exists, while a namespace
lookup alone does not prove package ownership or activate a channel. Publication
and owner environment review remain required after the concrete candidate is ready.


## Reader-facing review and Mac credential cleanup correction

The maintainer requested detailed product guides, fictional examples and public
text without internal task references. The initial editorial build has 23
maintained user guides plus three generated references on both surfaces: 57 pages,
2,330 local links/assets and 72 files. README now leads with available behavior,
installation, essential keys, documentation and contribution/license guidance.
An everyday walkthrough and troubleshooting connect the views into usable flows.
Public summaries/statuses distinguish available, partial, planned and unverified
capabilities while retaining internal source traceability outside rendered guides.

Guide review corrected stale EndpointSlice, attach/transfer and shell-history
statements, and separated log reception from following. Generated CLI help also
omits internal task codes. Tests inspect visible HTML and authored public guide
content, and verify that changing a public capability summary regenerates both
surfaces without exposing internal tracking fields. A private 62-file content
scan found no known customer names; no user Kubernetes configuration was read or
contacted. Workspace capture now declares fictional demo-lab/demo-apps aliases.

The initial frozen `be9c215346edd0446a57378efcd5eb0769e8e444` completed three
owned rounds (44 commands, 992 contracts and thirteen scenarios per round), with
cleanup/caller preservation independently checked in 50.447 minutes. Its original
results digest is `dc201cba5647c80f7bd85194ebb797657cae632a51cd8254588e95760fcf35c5`.
That does **not** override its failed Mac source job in
[run 38142026668](https://github.com/carloshm91/kuberich/actions/runs/38142026668).
The original source/native/installation ZIPs, API results and failed Mac log were
retained. The native installation run passed, but its earlier source does not
qualify the correction below. No unchanged retry is counted as a fix.

The Mac failure masked the credential helper's expected output-size error with
EPERM during process-group teardown. Apple XNU can report this while group members
exit, but the original job did not capture process state and does not establish
that diagnosis conclusively. The existing process-session signal guard is moved
to the low-level runtime and shared by credential helpers. Darwin's transient
denial is accepted only after bounded signal-zero probes establish ESRCH; live
or persistent denial still propagates. This avoids a services-to-adapters import
and preserves descendant-group cleanup after the leader exits.

Four real-child regression cases cover valid output, stdout/stderr overflow and
cancellation while spawn completes. All four fail behaviorally on the retained
original source (35 unrelated cases deselected), and all pass with the correction.
The initial negative-control import/setup error remains separately retained and
is not counted as a failing behavior witness. Existing live/persistent/non-Darwin
permission-failure controls also pass. The focused runtime guard measured 100%
line/branch coverage; broader focused slices do not substitute for the complete
production/critical-module gate.

Local checks passed: 274 process/credential/runtime cases; 334 additional
credential, real-terminal handoff and release-contract cases; 175 site/launch
cases; Ruff/format over 535 files; strict checking over 145 application/gate/site
files; and plan validation. An exploratory strict check including the preexisting
untyped capture-test helpers failed; it is not reported as a passing required
strict target. The initial editorial Chrome run checked all 57 pages at desktop
and mobile widths, keyboard, no-JavaScript navigation and clipboard success/denial
with zero accessibility violations, external requests or browser errors.
Its report digest is `22f2e184ce1f2b1ece6d1a239072ac31fbff3cda8f81f45dd5e608242c00dda1`.
These editorial bytes precede the final summaries/capture; the final frozen build
and fresh source/native/owned qualification remain required before handoff.


## Final local editorial/capture result

The final build has 57 pages, 2,336 local links/assets and 72 files. Actual new
workspace output uses demo-lab/demo-apps/demo-cluster/demo-reader, with no ambient
kubeconfig. Original owned-kind CoreDNS output retains its original digest and
provenance; no screenshot text is hand-edited. Full-size image links improve
mobile inspection. The maintained user guides contain no task codes or issue/PR
links; version notes retain authored change references and contributor attribution.

The final Chrome run covers all 57 desktop and 57 mobile pages, 320-pixel overflow,
A/AA accessibility, keyboard, clipboard success/denial and no-JavaScript navigation,
with zero external requests or browser failures. Source and output hashes are
receipted. Site SHA-256: `40132b9053862992bc904d0adb7d1f652cd7c209fee97b45e9e6f5eea169cda1`.
Browser SHA-256: `26278f3ebba184ff8889cccee2b06b069fe11cfda97699bccf0995ee731ed216`.
The final site/owned-kind/contract slice passed 1,015 tests in 182.26 seconds
(19 website tests plus 996 contracts/owned-boundary tests). Source/native/exact-main
and three fresh corrected rounds still need their own immutable receipts. No
public channel, final-site or custom-domain activation occurred.

## Installed help and component-style allocation review

The subsequent frozen `f45159323ca4f7b2a1a1e21fa6c70c43f3edc9ab` failed
[source run 38147690087](https://github.com/carloshm91/kuberich/actions/runs/38147690087).
Every source job found an installed-help test still requiring the removed
`U01 #56` reference. Ubuntu/Python 3.13 additionally failed the normal-runtime
aggregate UI heartbeat at 183.688 ms during a source-picker transition. A
174.698-ms generation-two collection reclaimed 46,159 objects; its allocation
stack includes Textual Strip/compositor rendering. That overlap accounts for
most of the observed gap, but does not identify every collected object.
Original job logs, artifact ZIPs and GitHub digest comparisons remain retained.
All four native archives and all three native source-install/upgrade trials
passed for that earlier source; they do not qualify the next repair.

The installed contract now checks the user-facing missing-feature description
and exit status. All eight installed launch cases pass. Diagnostic-only SAVEALL
attribution found repeated virtual component DOM graphs among collected objects;
its changed retention policy disqualifies it as latency evidence. The scoped
stylesheet instead reuses each widget's component nodes, with native selector
evaluation, reset rules, change detection and reload-copy behavior. Native
comparisons cover focus, theme/geometry changes, inline edits and removed CSS.
The five focused component/color-ownership cases pass. Textual is pinned to the
qualified 8.2.8 version for these private rendering boundaries.

The retained local Python 3.13 normal-runtime replay completes both full-history
rounds at 90.292 ms maximum; its deliberate callback control fails at 202.268 ms.
GC stays enabled at default thresholds, source hashes remain unchanged within
each child, and final app/log/watch/registry owners drain. The parent-coverage
replay also completes both rounds; its 178.215-ms maximum is diagnostic, not
ordinary-runtime qualification. Original child artifacts are retained under
`artifacts/launch150/affected-runtime313-original`; the positive heartbeat digest
is `b427f90762546d07f458df65dcf7062d55009a9154c4affa35b1eb2347cbc5e3`.
These are local repair checks, not final frozen platform qualification. Required
source/native/installation and owned-round evidence must be regenerated for
the completed repair before this issue closes.
