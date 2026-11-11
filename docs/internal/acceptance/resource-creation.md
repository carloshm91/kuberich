# Resource creation acceptance

Issue: [M10 #234](https://github.com/carloshm91/kuberich/issues/234). Phase:
v0.5.0. Source and published packages remain 0.4.0. This record distinguishes
development checkpoints from complete issue, platform and release qualification.

## Current status

Development source includes the complete creation workflow. Coherent owned-kind,
public source-terminal and fresh installed-wheel checkpoints pass at the distinct
producers below. Later private-editor routing and retained-draft corrections have
focused controls; complete final current-source/platform qualification remains
pending. No tag, package, website, DNS or repository visibility change is
authorized by this work.

The protected base is `7b69e226189758c805d1d67c10b01630c8ccbb2c`, the delivered
#233 squash. Its tree is `ae978481c19859223d47c272b84b7ab65ffcceb8`; see the
[Helm delivery receipt](https://github.com/carloshm91/kuberich/issues/233#issuecomment-6794562958).
That earlier issue's successful CI does not qualify creation behavior.

## Boundaries

- Named creation uses the existing parser, discovery, captured client, strict
  POST dry-run and one-use mutation review. Existing Apply/Delete keep their
  client-side merge and conditional write behavior.
- Creation never updates, adopts, retries, force-replaces or compensates for an
  existing name. It preserves submitted literal nulls and omits last-applied
  annotations. The same frozen canonical bytes reach dry-run and actual POST.
- Server `fieldValidation=Strict` with `dryRun=All` is the schema authority.
  Syntax, discovery and server acceptance are separate evidence. No complete
  offline OpenAPI validator or admission-compliance promise is made.
- Six packaged templates and bounded selected-config user data use typed,
  whole-value RFC 6901 destinations. False, zero and permitted empty values stay
  typed. No expressions, hooks, includes, environment expansion or executable
  template language is supported.
- Any sensitive template parameter makes submitted, returned and edited content
  opaque, including map keys and server/editor copies. Routing identities remain
  visible, so sensitive parameters cannot supply names or namespaces. Trusted
  editor disclosure remains explicit and does not authorize ordinary export.
  Private-template editor results preserve the captured literal GVK/name/namespace
  multiset, allowing reordering and requiring a fresh template capture for routing
  changes; refused edits retain the prior immutable draft without echoing values.
- Source replacement, parameters, namespace and session generations retire old
  validation and confirmation. A clipboard capture is immutable and is never
  reread on Confirm.
- Successful creation requires HTTP 201 and verified GVK/name/namespace plus a
  persistent UID/version receipt. A cancelled receipt decoder can retain known
  created metadata while the overall operation remains uncertain. A lost receipt
  never establishes absence or permits automatic replay.
- Batches validate every item, execute sequentially, retain completed outcomes
  and stop at the first failure or uncertainty. Later items remain unsent.
- Namespace creation and CRD prerequisites require separate reviewed batches.
  Named POST has no namespace-UID precondition; a separate read cannot eliminate
  namespace replacement between requests. Creation remains bound to a name.

## Early actual API checkpoint

Signed producer `59d623395389794327ba7e45f7c099d74361cb6d` passed the narrow
file-source ConfigMap service proof using pinned kind 0.33.0, Kubernetes 1.36.4
and kubectl 1.36.4. Reproduce with explicit owned tool paths:

```sh
uv run python -m scripts.verify_manifests_kind --creation-spine --kind /absolute/path/to/kind --kubectl /absolute/path/to/kubectl --evidence artifacts/issue234/create-spine-02.json
```

The report SHA-256 is
`6affecf061462111b5c021cd0ab4b92cc581b445539e994b581ac5571a3ce115`.
All 342 inputs matched that committed producer. Twelve actual assertions cover
strict dry-run absence, persistent receipt UID/version matching an independent
GET, no last-applied annotation, existing/after-review collisions, invalid
fields/types, read-only refusal, unchanged owned kubeconfig/sentinel, drained
owners/private files and independently verified disposable-cluster deletion.
This is not a template, clipboard, root-UI or final-head qualification.

The actual safe argv and producer/log identities are retained in ignored
`artifacts/issue234/early-producer-receipts.json`, SHA-256
`704fed6a7e05baad670d9c21818a71bd97f48a02a8bf467a1c9b16c9ea825f70`.

The first script-path invocation failed import before cluster creation; its
`create-spine-01.log` remains retained. The corrected module invocation has its
own report and does not relabel the original failure.

## Early source terminal checkpoint

Signed producer `186668e` passed all eight source editor cases:

```sh
uv run pytest -q tests/terminal/test_resource_creation.py -x -n 0 --basetemp=/tmp/kuberich-234-source-pty-04
```

The run passed in 20.69 seconds: 80×24 import/edit, no-op, failure, invalid output,
Ctrl-C, SIGTERM, repeat/resize and Escape during held private-file cleanup.
Actual foreground retention, private-draft removal, unchanged source/kubeconfig
and terminal restoration were checked. The earlier single successful checkpoint
is `e67f7ca`, one case in 2.69 seconds. Later source needs its own verification.

Original focus-traversal and final-root-sentinel failures remain retained.
Four failed focus cases completed cleanup; the interrupted fifth failed its
acknowledgement and required SIGKILL, with group absence/descriptors observed.
That interrupted cleanup remains a failure. The production task-name collision
and missing root Escape delegation were corrected before these passing producers.

## Private editor ownership correction

An independently owned-filesystem counterexample showed the previous
`ManifestFile.close()` removing a replacement root and leaving the retired
original behind. Explicit lifetime, captured root/parent identity and no-follow,
descriptor-relative operations now refuse replacement reads/cleanup. There is
no automatic finalizer that can delete the replacement later. Root, parent,
garbage-collection and cancelled-discard controls pass; the independent original
counterexample and green repeat retain separate receipts. Cleanup refusal stays
visible and retains the owner for retry; it is not reported as complete cleanup.

## Coherent creation and regression checkpoints

Signed producer `b94d2772f7d88e429fd1f05e2de36efe1cbfbeff` passed 110 owned-kind
check occurrences (88 unique names), including all six built-ins and a
selected-config user template, actual
201 receipts matched to independent GETs, zero replicas, changed-template refusal,
served-version CRD schemas/defaults/nullable values/CEL/preserved unknown regions,
ResourceQuota, Pod Security and validating admission. Partial and committed-write
cancellation cases retain known outcomes or uncertainty, keep later items unsent
and do not replay. Existing Apply/Delete, Kustomize, scope, race, RBAC, immutable
field and actual public Pilot review regressions pass in the same run.

Reproduce with explicit owned tool paths:

```sh
uv run python -m scripts.verify_manifests_kind --kind /absolute/path/to/kind --kubectl /absolute/path/to/kubectl --evidence artifacts/issue234/full-kind-03.json
```

The report SHA-256 is
`0fb4fc0e5c066c2bb497ad98424e98a19a731926a0ec3b891fdb1e8794dbe70f`.
All 342 measured inputs stayed unchanged; every owned service/worker/private
connection drained, kubeconfig/sentinel bytes stayed unchanged, and independent
inspection confirmed disposable-cluster deletion. This is Linux amd64 kind
1.36.4 evidence, not provider or complete platform certification.
The actual owned-tool argv and coherent report/log identities are retained in
ignored `artifacts/issue234/coherent-producer-receipts.json`, SHA-256
`6d7edf981ee7527903ff33824b555ead917f8be0e966900d918b018f1d1676ec`.

Original `full-kind-01` failed because the new verifier expected Forbidden for
an admission policy whose default reason returns HTTP 422 Invalid. The application
correctly refused it; the verifier now expects Rejected. `full-kind-02` passed all
new creation cases, then failed when the new quota fixture reused the existing
Apply quota namespace. Only the new fixture namespace changed. Both original
reports/logs remain retained with unchanged-source and complete cleanup results.

Signed producer `3976e3c` passed three actual public CLI PTYs in 13.53 seconds:
known 201 UID/version and server-default review, committed-write cancellation
with missing receipt/unsent later item/no replay, and initially offline capture
followed by explicit Connect & Review of the same draft. Eleven source editor
PTYs passed in 28.92 seconds, including eight Python-editor cases and three
`/bin/sh` cases at 80×24. Full terminal/log private-sentinel absence, public
foreground feedback, handler drain and restored terminal modes were checked.

The exact tested commands were:

```sh
uv run pytest -q tests/terminal/test_resource_creation_cli.py -x -n 0 --basetemp=/tmp/kuberich-234-public-cli-03
uv run pytest -q tests/terminal/test_resource_creation.py -x -n 0 --basetemp=/tmp/kuberich-234-source-pty-05
uv run pytest -q tests/packaging/test_resource_creation_cli.py tests/packaging/test_distribution.py::test_installed_creation_draft_import_editor_and_terminal_restoration -x -n 0 --basetemp=/tmp/kuberich-234-wheel-01
```

The last command passed four fresh installed-wheel cases in 21.49 seconds at
`b94d277`: both console/module entrypoints exercised initially offline public
connection/review/creation and the private shell editor outside the checkout.
The wheel SHA-256 is
`f02dfaf3527b74026230d3bab2f0cf1f9a86268c900a3e2eb1762f5c839c3152`;
all 337 packaged Python modules match the committed producer's bytes.
Earlier CLI namespace-event and rendered-footer harness failures retain their
original identities and logs; successful runs do not relabel them.

These checkpoints precede the final private-template editor identity guard and
Stop disclosure restoration. Their original input/producer identities remain
historical; focused current-source controls and the ordinary exact-head hosted
matrix qualify later changes.

## Final focused source checks

Signed producer `f28c95449073262815a7b11368375e66aeb200cb` passed 1,866 targeted
unit/contract cases with two platform skips in 131.89 seconds. Every changed
critical module has 100% line and branch coverage, with no exclusions:

| Module | Executable lines | Branches |
| --- | ---: | ---: |
| `domain/clipboard.py` | 69/69 | 32/32 |
| `domain/commands.py` | 71/71 | 0/0 |
| `domain/manifests.py` | 332/332 | 96/96 |
| `domain/resource_templates.py` | 264/264 | 136/136 |
| `services/command_catalog.py` | 64/64 | 8/8 |
| `services/commands.py` | 189/189 | 98/98 |

Whole-tree Ruff/formatting, the exact workflow strict-type union (402 sources)
and the complete private-access audit pass at the same producer. All 337
production module bytes match committed blobs. The ignored
`artifacts/issue234/final-focused-receipt.json` SHA-256 is
`d35444e568f261955b34b6ad6ec353612b89aac9dd507f496700b5dd646b513b`;
it binds the module inventory, coverage/log hashes and original docs failure.
This focused coverage does not establish whole-production or changed-line floors.

The five creation UI files and complete lazy-SDK family passed within a combined
266-passing-case feature/docs run. Its two failures were existing public-document
tracking guards treating the product term X11 as an issue-code token. The guide
uses the standard X Window System name; neither guard is weakened. The original
`final-feature-docs-01.log` remains retained. Earlier critical coverage aborted
two completion tests at stale expected candidate lists; corrected lists include
create within the existing eight-result bound and preserve the old aliases.

Private-template editor controls reject name/namespace/GVK changes, additions,
removals and duplicate identities, preserve the prior draft and remove the
private file. Same-identity content moves and document reorder remain opaque.
Public UI controls await the actual refusal/update text and demonstrate fresh
disclosure on the same retained draft. Stop controls preserve in-memory edits,
join held disclosure preparation on Back, reject stale source/policy results and
restore fresh consent without recapture. Original failures retain their own logs.

The corrected complete internal-documentation, style, link and site test family
passed all 219 cases in 93.13 seconds at docs-only producer `87b1205`. The actual
external-source checker and both static-site build/check surfaces pass: 53 pages,
2,230 local links/assets and 70 files. Plan validation reports 1,176 local Markdown
links. Production bytes remain identical to the audited `f28c954` source.

The first genuine PR run `43030692308` failed Fast on an existing UI completion
fixture that still expected context aliases before the new create candidate.
The fixture now includes create explicitly and uses four Down events to select
the unchanged ctx alias. Product source, ordering, result bound and CI gates stay
unchanged. Original hosted Fast artifacts/logs retain the `5e3c2cf` producer;
downstream matrix jobs correctly remained skipped and the quality gate failed.

The corrected run `43031735840` passed Fast: 12,613 cases and two platform skips
in 448.13 seconds. Its actual checkout was PR merge
`5741190d0105ac32ce3ab304d068b3e93690a3d7`, with ordered parents `7b69e226` and
`d50faf5`, and tree `5058eb5` equal to the branch head. All twelve Ubuntu source
parts and both Linux native jobs then failed before behavior: official Ubuntu
archive/ports DNS resolution failed during signed APT index setup, reaching the
unchanged 120-second deadline. Microsoft indexes succeeded. The original logs
retain the infrastructure failure; no Ubuntu application/native qualification
is inferred. Agent-host DNS/TLS reachability later recovered, which does not
establish hosted-runner recovery or waive the next complete matrix.

Review of the two Fast platform skips also found that the existing explicitly
owned macOS clipboard step selected only the write-roundtrip node. That same
guarded command now selects the dedicated native-read roundtrip as well; the
hosted-runner, platform and explicit opt-in guard remain unchanged. A policy
control binds both selected nodes. The focused CI/APT/clipboard family passes
117 cases with two intentional Linux platform skips. No application, APT mirror,
signature/TLS check, retry count or deadline changes accompany this correction.

Run `43034296431` then failed in Fast before behavioral tests: the same Canonical
archive DNS failure again reached the unchanged 120-second signed-index deadline.
Agent reachability therefore did not establish hosted recovery. Original
`hosted-03-fast-failure.log` remains retained, SHA-256
`ca79c86d2ff50dec52a2f160926d5b493f3c79029fe6387caacf62101711acf2`.

The CI-only correction selects the fixed, operator-documented
[MIT SIPB HTTPS mirrors](https://mirrors.mit.edu/) for Ubuntu and Ubuntu Ports.
Independent agent checks authenticated all four jammy/noble security combinations
using the existing Ubuntu archive keyring and matched the contemporaneous
Canonical bytes exactly. This establishes the candidate's metadata authenticity
and observed currency, not mirror registration or hosted recovery. An earlier
OCF candidate had valid signatures but lagged security metadata and was rejected.

The bounded source-format helper rewrites recognized Ubuntu one-line, deb822 and
mirror-list layouts, including actual ARM sources that previously ignored the
mirror-file-only change. Suites, components, architecture and Signed-By remain
captured; unrelated sources remain unchanged. Unknown formats, trust overrides,
unsafe files, oversized inventories and changed preimages refuse before writes.
Actual `apt-get update --error-on=any` must authenticate the selected pockets with
the existing keys. No key, TLS/signature option, package closure, retry count,
120/180-second command deadline or outer six-minute bound changes. Focused source,
bootstrap, workflow and qualifier controls pass 199 cases; genuine next-hosted
signed setup plus the complete current matrix remain mandatory.

Run `43039790495` refused source preparation before network access. The pinned
Ubuntu image's mirror list includes TAB-separated `priority:1` through
`priority:3`; the first finite parser rejected those rows as unknown URIs.
The exact [image provisioning source](https://github.com/actions/runner-images/blob/ubuntu24/20261101.360/images/ubuntu/scripts/build/configure-apt-sources.sh)
is retained in ignored `pinned-configure-apt-sources.sh`, SHA-256
`90b1cde55a1daacb8b65efd19faa3a1fe61c24353c3fef829da2104ff6be5f16`.
The parser now accepts only that observed optional priority field and preserves
refusal for other metadata. The exact pinned fixture and negative controls pass
within a 205-case focused cohort. Fixed source-validation reasons are visible
through SourceFormatError; raw source values/credentials and generic OS details
remain withheld. Original `hosted-04-fast-failure.log` is retained separately;
this refused setup establishes no mirror-recovery or application result.

Run `43041184702` passes current Fast (12,613 cases, two platform skips, 482.84
seconds). Actual checkout is `761abebad9545b7cf2d54da88e8b6c0cda0bb84e`.
All twelve Ubuntu source-part dependency setups and both Linux native compiler
setups succeed with the reviewed mirror and original authentication/bounds.
The completed Fast log retains actual MIT base/updates/backports/security index
refresh and package installation. This demonstrates hosted setup recovery.

Both Linux native outside-checkout workflows then refuse the relative creation
file: the Docker wrapper preserved UID/GID but omitted the container working
directory, so the app correctly looked under `/` and found no source. macOS
sandbox execution inherited the owned fixture cwd. The verifier-only correction
passes that exact cwd through both creation-driver wrap ports and sets Docker
`--workdir` only for this cohort. Global Host/root negative controls, private-file
ownership, application guards and deadlines remain unchanged. Focused verifier/
fixture controls pass 37 cases with one macOS platform skip. The original Linux
logs and provider ZIP remain retained; those native failures are unqualified and
the next genuine complete current-source/native matrix is still required.

## Remaining qualification

Whole production/branch/changed-line gates, native workflows and the
ordinary exact-head hosted matrix remain separate requirements. Provider
certification remains Q05
#87. D09 #82 owns cumulative v0.5 qualification and any source version change;
publication requires separate approval.
