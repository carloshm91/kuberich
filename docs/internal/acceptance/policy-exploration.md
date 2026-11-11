# Policy exploration acceptance

[A05 #80](https://github.com/carloshm91/kuberich/issues/80) extends the protected
#232 resource implementation from main
`871d95890ddc08afa79631a693317e3858a1631e`. This record separates development
proof from final protected checks and release qualification. Source metadata
remains 0.4.0; no artifact or website publication is performed.

## Implemented behavior

The existing Standard table now covers validating/mutating admission policies and
bindings at exact discovered v1/v1beta1 descriptors. Typed counts, declared match
constraints, exclusions, selectors, parameter identities, actions, mutation types
and generation-qualified validating observations stay separate. Mutating resources
receive no fabricated validating-policy status or webhook reinvocation default.

Policy links filter same-version bindings by exact `spec.policyName`; bindings
read the current named policy through discovery. These are current-name relations,
not historical UID continuity. The existing captured client, source UID/opaque
version anchors, two-GET budget, intent guard and normal Back history remain in use.
All four families stay read-only at effect boundaries, including unknown versions.

The single discovery catalogue retains advertised preference through failed
version discovery. An automatic selection cannot interpret denied/incomplete
higher-preference discovery as absence; explicit discovered versions remain
usable. Unknown/alpha schemas retain metadata fallback and no PSP endpoint is
probed. Existing list/watch/pagination/metadata ownership machinery is reused.

Default inspection and artifact recursion share descriptor-aware admission
concealment for CEL, validation/message/patch/audit/warning payloads and webhook
URL/path/CA bytes. Resource/document/support exports and imported artifacts use
that policy. Deliberately reviewed sensitive resource payloads retain their
existing contract while previews stay concealed. Unrelated resource expression,
message and URL fields retain their existing intentional disclosure behavior.

NetworkPolicy peer scope, webhook match-condition/reinvocation declarations, HPA
behavior/generation provenance and bounded Pod/Node scheduling detail fill the
reviewed existing-family gaps. Quota, LimitRange and PDB observations are retained.
There is no parameter-value reader or admission, CEL, webhook, CNI or scheduler
simulator. Optional Workload/PodGroup API semantics and provider/CNI certification
remain unqualified. Immutable primary-source pins are appended to the
[existing inventory](../curated-resource-inventory.json); #232 history is unchanged.

## Required thin-spine proof

The initial validating-v1 implementation passed the complete path before other
families were added: owned HTTP discovery → Standard table → details/Links →
bindings → current policy → Back at 100×30 and 40×12. Its nine UI cases passed in
11.59 seconds with:

```sh
uv run pytest tests/ui/test_admission_exploration.py -q \
  --basetemp /tmp/kuberich-80-http-spine-2
```

Held source UID/RV changes, a third observed source RV during a held target read,
context replacement, actual HTTP 403, absent policy API and missing object all
refused stale navigation or version downgrade. The first draft's viewport-field
test error was corrected to actual public navigation coordinates; its failed log
is retained in `artifacts/issue80/http-spine-1.log`.

An actual owned kind validating-v1 pair passed in 30.969 seconds. Server defaults
Fail/Equivalent, LIST/WATCH/GET, read-only UI with global read-only disabled,
policy/binding/Back/filter/UID restoration, changed source RV, delete/recreate UID
refusal, actual impersonated 403 and PSP absence were observed. The exact command:

```sh
uv run python -c 'import runpy; runpy.run_path("/home/develop/projects/personal/kubetrol/artifacts/issue80/proof-lane/run_spine.py", run_name="__main__")' \
  /home/develop/projects/personal/kubetrol/artifacts/issue80/proof-lane/spine-002
```

Receipt `proof-lane/spine-002/result.json` retains 325 equal before/after input
hashes, real manifests and an SVG. App/admin/restricted sessions closed, generated
kubeconfig stayed unchanged, the cluster was deleted with absence verified and
its private directory was removed. The first run's receipt attempted to serialize
private record bytes; the verifier now captures explicit public fields and keeps
the strict encoder. Its original failure and cleanup outcome remain retained.
This spine qualifies only its measured working bytes, not the final candidate.

## Focused development evidence

The initial independent admission facts reached 100% lines/branches before the
spine. Expanded versioned controls cover all four families, required omissions,
malformed/duplicate identities, absent/null/empty selectors and collections,
unknown enums, output bounds and concealed payloads. Final measured results are
recorded after the input freeze below.

The shared privacy/inspection/export regression cohort passed 211 cases in
14.25 seconds. An independent public-codec probe reproduced 18 export/preview
leaks before the shared policy and zero afterward across six admission kinds and
48 controls. Original RED and corrected GREEN receipts remain under
`artifacts/issue80/root-audit/`; deliberate sensitive payload and unrelated-group
controls passed. Privacy policy coverage is 10/10 lines and 2/2 branches.

## Frozen implementation evidence

The final pure admission cohort passed 200 cases in 17.84 seconds: 246/246
statements and 58/58 branches. Existing policy/scaling and the scheduling helper
passed 374 focused cases in 25.70 seconds, each at 100% lines/branches:
394/126, 383/124 and 184/74 respectively. Separate privacy/navigation controls
also measured 100% of their new deterministic modules. These are scoped reports,
not the complete-production coverage result.

After composition review, a sensitive selector value was found to re-enter Pod
details through the raw scheduling projection. Passing the already-redacted
manifest corrected the issue; independent RED/GREEN receipts and actual App
canaries preserve this failure and correction. Denied-preferred discovery also
exposed an eager unversioned lookup when opening an explicitly selected beta;
the native-route preference check now preserves that explicit descriptor. Both
fixes passed 113 focused boundary cases in 29.74 seconds. The subsequent full
navigation/curated compatibility cohort passed 304 cases in 64.34 seconds.

The amended real kind command passed all 23 families (22 ordinary plus Events)
in 64.5607 seconds:

```sh
uv run python -m scripts.verify_curated_resources_kind \
  --kind /home/develop/projects/personal/kubetrol/artifacts/qualification-tools-linux-amd64-ewfuxtag/kind \
  --docker /usr/bin/docker \
  --evidence /home/develop/projects/personal/kubetrol/artifacts/issue80/proof-lane/full-kind-002/evidence.json
```

Its 326 source inputs stayed unchanged. The receipt SHA-256 is
`94b7a4c583771566d3c44205c2fe88c501243f17b65d33554b555381b26e6b05`.
The pinned 1.36.4 server advertised only stable v1 for all four admission
families; v1beta1 compatibility is versioned HTTP/pure evidence, not a claim
that this kind served it. Optional Workload/PodGroup APIs were absent. Both policy
kinds followed binding links and Back. Actual Pod/Node inspection showed bounded
affinity/toleration/taint declarations, preserved the unscheduled Pod's missing
nodeName, and concealed sensitive selector values and annotations in default,
managed, details and viewer captures. Every App/session, generated kubeconfig,
owned cluster and private-directory cleanup check passed.

The matching source PTY cohort passed four cases in 41.71 seconds: all 22
ordinary routes, both admission link paths, 100×30 and 40×12 geometry, resize,
Ctrl-Q/Ctrl-C, exact imported-module/source binding, GET-only ledger, no egress
or helper execution, concealed payloads/logs and restored terminal attributes.
Receipts are under `proof-lane/source-pty-002-receipts/`; original pre-fix 001
receipts remain historical. The documentation/site cohort passed 190 cases in
98.17 seconds. Ruff, formatting, the strict workflow target union (61 targets,
380 source files at that check) and changed-boundary strict types passed.

## Clean installed candidate

Signed implementation `da5920fc78327c877d9c44735758d10fccebe7b7` passed four
fresh installed-wheel cases in 66.88 seconds (console/module, families/admission):

```sh
uv run pytest tests/packaging/test_curated_terminal.py -q \
  -k 'families or admission' \
  --basetemp /tmp/kuberich-80-curated-installed-pty-01
```

The wheel SHA-256 is
`4b8b71670eb229ddd4deaeafb47aa1a4486d8a44d92902be4a5798c44911229c`.
All 320 Python payload modules matched source byte-for-byte. Actual imported
paths and cwd were outside the checkout. Every family route, both admission
link paths, Back, resize, interruption, concealed API/log payloads, GET-only
ledger, zero helper/egress and terminal/process/API cleanup checks passed.
Original receipts and the wheel are preserved under
`proof-lane/installed-001-receipts/`; there was no installer failure or retry.
This documentation-only evidence update preserves the measured implementation
commit and receipt identities rather than relabeling them as a later source.

## Remaining qualification at this source freeze

The ordinary 27-job PR matrix, complete independent production/changed-line
coverage and protected delivery are tracked live in
[issue #80](https://github.com/carloshm91/kuberich/issues/80).
No focused cohort substitutes for those checks. The six-environment manual matrix and three repeated release
contracts belong to #82; provider certification remains opt-in #87. Startup and
runtime latency are advisory for 0.x with actual misses retained; RSS, import
boundaries, frames, deadlines, cleanup and coverage remain hard requirements.
