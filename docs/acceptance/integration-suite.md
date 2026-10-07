# Q01 #38 disposable Kubernetes and fault qualification

Shared owned-kind setup verifies a generated certificate/TLS endpoint against the actual local Docker control-plane node before fixture writes. It freezes the Docker destination, rejects existing names/replaced nodes, pins the image, uses explicit temporary kubeconfigs and owns bounded process groups and scoped SIGINT/SIGTERM cleanup.

Frozen implementation: `21aac9998225b9c2e5227c8766bb2d304396856a`; base `616c968432c236132ce533be9d7ac302bf70e1b5`. Production tree `adafc145e153014c4fc0a8f74aabd1a965d034a2` remains unchanged from the fully qualified application in #140.

## Actual disposable-cluster outcomes

All three verifiers were repeated successfully on the frozen implementation:

- Real kind context sessions, pagination, list/watch changes and quiet renewals, TLS/client certificates, scope replacement, pod/server Table agreement, namespaces, inspection/events, CoreDNS logs and return/navigation.
- Real kubectl exec with two containers, configured/missing shells, fullscreen vi, resize, Ctrl+C, repeated return, source-config pinning, impersonation and actual restricted RBAC. Synthetic AWS/Azure helpers exercise local contracts; actual EKS/AKS remain #87.
- Actual SIGTERM while the node is being created and after verified readiness exits 143; an injected body failure exits 1. All remove the owned cluster and preserve the initial node inventory and an owned caller-kubeconfig sentinel.

All 27 ownership/process tests pass, including remote/ambiguous Docker refusal, wrong image/role/port/context/TLS/credentials, existing-node nonadoption, replaced-node nondeletion, setup/body failure, cancellation, a second signal during deletion and a resistant real forked process-group timeout.

Commands and pins: [integration testing](../integration-testing.md). Required Linux/Python 3.12 CI includes the context, lifecycle and shell trials; its 45-minute limit accommodates the complete suite plus the additional real cancellation trials. Release-time threefold qualification is explicitly scheduled with per-run artifacts; this implementation does not claim those RC repetitions already ran.

## Measured checks

CPython 3.13.12: 838 affected quality/contract/packaging tests passed in 420.77 seconds. CPython 3.14.3: the same 838 passed in 423.66 seconds. Both also passed Ruff/format, strict 83-file application/tooling types, provider types, plan validation, build/Twine and artifact-linked security gates. These are targeted runs, not newly measured full-application coverage on those minors. Their inherited UI/terminal files are not counted as fresh results.

CPython 3.12.12: the complete **2,274-test suite** passed in 1831.42 seconds. Production lines: 6419/6451 (99.50%); branches: 1891/1936 (97.68%). All 29 critical modules reached 100% lines/branches; changed production lines are N/A (0). Lint/format, strict types, plan validation, independent coverage gates, builds/Twine and installed-runtime security gates all passed.

The final evidence/documentation correction preserves executable/test/workflow trees and every pinned release input. Raw commands, logs, coverage, audited packages, actual-kind outcomes and failure injection transcripts are retained in `/tmp/kubetrol-38-evidence`. Historical acceptance commands remain unchanged; current operational instructions use `python -m scripts.verify_contexts_kind` after its shared module extraction.

## Limits

macOS/arm64 and hosted checks remain unavailable under the documented billing restriction. DCO and measured Linux results support this private merge; full supported-platform CI and the release-time repeated trials remain mandatory before publication in #40. No user active context, real provider cluster, public package, production tag or website was used/published. Coverage and these contracts do not guarantee every cluster/environment.
