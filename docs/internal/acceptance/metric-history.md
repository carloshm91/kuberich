# Historical metrics acceptance

Issue: [O08 #231](https://github.com/carloshm91/kuberich/issues/231), milestone
v0.4.0. Protected baseline: `5444b7d9c357d389243147a978cc20b248293edb`.
This is an active implementation record, not whole-source or release acceptance.
Publication remains a separate authorized task.

## Boundaries

- Five entity scopes, four measurement families and seven 15m–24h ranges use
  fixed queries, numeric values, explicit source states and finite collection.
- Service proxy and external HTTPS use distinct credential/transport owners.
  Detection and backend selection are explicit; source and historical-identity
  gaps remain visible rather than becoming zero or a parity claim.
- Context/scope/target/configuration revisions reject late work. Removed screens
  remain owned through cancellation; export review retains the detail claim.
- Actual native provider availability must be distinguished from controlled
  synthetic exporter/query evidence. No ambient/customer context is permitted.

The adopted plan, interface contract and 57-pin source revalidation are retained
under `artifacts/issue231/planning/`. The implementation decision is
[ADR 0039](../../adr/0039-context-owned-metric-history.md). User guidance is in
[cluster health/history](../../cluster-overview.md).

## Evidence in progress

The frozen domain cohort passed 273 cases, with exact 100% lines and branches in
all three deterministic modules. Its source hashes, original failures, query
vectors and strict/static results are in `artifacts/issue231/domain/receipt.json`.
Vectors describe generated query profiles; they do not prove provider execution.

The integrated UI cohort passed 21 cases in 42.88 seconds, exercising the five
scopes, regular/init/sidecar/ephemeral containers, seven ranges, family/device
selection, configuration reload and actual export review. Source PTYs passed at
100×30 and 40×12 in 18.36 seconds, with literal navigation, API audit controls,
resize/back/quit and exact terminal restoration. The subsequent strengthened
source-hash replay is recorded separately; these earlier results do not qualify
later edits. Raw synthetic ANSI stays private in ignored artifacts.

Root action/catalog/key/qualifier/CI tests passed 250 cases after correcting the
property fixture's obsolete safe-key set. The original 240-pass/one-failure
result is retained in `artifacts/issue231/root/static-02-original-failure.json`.
New explicit regressions require a per-history override when a shared `b` or `1`
navigation key conflicts with chart controls. The parser's rejection rule and
quality floors were not weakened.

Actual provider trials, installed console/module PTYs, final complete production
coverage, changed-line coverage and exact-head protected CI are still pending.
Do not close this issue from these focused results alone.

## Reproduce focused source trials

```sh
uv run pytest tests/unit/test_history.py tests/unit/test_history_queries.py tests/unit/test_history_membership.py
uv run pytest tests/unit/test_history_workspace.py tests/unit/test_history_http.py tests/contract/test_history.py tests/contract/test_history_http.py
uv run pytest tests/ui/test_history_screen.py tests/ui/test_history.py
uv run pytest tests/terminal/test_history.py
uv run pytest tests/packaging/test_distribution.py -k installed_metric_history
```

The separate provider verifier is `python -m scripts.verify_history_kind`, using
an explicit checksum-verified kind binary and a fresh evidence directory. Its
receipts bind the chart archives, locked dependencies, rendered manifests,
container digests and measured application source. A prepared inventory is not
an executed cluster result. Preserve original failures before corrections.

## Integrated lifetime and installed checkpoints

The final independent action-owner cohort passed 26 cases in 27.24 seconds on
257 unchanged source/configuration bindings. `HistoryActions` measured 198/215
lines (92.09%) and 66/70 branches (94.29%) with no exclusions. It exercises actual
Pulse collection, owned HTTP cancellation, retained screen drainage, captured
scope generations and genuine parent cancellation. The actual App/export-overlay
regression reproduced backend reload permanently invalidating Pulse history;
the corrected reload keeps the detail claim and health owner alive. Original
failure and exact post-fix evidence remain in `domain/actions/receipt.json`.

Node detection had a separate reproduced failure: a cluster-scoped Node target
has no resource namespace even when a namespace is selected in the header.
Detection now uses a separately selected namespace; host metric queries remain
cluster-scoped. The original actual-App failure, one fixed actual-App case and
three focused compatibility cases are in `ui/node-detect-receipt.json`.

Fresh outside-checkout installed wheel console and module entry points both
passed in 26.24 seconds. Their source hashes, wheel SHA-256, API audits and exact
terminal restoration are retained under
`artifacts/issue231/root/installed-01/terminal/`; the bounded runner reaped its
child and recorded the process group absent. These are Linux Python 3.12 local
checks, not hosted/macOS/native release qualification.

The existing Pulse regression cohort initially passed 200 cases and failed two
outdated fake backends before their proxy handlers were reached. It retained
`root/pulse-01.log` and JUnit. Those fixtures lacked newly required Service
discovery/UID reads and treated contributor probes as ordinary metric values.
Their correction and subsequent result must be recorded before acceptance.

The frozen actual-provider verifier is now running against one owned kind
cluster with checksum-verified kind/kubectl and pinned charts/images. Its result
remains pending; preparation and startup alone do not establish acceptance.
