# Helm catalog and lifecycle acceptance

Issue: M09 [#233](https://github.com/carloshm91/kuberich/issues/233), v0.5.0.
Status: implemented in development source; final coherent native, installed and
ordinary exact-head CI qualification **pending**. Source version remains 0.4.0;
published 0.4.0 does not include this workflow. This record neither completes
cumulative #82 qualification nor authorizes tags, packages or website publication.

## Behavior and limits

- Public `:helmcharts` opens the application-owned cached catalog. Explicit
  add/update/remove controls manage classic HTTPS indexes or registered OCI chart
  paths, private Basic/token credentials, independent CA trust and separate exact
  token/download origin approvals. Opening, cached search and reload do not probe
  Helm or refresh a remote index. Registry-wide discovery is not assumed; denied
  tag enumeration never becomes authority to invent a version. Explicit digest
  registration is separate. Only fixture setup uploads synthetic registry bytes.
- Chart/version selection freezes exact package, catalog revision/generation and
  package/OCI manifest/layer digests. Private atomic metadata/credentials use
  no-follow physical-file identities; external receipt replacement or stale
  displayed generation fails closed. No ambient Helm/Docker state, provider login,
  credential helper, proxy credentials or Kubernetes credentials enter catalog HTTP.
- V2 application charts and bundled library/application dependencies are supported
  within cumulative 16-MiB compressed/64-MiB expanded, 2,000-file/eight-level limits.
  Index/OCI metadata is limited to 8 MiB, 10,000 entries and 20 pages; values to 1 MiB.
  Missing/unresolved dependencies, legacy requirements files, unsafe archives and
  external file/network/URN schema resolution are refused before native consumption.
  Supported dependency syntax is deliberately narrower than Helm semver: separated
  comparator tokens such as `>= 1.0.0` and repeated names with distinct aliases are
  refused. Offline schemas allow fragment references and recognized draft-07,
  2019-09 and 2020-12 metaschemas; unlisted dialects are refused. OCI provenance
  descriptor integrity does not establish a verified signature or trusted publisher.
- Public install, upgrade and uninstall share the existing Helm service/current
  client. A concrete active namespace UID, complete Secret/ConfigMap storage
  identity, CLI version, chart/values/options and live UID/resourceVersion or true
  absence bind one-use approval. Catalog/auth receipts are revalidated without a
  network refresh. All-namespace browsing never grants an all-namespace write.
- Values start explicitly from chart defaults or fresh current supplied values;
  computed values are not silently reused. Upgrade uses reset-values and a complete
  private override file. Full editor disclosure is separate and one-use. Drafts
  remain private, editor output must be one valid limited YAML mapping, and every
  edit/source/options change invalidates the earlier review. Normal previews and
  observations conceal values and raw CLI output.
- Mandatory native Helm dry-run and the actual live desired-state comparison are
  separate facts. Old/desired ordinary objects share 256 unique destinations and
  8 MiB of bodies. Supported absent named CREATEs receive separate strict
  `dryRun=All` admission requests (at most 1 MiB each); these neither reserve
  whole-batch quota nor simulate final update/SSA/delete admission or Helm patches.
  Denied/incomplete discovery, collisions and missing served CRD prerequisites
  block preparation. Helm can rerender and race after the final identity checks.
- Hooks default off, wait/resources/Jobs on, timeout 300 seconds (1–600 supported).
  Helm 3 boolean wait and Helm 4 explicit legacy/hook-only modes remain distinct.
  New Helm 4 installs explicitly use client-side apply; upgrades preserve the
  observed method. Automatic rollback/cleanup, force, adoption, post-renderers and
  dependency downloads are disabled. This is not a sandbox for arbitrary templates
  or the trusted editor, nor an atomic multi-object transaction.
- Install/upgrade enumerate skipped CRD file paths through bundled subcharts.
  Uninstall reviews fresh ordinary live ownership, namespace/cluster scope, hook
  events/delete policies, keep policies, PVCs, finalizers and cascade. Keep-history
  defaults true. Purge is deliberate; names are not silently reused. Stored release
  JSON lacks a complete bundled-subchart CRD inventory; this gap stays explicit.
  CRDs are never installed/deleted by this workflow. Helm 3 name-based deletion
  and Helm 4 skip/unverifiable ownership behavior remain explicit limits. History
  removal, resource absence, retained resources and pending finalizers are distinct.
- Read-only blocks catalog mutation/download, values/editor preparation and every
  release-write preparation/execution. Exact private files are consumed under
  scoped argv, debug off, plugins disabled and credential-empty Helm/Docker config.
  Cancellation drains threads, HTTP and process groups before private cleanup and
  client teardown. Launched-write uncertainty survives cancellation; no uncertain
  write replay or unreviewed compensating action occurs.

See the [user workflow](../../workloads.md#choose-a-chart-and-version),
[ADR 0041](../../adr/0041-helm-release-identity.md) and
[earlier M06 acceptance](helm-releases.md). Earlier browse/disclosure/rollback
evidence remains attached to its original source and is not transferred to M09.

## Source and tool identities

Implementation starts from protected main
`d6ee8c7dfc6f7bf057e925f7eb86e792bdf349c5`, tree
`f8e085d78e6f2bd771532ef3901c1f7cd2c4f1ad`. The
[delivered policy receipt](https://github.com/carloshm91/kuberich/issues/80#issuecomment-6787369969)
records #80. Its actual PR CI commit `29c8905` and protected squash are different
identities with matching trees. The reviewed Astra plan was prepared against
`78303d2a36a6eaed5e97292b60b7ae4f2195109f`; it is preserved as planning provenance,
not an implementation or qualification receipt.

The initial Helm contracts are v3.22.1 / source
`d6c1a0e4027caa6abc7892e7ea9f0cda7447baa3` and v4.3.1 / source
`c0d08d0d6d9424d4a14febb5e8a3e51b0dd00dff`, each with both Secret and ConfigMap
drivers. Linux-amd64 binary SHA-256 values pinned in `scripts/helm_tools.py` are
`46aeab5e043f62d01f7c168823b392cabc1cea3807b67906296290483791be43` and
`b66cb19f2b31f9d427632ea6c4b4a1ff89b74ecaeaee323cd166da41a7af53bd`.
Official archive/checksum bytes are pinned separately; this is not a signature claim.

Owned registry setup pins Distribution 3.1.2 Linux-amd64 manifest
`sha256:52b489ad8e6f40d1a676702e3ce398ec796ce38f08fbb786e1f324baa12d84b8`
and image/config ID
`sha256:39a2a88344598be51c03d6829b40dd29fcda04ce1e01ef1f7596b5af744276ce`.
The official image index, source commit and release archive digests are retained
in `scripts/helm_registry.py` and the exact component receipt. No caller Docker
credentials/context or existing Kubernetes cluster is used.

## Measured checkpoints

The following are separate focused working-tree measurements, with overlapping
regressions. They are not added into a fabricated total or relabeled as final
source, whole-production coverage, installed, platform or release qualification.

| Measurement | Retained result and scope |
| --- | --- |
| Catalog/archive/HTTP/private store/helpers | `artifacts/issue233/catalog/full-05.log`: 310 passed; both deterministic modules 100% lines/branches; measured adapters/service each above 90% lines and branches. Separate coverage file/JSON and `catalog-stable-03.json` retain identities. |
| Live Kubernetes adapter | `catalog/live-03.log`: 48 passed; `helm_live.py` 116/116 lines and 44/44 branches. Real owned HTTP/session, finite discovery, scope, identity, RBAC and cumulative limits; not a native-cluster trial. |
| Lifecycle authority | `lifecycle-authority-02.log`: 286 passed in 19.06s after original 284-pass/2-failure authority attempt. |
| Shutdown/teardown | `lifecycle-shutdown-02.log`: 111 passed in 17.83s. Cleanup refusal still closes other owners; cancellation and teardown remain separate facts. |
| Current public UI guards | `ui-guards-01.log`: 40 passed in 20.06s; public actual-root CLI direct/wrapped `ui-public-cli-03.log`: 2 passed in 14.50s. Earlier 56-case UI result retains its prior source identity. |

The first four-way native positive path `artifacts/issue233/spine-04/evidence.json`
passed 20 public operations across both exact Helm versions and both drivers:
production HTTP add/search/select/update/remove, native preparation, install,
upgrade, kept/purged uninstall, independently read resource/storage effects and
no pre-confirm persistent write. It binds 346 frozen **uncommitted working-tree**
inputs; its SHA-256 is
`e2a94c3f0558ee4cec38136f50a44c802f99a83787b40ebc78994f16fb0c2614`.
It is a historical thin-spine checkpoint, not the later full feature or protected
base qualification. Root independently reviewed its identities and cleanup.

The separate actual registry component `artifacts/issue233/registry-01/evidence.json`
passed production OCI registration/version/build-tag/exact-digest retrieval and
update/remove with 339 unchanged input hashes. The exact pinned container and
private/temp files were absent afterward. SHA-256:
`90b0b0de691ff31bae29f256ec22c7b0ca74f7890fc802b0bb9394ae61a7d62f`.
It does not prove Helm lifecycle operations against OCI or later changed source.

Original failed spine attempts remain retained: 01 refused a relative proof-store
path before a release action; 02 encountered metadata `items:null` before preview
and corrected the product parser as well as the independent check; 03 refused
Helm 4 mutually exclusive false force flags after both Helm 3 driver paths.
Their original logs retain cleanup outcomes. Early scoped fixture/lint failures
and subsequent corrected runs remain under their own artifact names; a later pass
does not rewrite an original failure or reconstruct a missing original log.

## Reproduce focused contracts

Use fresh external temporary roots and unique `COVERAGE_FILE`/artifact paths;
the exact historical commands/results remain in their corresponding receipts.
These examples select affected behavior, without launching a caller-context trial:

```sh
COVERAGE_FILE=/tmp/kuberich-helm-live.coverage uv run pytest -q -o addopts='' tests/contract/test_helm_live.py --basetemp=/tmp/kuberich-helm-live-fresh --cov=kuberich.adapters.helm_live --cov-branch
uv run pytest -q -o addopts='' tests/contract/test_helm_lifecycle.py tests/contract/test_helm_lifecycle_faults.py --basetemp=/tmp/kuberich-helm-lifecycle-fresh
```

Real trial commands and tool acquisition belong to
[integration guidance](../../integration-testing.md#reproduce-the-real-trials).
Use `scripts.verify_helm_kind` with explicit kind/Helm paths and fresh evidence;
`--lifecycle-only` is a scoped checkpoint, not the full earlier M06 regression run.

## Final qualification and delivery — pending

- **Pending:** one coherent frozen-current-source native run retaining both Helm
  versions/drivers, earlier M06 regressions, real OCI/catalog public routes,
  admission/quota failures, hooks/retention/CRDs and actual uncertainty/no-replay
  observations, with unchanged input hashes and complete ownership cleanup.
- **Pending:** fresh outside-checkout wheel and supported native-bundle terminal
  evidence for current catalog/values controls, cleanup and source identity.
- **Pending:** exact-head ordinary Application matrix, Repository checks, DCO,
  full/changed coverage and all new source/helper/proof-input enrollment.
- **Pending:** independent final source/artifact review, protected matched-head
  squash, issue acceptance/project completion and clean-main delivery receipt.

The lead fills exact final command, commit/tree, receipt hashes, per-version/driver
outcomes and required-check identities after those operations actually pass.
Real EKS/AKS/GKE/provider trials and cumulative phase/publication remain separate.
