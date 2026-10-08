# S05 #42 acceptance evidence

Managed forwards use the actual owned ProcessRunner, captured SDK connection and
explicit kubectl argv. Readiness is parsed from bounded real stdout, checked
against the requested address/mappings, process health and a second target UID
read. Namespace/view changes retain sessions; client replacement drains them
before SDK/private-directory teardown. Stop and app exit drain owned work.

## Focused behavior qualification

- Pure mapping, address, scoped argv, UID/phase and chunked readiness contracts:
  100% of 144 executable lines and 64 branches in `domain/port_forwards.py`.
- Real child processes and owned IPv4/IPv6 TCP listeners test traffic, dynamic
  ports, Service backend translation, occupied ports, failures/timeouts/flood,
  process death, deleted/recreated/denied targets and connection loss.
- Repeated cancellation during private-file creation/removal and collision
  probing drains the owned threads; context/exit barriers reject later starts.
  Active/recent limits, immediate cancellation and deliberate repeated stops
  leave no owned child, listener or forward file. Streaming output drains
  consumed bytes without undoing an already detected overflow.
- Pilot exercises 40×12 and 100×30 forms/lists, invalid mappings, filtering,
  deliberate stop, namespace retention, retry cleanup, read-only policy and
  input routing. Related standard-view/navigation regression: 211 passed.
- Actual source and freshly built installed-wheel console/module PTYs exercise
  rapid mapping editing/submission, list/return, payload, resize, repeated starts,
  stop and exit with an active forward. The harness checks terminal attributes
  and control restoration against the original PTY modes.

## Actual Kubernetes transport

```sh
uv run python -m scripts.verify_port_forwards_kind \
  --kind /tmp/kubetrol-tools/kind \
  --kubectl /tmp/kubetrol-tools/shell/bin/kubectl \
  --evidence /tmp/kubetrol-42-evidence/kind.json
```

A freshly owned kind cluster first passed generated kubeconfig-to-Docker-node/API
identity verification. Real Kubernetes 1.36.4 and matching kubectl forwarded HTTP
through two dynamic Pod ports and an explicit local Service port 80 translated to
backend 8080. Actual payloads, namespace retention, deliberate stop, repeated use,
Service deletion, same-context reconnection and app exit passed. Processes and
listeners disappeared; private forward files/TLS directories were removed in
order. The source kubeconfig stayed byte-for-byte unchanged. The owned cluster
was deleted and its absence verified; no external cluster was used.

The verifier pins kind/node/kubectl and
`busybox:1.37.0@sha256:bdf57e528e45e4433820e045b29b4597825a1c9e38353532d90a01445013f82e`.
The first fixture run failed because the previous Alpine shell image lacked
`httpd`; its owned cluster still cleaned up. A subsequent real-network run caught
TIME_WAIT being falsely classified as an active listener collision. The probe now
uses kubectl-compatible address reuse; an existing listener still fails, while
an explicitly released port can be reused after real traffic. Final passing
qualification supersedes those retained failed trials.

## Whole-suite and delivery qualification

The final source tree is `dfcfb4310f3a499d9d7b9cd9e7951ce6d5bb5b85`:
root commit `88aaa6f` and detached matrix commit `a989baa` contain identical
production code and tests. Documentation-only delivery changes follow these runs.

| Actual Linux interpreter | Complete suite | Lines | Branches | Changed executable lines |
| --- | --- | --- | --- | --- |
| CPython 3.12.12 | 2,596 passed, 1,862.68 s | 7,374/7,414 (99.4605%) | 2,137/2,190 (97.5799%) | 656/664 (98.7952%) |
| CPython 3.13.12 | 2,596 passed, 1,318.14 s | 7,374/7,414 (99.4605%) | 2,137/2,190 (97.5799%) | 656/664 (98.7952%) |
| CPython 3.14.3 | 2,596 passed, 979.36 s | 7,236/7,276 (99.4502%) | 2,137/2,190 (97.5799%) | 639/647 (98.7635%) |

Each independent gate verifies all 79 production Python files, no coverage
exclusions, both global floors and 100% lines/branches for all 31 critical modules.
Interpreter-dependent executable-line inventories account for the different
3.14 denominator. Changed lines compare against main `7e048ec`, using committed
changes only. Commands run in each corresponding frozen checkout:

```sh
uv run --python 3.12 pytest --cov=kubetrol --cov-branch --cov-report=xml:/tmp/kubetrol-42-evidence/py312.xml --cov-report=json:/tmp/kubetrol-42-evidence/py312.json
uv run --python 3.12 python scripts/check_coverage.py /tmp/kubetrol-42-evidence/py312.json
uv run --python 3.12 diff-cover /tmp/kubetrol-42-evidence/py312.xml --compare-branch 7e048ec7b2d3b0e7a76c60ed44cc99773947cae1 --fail-under 90 --ignore-staged --ignore-unstaged --total-percent-float --format json:/tmp/kubetrol-42-evidence/py312-diff.json
```

The 3.13/3.14 runs use their explicit interpreter and corresponding report paths.
Ruff/format (313 files), strict types (93 application/gate/verifier files), plan
validation, whitespace and actionlint passed. Actionlint's optional shellcheck
and pyflakes integrations were disabled; their success is not claimed. Wheel and
source builds passed Twine. Artifact-linked audits of both locked and freshly
resolved installed runtimes passed for 27 dependencies, with no accepted
exceptions. The full suite also exercises real isolated uv-tool/pipx installs,
source/installed PTYs and package metadata/content/rebuild contracts.

Initial full attempts caught an outdated import in the opt-in EKS verifier after
private connection staging was shared; correcting that import restored all 13
provider-verifier contracts. A passing baseline matrix was then superseded by
the complete final matrix above after a real 40×12 rendering check caught a
header without a visible data row. The compact footer now leaves a visible row;
Pilot and source/fresh-install PTYs explicitly assert it. Failed trials and both
matrices remain under `/tmp/kubetrol-42-evidence`, alongside SVG/PTY evidence.

Actual-kind qualification also passed with an IPv6 `::1` bind and HTTP payloads.
The existing actual-kind shell verifier passed against the shared delegation
refactor, including TLS/impersonation, restricted RBAC, two-container exec,
fullscreen programs, resize/interrupt, repeated return and terminal restoration.
Those transport trials precede the final CSS-only refinement; their service,
adapter and domain sources are identical to the final tree. Every owned cluster
was deleted and its absence verified.

Hosted jobs did not start: annotations identify failed account payments or a
spending-limit restriction. DCO passed on the implementation head; unavailable
Actions use the authorized private local-verification workflow. Local Linux
qualification does not establish macOS, live EKS/AKS or public release readiness.

Numeric TCP forwarding is implemented; no parity claim is made for named ports,
FastForward annotations/presets, unmanaged external forwards or cloud-provider
certification. See #62/#87 and the capability inventory.
