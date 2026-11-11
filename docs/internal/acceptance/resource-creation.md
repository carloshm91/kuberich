# Resource creation acceptance

Issue: [M10 #234](https://github.com/carloshm91/kuberich/issues/234). Phase:
v0.5.0. Source and published packages remain 0.4.0. This record distinguishes
development checkpoints from complete issue, platform and release qualification.

## Current status

The create-only ConfigMap service and source editor checkpoints pass. Template,
clipboard, batch, schema/admission, installed/native and final hosted verification
are being completed on the issue branch. No tag, package, website, DNS or
repository visibility change is authorized by this work.

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

## Remaining qualification

Complete current-source built-in/user/clipboard/schema/admission/batch trials,
source/installed/native workflows, all changed critical modules at 100%, whole
production/branch/changed-line gates, docs/site checks and the ordinary exact-head
hosted matrix remain separate requirements. Provider certification remains Q05
#87. D09 #82 owns cumulative v0.5 qualification and any source version change;
publication requires separate approval.
