# Helm release workspace acceptance

Issue: M06 #66. Phase: v0.5.0. Install/upgrade/uninstall and repository/OCI product
operations remain M09 #233; their use below is fixture preparation only.

Status: implemented in development source with feature-level verification below.
Candidate-wide coverage and required hosted validation are reported by the live
implementation PR. This does not qualify cumulative phase D09 #82 or authorize
a v0.5 tag, artifact publication or website deployment.

## Implementation

- Native `:helm [NAMESPACE|*]`, namespace picker, metadata filtering/sorting,
  stable namespace/name rows, viewport/history restore, F4 refresh and Enter
  inspection. Helm rows have no fabricated Kubernetes resource UID.
- Status metadata, notes, supplied/computed values, manifest and newest 200
  history revisions. Default notes/descriptions/value scalars and sensitive
  manifest contents are withheld; deliberate one-use disclosure is fresh and
  revealed text remains in its owned viewer only.
- Actual Secret/ConfigMap revision-storage UID/resourceVersion and complete
  bounded metadata pagination guard inspection, disclosure and rollback.
- Explicit prior-revision review, read-only enforcement, default hooks off,
  wait/resources/Jobs on, 300-second timeout with bounded reviewed options.
  Success requires the expected next deployed revision; failed and unknown
  outcomes retain partial-effect and concurrency limits.
- Per-context private argv/environment delegation, no ambient Helm auth/target
  overrides, finite process/parser ownership and cancellation drain before
  credential/client teardown. The optional binary is not probed at startup.

See [ADR 0041](../../adr/0041-helm-release-identity.md) and the
[user workflow](../../workloads.md#browse-helm-releases-in-development-source).

## Scope and tool provenance

The original chart contains only synthetic names, values and credentials. It
uses the shared digest-pinned owned shell image for rollback hook Jobs and
an optional deliberately failing readiness Job. Test code never uses an
operator's current Kubernetes context.

Initial CLI contracts are Helm v3.22.1 and v4.3.1, source commits
`d6c1a0e4027caa6abc7892e7ea9f0cda7447baa3` and
`c0d08d0d6d9424d4a14febb5e8a3e51b0dd00dff`. Official checksum documents,
archive digests, exact binary bytes and sizes are pinned in `scripts/helm_tools.py`.
No artifact signature claim is made. Both Secret and ConfigMap drivers are
tested independently. SQL, memory and untested CLI versions are refused.

Local actual-cluster evidence uses Linux amd64, CPython 3.12.12 and the pinned
kind v0.33.0/node image. Other supported application platforms, real providers
and cumulative phase qualification remain separate evidence.

## Retained development evidence

- Domain: 278 focused cases; three new deterministic modules 100% lines/branches,
  retained in `artifacts/issue66/domain-coverage-final.json`.
- Service/process/storage: 107 focused cases, actual owned fake executable and
  HTTP metadata. Final report `service-coverage-complete.json` records service/
  workspace 100% lines/branches and adapter 100% lines/90.6977% branches.
- UI: 50 focused Pilot/CLI cases and two real PTY sizes (100×30, 40×12), with
  startup scope, sections/history/rollback, resize/refresh/quit, exact terminal
  restoration and unchanged owned kubeconfig. Default-only terminal captures
  exclude disclosed values. Existing command/navigation regressions also pass.
- Root integration: real HTTP/session switching with controlled collection
  producers proves immediate invalidation, reconnect rebinding, retained stale
  rows, unexpected-error reporting and drain before client closure.
- Qualification/tooling: 126 focused cases cover acquisition/extraction, drift,
  symlinks, partial retention, bounds and the actual mandatory workflow's failure
  exit/provenance-retention behavior.

These focused counts overlap existing regressions and are not added into an
invented total. They do not replace the full production coverage gate.

The first actual chart trial, `artifacts/issue66/kind-01/evidence.json`, completed
four functional cases but remains **failed** because source inputs changed
during parallel implementation. Its original result/log are retained unchanged.

The extended frozen trial `artifacts/issue66/kind-02/evidence.json` **passed**
both exact versions and both drivers: four cases with 15 checks each, 289
unchanged source inputs, private config unchanged and owned-cluster deletion
verified. Report SHA-256:
`7612c369d98b7bda75ee904f935826b651e2959ee5a9633c22c9c416d4edd6f6`.
It proves actual install plus two upgrades, duplicate names, all document modes,
redaction/disclosure, rollback effects, hooks off/on, real list-only RBAC GET403,
storage recreation refusal, pending failed hooks, timeout and launched-write
cancellation. Pending outcomes are unknown and refuse another rollback.

The final trial `artifacts/issue66/kind-04/evidence.json` **passed** after
redundant-cancellation hardening and both independently reproduced UI fixes.
It retains four cases with 16 checks each, 290 unchanged source inputs,
eight actual list/history CLI fixtures with binary/argv/hash provenance,
unchanged caller kubeconfig, and verified owned-cluster deletion. Report SHA-256:
`95ec2a01ffde9a1ebc053b5b4376f8fdef1cebcece7493fd5398a5c4bd8854b5`.
It additionally proves a completed readiness failure with an observed failed
revision and partially restored ConfigMap. The private delegation absence check
now matches all `helm-*` files before client teardown. Earlier 02/03 runs used
an ineffective `.yaml` absence pattern for `.json` delegation files; no leak was
observed, and their other observations remain retained without upgrading that
weaker assertion into evidence.

Independent review reproduced an unreachable-startup F4 crash and a pending
value disclosure that could finish beneath a covering help screen. Both are
fixed. Independent confirmation passed 15 exact regression cases, including
F4/`:refresh` recovery with inherited, explicit and all namespaces, and delayed
disclosure/preparation completion across screen suspension. Original failing
logs and the passing review JUnit/log remain under `artifacts/issue66`.

Ruff and formatting pass repository-wide. The actual strict workflow target
union passes across 329 source files (53 declared targets). Full candidate
coverage, packaging and required hosted status remain per-candidate PR evidence;
these feature trials do not qualify cumulative phase #82.

## Reproduce

```sh
uv sync --locked --group dev
uv run python -m scripts.helm_tools --directory /absolute/owned/helm-tools
uv run python -m scripts.verify_helm_kind \
  --kind /absolute/verified/kind \
  --helm3 /absolute/owned/helm-tools/3.22.1/helm \
  --helm4 /absolute/owned/helm-tools/4.3.1/helm \
  --docker /usr/bin/docker --evidence artifacts/helm/evidence.json
```

Use a fresh evidence path and freeze source inputs for the complete run.
The mandatory Linux/Python 3.12 Application gate and local qualifier acquire
the same pinned tools and retain only evidence/provenance, not binaries.
Full static, behavioral, package, independent line/branch/changed coverage and
critical gates follow [the quality policy](../../quality.md).
