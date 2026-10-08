# Disposable Kubernetes and fault qualification

Q01 #38 combines owned API/credential fault servers with real local kind trials.
Every ordinary pytest connection is restricted to owned temporary configuration
and registered numeric loopback endpoints by `tests/conftest.py`. Missing fixture
setup never falls back to the active context. Fault fixtures and synthetic
provider helpers do not establish real cloud-provider certification.

## Required paths

| Behavior | Contract suite / real kind evidence |
| --- | --- |
| Pagination, consistent resource versions, discovery and permissions | `tests/contract/test_resources.py`, `test_sessions.py`; context verifier |
| HTTP framing, EOF/reconnect, 410 relist, bounded queues/backoff and cancellation | `tests/contract/test_watches.py`; real updates and quiet renewals |
| Rapid scope switches and rejection of late responses | `tests/contract/test_workspace.py`; Pilot and context verifier |
| Unicode logs, previous-log errors, denied reads, abrupt disconnect and retention | `tests/contract/test_logs.py`; actual CoreDNS logs |
| Exec scope, missing shell, fullscreen program, resize/interrupt and restricted RBAC | `tests/contract/test_shell.py`, real PTYs and shell verifier |
| Pod/Service TCP payloads, readiness, target loss, context/exit cleanup and private files | `tests/contract/test_port_forwards.py`, Pilot/PTY and port-forward verifier |
| Guarded annotation writes, stale UID/version tests and actual patch RBAC denial | mutation contracts/Pilot/PTY and mutation verifier |
| Private manifest drafts, strict dry-run, separate Apply, validation/conflicts and patch RBAC | editing contracts/Pilot/PTY and editing verifier |
| Expiring/rejected credentials, concurrent refresh and helper faults | provider/session contracts; synthetic helpers with real kind tokens |
| Unsafe node/config refusal, setup failure, repeated cancellation and process timeout | `tests/quality/test_owned_kind.py`; real lifecycle verifier |

AWS/EKS and Azure/AKS certification remain Q05 #87. Maximum-workload performance
belongs to Q03 #86; repeated bounded contracts do not establish a benchmark.

## Ownership before writes

The Kubernetes verifiers use `scripts.owned_kind`. It freezes a local Docker
Unix-socket destination, removes conflicting context/TLS overrides and forces
the Docker provider. It refuses an existing generated name, creates an explicit
temporary kubeconfig and pins the node image by digest.

Before API fixture writes, the generated context/references, certificate-only
credentials, TLS settings and numeric-loopback HTTPS port must match the actual
Docker control-plane node's labels, image and ID. Cleanup rechecks membership and
refuses a replaced node. `kind delete` receives the same explicit kubeconfig.
Creation and deletion preserve the caller's default context.

Owned process groups have deadlines and terminate/kill cleanup. SIGINT/SIGTERM
exit with 130/143 after cleanup; repeated signals are ignored during deletion and
previous handlers are restored. SIGKILL cannot run Python cleanup and is outside
this graceful-cancellation claim.

## Reproduce the real trials

Use local Docker, verified kind 0.33.0 and kubectl 1.36.4. Required Linux/Python
3.12 CI checksums its own downloaded tools without replacing global executables:

- kind Linux amd64 SHA-256: `aee6151561422756b764a4ae28e7f44cda5af5a9eead3cc9985112b1de8d8e0d`
- kubectl Linux amd64 SHA-256: `8b8f088da2dab964f853b38464033b1be15ede2839eca751482357c45abdd05a`
- node: `kindest/node:v1.36.4@sha256:099e049362a1526b2db71494e1947aae99bd16290d7c895f2b7ea312e3cbfaed`

```sh
uv sync --locked --group dev
uv run pytest -q tests/quality/test_owned_kind.py tests/contract
uv run python -m scripts.verify_contexts_kind --kind /absolute/path/to/kind
uv run python -m scripts.verify_kind_lifecycle --kind /absolute/path/to/kind
uv run python -m scripts.verify_shell_kind --kind /absolute/path/to/kind --kubectl /absolute/path/to/kubectl
uv run python -m scripts.verify_port_forwards_kind --kind /absolute/path/to/kind --kubectl /absolute/path/to/kubectl
uv run python -m scripts.verify_mutations_kind --kind /absolute/path/to/kind
uv run python -m scripts.verify_editing_kind --kind /absolute/path/to/kind
uv run python -m scripts.verify_workloads_kind --kind /absolute/path/to/kind
uv build
uv run python -m scripts.verify_quickstart --wheel dist/kuberich-0.0.1.dev0-py3-none-any.whl --kind /absolute/path/to/kind --kubectl /absolute/path/to/kubectl
```

The lifecycle controller sends actual SIGTERM during node creation and after
verified readiness, then injects a body failure. Every case must remove its own
cluster, preserve the initial node inventory and retain an owned caller kubeconfig
sentinel unchanged. Run cluster trials sequentially so inventory comparisons do
not overlap another process creating/removing clusters.

## Release-time repetition

Required PR/main CI runs the complete suite and all eight real rehearsals once
(contexts, lifecycle faults, shell, port forwards, mutations, editing, workloads and installed quickstart).
Before each canonical RC publication, and after client/runtime or lifecycle
changes, repeat the contract suite and all eight real rehearsals three consecutive
times on the exact candidate checkout. A failure blocks qualification; retain
its evidence and diagnose before repetition.

Use `--evidence artifacts/cluster/rc-N-contexts.json`, `rc-N-lifecycle.json`,
`rc-N-shell.json`, `rc-N-port-forwards.json`, `rc-N-mutations.json`, `rc-N-editing.json`, `rc-N-workloads.json` and `rc-N-quickstart.json`, for
N=1,2,3. Use that candidate's exact wheel filename for the quickstart. Preserve
per-run logs, duration, exit status,
candidate SHA, tool versions/digests, configuration invariance and node inventory.
Archive `artifacts/ui`, `artifacts/terminal` and `artifacts/cluster` after each run
so repeated screenshots do not overwrite earlier evidence. Hosted quality retains
these directories even on failure. Link release-time evidence from D04 #40;
a documented schedule is not a claim those repetitions ran.

Sources: [kind explicit kubeconfig/provider](https://kind.sigs.k8s.io/docs/user/quick-start/),
[Docker context precedence](https://docs.docker.com/reference/cli/docker/),
[Python process groups](https://docs.python.org/3.12/library/subprocess.html).

Measured commits, counts and limitations: [Q01 acceptance](acceptance/integration-suite.md).
