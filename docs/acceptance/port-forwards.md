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

Final frozen-head Python 3.12/3.13/3.14 suites, independent production/critical/
changed-line gates, packaging/security/lint/types/build evidence will be recorded
before closure. Hosted checks remain subject to the account billing restriction;
local Linux qualification does not establish macOS or public release readiness.

Numeric TCP forwarding is implemented; no parity claim is made for named ports,
FastForward annotations/presets, unmanaged external forwards or cloud-provider
certification. See #62/#87 and the capability inventory.
