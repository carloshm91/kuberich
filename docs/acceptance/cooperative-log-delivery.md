# Cooperative dense-log delivery: Refs Q03 #50

An immediately completing async consumer previously received 4,096 tiny lines
from one 8-KiB transport read before pending input ran. Three actual-HTTP
regressions reproduced that behavior on the preceding `46c4dea` source: ordinary
input, cancellation and target invalidation each failed the requirement to run
before the first 1,000 lines. Their original XML/logs remain under ignored
`artifacts/delivery50`; the baseline added only the reproducing cases.

Production delivery now yields cooperatively after at most 32 lines, awaiting
the consumer in order and checking the captured target before each next line.
There is no producer queue, dropped output or moved consumer thread. Normal EOF
still delivers the final partial line exactly once. Slow-consumer backpressure,
UID checks, parser-worker ownership and response closure remain required.

## Original native failure

PR #176 source `46c4deaa1b4ba703d561dbb1f2326f0a68b30750`, tree
`b7926512f5a3307205f40b11c8f20a81c1b5413a`, ran in `38043506336`.
Each Linux environment independently passed 4,308 cases. Minimum measured whole
line/branch coverage was 99.1053% / 96.8750%; all 43 critical modules and 101
changed executable lines met 100%. Exact Git comparisons verified all 109
production modules and 111 payloads per distribution, plus original installer,
security, runtime and 215/203/203 terminal receipts. These Linux observations do
not qualify a failed candidate.

macOS/Python 3.12 job `114188310394` passed 4,307 cases and failed the tiny-line
backend heartbeat: 561.710417 ms against 150 ms. The diagnostic records active
CTracer coverage and development-only IRI grammar imports. A worker-thread
generation-two collection of 534.620167 ms overlaps the worst gap. The complete
32,771-line workload, slow source, both retention limits and final zero owned
tasks/log streams/watches passed. This observation does not establish the full
cause or prove an installed runtime meets the latency budget.

Original artifact `11667672199` has ZIP SHA-256
`bb790a6ee55f0fd87826fbed7c44ce10a1e90d7e2efc5e72dbcde2d4484c5cff`.
All 118 diagnostic input hashes independently match the pinned Git source.
The diagnostic SHA-256 is
`53b6c0abc40c83c8cc7245a4947e4996138711ce3bbcb6a6bed2c9f2b0973993`;
the independent failure review SHA-256 is
`384f5a0918fc51859aa4ccc67b380a11bd39efa3d1eaff75e6e047a5b8d43d55`.
No retry or failed-head merge replaces these originals.

## Runtime measurement contract

The original HTTP test runs the full 32,768-line burst, seed lines and slow-source
delivery in the parent branch-covered suite. Its retention, 30-second receive
deadline, source identity and final ownership assertions remain unchanged.
Two mandatory fresh children execute the same test node with normal GC and
its unchanged thresholds, without coverage/trace/profile callbacks or the
development grammar. The positive child must meet the original 150-ms maximum
heartbeat. The negative child schedules a deliberate 200-ms callback and must
fail specifically that assertion while preserving the full workload and cleanup.
Neither child generates coverage. The parent supplies the original functional
coverage; UI replay coverage remains a separate measured union.

Both controls require unique source-bound nonces, XML proving the exact case,
complete artifact hashes, actual import/instrumentation facts and drained owned
process groups. Each uses a 60-second deadline and 256-KiB output limit. Before
merging UI replay coverage, the required entry point independently verifies
both controls and the original branch-covered backend diagnostic, then verifies
their unchanged identity after the merge. Missing, stale, incomplete, altered,
instrumented or unrelated-failure evidence rejects qualification.

## Working-source verification

```sh
uv run --locked --python 3.12 pytest -q tests/unit tests/contract tests/ui/test_aggregate_logs.py tests/ui/test_logs.py tests/ui/test_sessions.py tests/quality/test_backend_runtime.py tests/quality/test_backend_heartbeat.py tests/quality/test_runtime_coverage.py --cov=kuberich --cov-branch
```

This passed **3,077 cases in 440.60 seconds**. Eleven actual source-terminal
cases passed in 33.75 seconds; Python 3.13 and 3.14 each passed 149 focused
log/parser/formatting and gate-regression cases. Four receipts bind 537 unchanged
tracked inputs, including all 109 production modules, with no failures/errors/
skips. Broad and terminal receipt SHA-256 values are
`24fe5996e4805c95e01b0dfcbca214477edd4e88c18e64811912e250f3a9fed3`
and `be9d213624e02db0dcc089fbc2110fb168a12b9092bcb99c5f3fe08dc4df82e7`;
Python 3.13/3.14 receipts are
`6abc44abb6ba72daf9d526003307a0198125d3bb74e615a630eeb5d0cea34d54`
and `9573fa097646f9024bf0d3faf0530baae497c1655b00b6a4777f256a7320138f`.

The required coverage entry point independently verified both backend controls,
the original covered workload and all three UI controls before merging only
successful UI replay arcs. All 43 critical modules and the 13 owned changed
executable lines measured 100%. Scoped overall coverage was **89.2635% lines /
86.6836% branches**; this is not qualification of the whole-package gates. A
new frozen-head/native run remains required.

The normal backend child measured **31.011 ms** and the deliberate negative
child failed at **201.247 ms**. Both delivered 32,771 lines, retained both bounds
and drained tasks/log streams/watches to zero. The UI positive child completed
both warmed 5,000-record rounds at 117.544 ms; its negative control failed at
202.418 ms. Branch-covered UI replay completed both rounds at 174.283 ms,
explicitly nonqualifying timing, with final whole-app cleanup.

Ruff/formatting, the complete 133-file strict type command, the 12-epic/79-task
plan, both static-site build/link checks and wheel/sdist build/metadata checks
passed locally. Gate regression fixtures verify rejection behavior and are not
performance evidence. These receipts precede final documentation; the frozen
native candidate still needs qualification. Q03 remains open for the combined
independent workload, 10,000 retained
lines, sustained p95 below 100 ms, 30-minute memory plateau and lifecycle audit.
