# Forward presets and transport: S08 #62

This extends the existing owned Pod/Service forward controller. It does not
publish a package or change the immutable 0.1.0 distribution.

## Captured behavior

- Pure mapping resolution accepts literal numeric/named TCP ports and explicit
  regular-container qualification. Missing/ambiguous/UDP declarations fail;
  Service names resolve to Service ports, not guessed backend numbers.
- Versioned local preferences own named presets, exact-context replacement and
  auto-annotation permission. Cluster metadata never grants that permission,
  chooses a bind address or initiates work while listing resources.
- The existing Start guard applies before preparing credentials or launching
  children. Non-loopback presets need their own unchecked-by-default opt-in.
- Automatic annotation shortcuts apply only to an explicit forwarding action
  after local opt-in. Without it, annotations populate the ordinary review form.
- The child transport flag preserves captured environment in auto mode, sets
  `KUBECTL_PORT_FORWARD_WEBSOCKETS=true` for WebSocket preference (including
  kubectl's documented fallback), and `false` for SPDY. No wire negotiation
  observation is claimed from an environment flag.
- Zero retries remains the default. Explicit budgets 1–3 reconnect only after
  process disconnect. The old ownership stack cleans up first; each new process
  gets fresh delegation and preflight. UID/403/404/context/readiness/collision
  failures, cancellation and Stop are terminal for that controller.

Captured named mappings are rechecked at preflight, readiness and monitoring.
Reassigning a Service port name under the same UID requires new review rather
than forwarding to an unreviewed number. Backend target-port changes retain
the captured Service port and can be picked up on an opted-in restart.

## Verification sources

`tests/unit/test_forward_presets.py` covers literal grammar, container/Service
resolution, unsafe and oversized values, duplicate local ports, annotation
precedence, transport isolation, explicit local permission and context scopes.
`tests/contract/test_forward_reconnect.py` uses real owned subprocesses and TCP
listeners to verify payloads after reconnect, old PID/listener removal, fresh
private paths, finite retry budgets and failures/cancellation during backoff.
The original numeric/IP/readiness/cancellation/history contracts remain required.

Pilot exercises the forms at 40×12 and 100×30, local presets, named ports,
remote-bind refusal, invalid preferences, default review and explicit exact-context
annotation permission. Source and genuinely installed wheel console/module PTYs
exercise named annotation defaults, traffic, navigation, resize, Stop/exit and
the unchanged terminal restoration oracle.

The extended `scripts.verify_port_forwards_kind` uses only its own disposable
cluster. It resolves declared Pod/Service names and annotation syntax, sends HTTP
through both selected kubectl transport modes, changes a Service selector/backend
port, then induces a real process disconnect and verifies the distinct backend
response on reconnect. It also verifies non-loopback opt-in, namespace retention,
resource/context invalidation and process/listener/file cleanup. These owned
fixtures are not real EKS/AKS/GKE certification.

## Measured results and delivery

The initial focused command passed **218 tests in 98.18 seconds**, including pure
contracts, owned HTTP/process listeners, compact/normal Pilot forms and actual
source/installed-console/module terminals. Both new deterministic modules and
the original forward domain measured **100% line and branch coverage**. Strict
application/owned-kind-verifier types, Ruff and formatting passed.

```sh
uv run pytest -q tests/unit/test_forward_presets.py tests/unit/test_port_forwards.py tests/contract/test_port_forwards.py tests/contract/test_forward_reconnect.py tests/ui/test_port_forwards.py tests/ui/test_forward_presets.py tests/terminal/test_port_forwards.py tests/packaging/test_forward_presets.py --cov=kuberich --cov-branch --cov-report=xml --cov-report=json
uv run python -m scripts.verify_port_forwards_kind --kind /absolute/path/to/pinned/kind --kubectl /absolute/path/to/pinned/kubectl
```

The final owned-kind run verified named annotation defaults, both transport
selections, real HTTP, owned/external listener collisions, explicit remote bind,
Service backend replacement (8080 to 8081), reconnect, deletion, namespace
retention, context replacement and exit. Source kubeconfig bytes remained
unchanged. All processes/listeners/private files closed and the owned cluster
was deleted with absence verified. Pinned node, BusyBox and tool hashes and
actual per-scenario receipts remain in the original qualification artifacts.

Initial retained failures caught an incorrect CLI test expectation (invalid
preferences exit 2, not 3) and a kind fixture inspecting the newest deliberately
failed collision record instead of its captured live-forward identity. Correcting
those observers preserved the original behavior assertions. A later review added
same-UID Service-name reassignment checks; the final 218-case run and fresh kind
run qualify that additional protection, not just the earlier source.

Original focused reports, PTY transcripts/restoration receipts and failed/successful
kind logs are retained under `artifacts/forward62-*`, `artifacts/terminal` and
`artifacts/cluster`. The protected PR checks retain the complete platform/native,
whole-production and changed-line qualification separately; this focused result
is not a claim that every production module was exercised by these 218 cases.
The phase gate and public release activation remain separate work.

## Startup failure regression

A final review distinguished a disconnected established forward from a child
that never became ready. Two real-process negative controls reproduced the old
behavior: initial and replacement configuration errors consumed all three retries
(2 failures in 4.62 seconds). The controller now allows reconnect only after
READY; an initial or replacement startup failure terminates without another
helper invocation. No output matching, deadline or retry-budget limit was relaxed.

The corrected source passed **220 focused tests in 79.79 seconds**, including
both regressions and the original unit/HTTP/Pilot/source/installed-terminal cases.
Both new deterministic modules and the existing forward domain retained 100%
line and branch coverage. The earlier full local suite remains frozen on original
commit `2af1b83`; it is supplemental baseline evidence, not a full-suite result
for this correction. Fresh complete protected source/native/owned-kind checks
qualify the corrected PR head before merge.
