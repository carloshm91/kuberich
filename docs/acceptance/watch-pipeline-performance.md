# Single owned watch parser: Refs Q03 #50

`KubernetesSession.watch_bytes` exposes one complete bounded watch frame at a
time, retaining the existing headers, lifetime, size limits, scope and transport
error policy. `watch_json` remains a decoded compatibility API over this same
owned stream. ListWatch performs JSON object/nonfinite validation and domain or
Table normalization in one owned worker. No parser queue or prefetch is added;
a blocked consumer cannot start parsing another frame. Retry, relist, Table
fallback, resource identity and generation decisions remain unchanged.

The shared decoder is now public `decode_json`; GET and guarded write receipts
retain identical JSON validation. JSON transport parsing uses the existing
repeated-cancellation drain before its owner can close. Normalization errors
and malformed JSON keep their separate safe messages, without response bodies.

## Focused verification

The exact command

```sh
uv run pytest -q tests/contract/test_watch_pipeline.py tests/contract/test_watches.py tests/contract/test_resources.py tests/contract/test_custom_resources.py --no-cov
```

passed **188 cases in 18.39 seconds**, including 19 new actual HTTP cases for
Unicode/chunk/CRLF order, malformed/nonfinite/deep JSON, complete/unfinished frame
limits, incomplete-tail recovery and raw/decoded compatibility. Actual JSON and
domain calls occur on the same non-loop worker; a blocked parser and slow sink
submit no additional work. Repeated cancellation waits for JSON/domain workers
in both success and failure paths, suppresses later emissions and closes the
owned HTTP connection. Compatibility GET/WATCH cancellation is also covered.
Existing Table-header retention/fallback, expiry, authorization, retries and
scope tests passed. An initial new observer compared the auto-valued SyncStatus
to a lowercase string and counted setup workers; it was corrected to the actual
LIVE enum. Its original failing XML is retained as fixture evidence.

The broad affected cohort passed **557 contract/UI cases in 495.21 seconds**
and **20 actual owned source-terminal cases in 61.38 seconds**, without failures,
errors or skips. Both receipts bind unchanged 530-file tracked inventories,
including all 109 production modules. The four owned changed production files
covered **25/25 executable lines** against the actual parent `950f784`; this is
the pipeline correction's scope, not the mixed-ancestry main diff. Receipt
SHA-256 values are `a17f9547c874741b955d9473cfad9390d6554e6acf200c540930bec3e9c4622c`
and `8b1ce9ff6a2c4b829597e30907e5ed6c57d48975ae500756019355641514c847`.
Frozen-head/native checks remain required. Scoped evidence does not establish
whole-package coverage. Ruff/all 474-file formatting, strict types over 133
application/tooling files and four site files, plan validation, wheel/sdist build
and Twine passed; both site surfaces passed their 49-page/1,726-link/64-file checks.

## Resource-only diagnostics

The reference host is Linux 6.8/glibc 2.39, CPython 3.12.12, six CPUs and a
100×30 terminal. A separate owned loopback process independently paces
100 events/s over 10,000 actual dated Pod rows. The unpatched production CLI
uses explicit owned kubeconfig/context/namespace in read-only mode, ordinary
GC (700/10/10), and no coverage, tracing or profiling. The external terminal
observer records actual key bytes, painted selected names and the original
ordered ANSI stream. No normal terminal test bounds are raised.

The paired 30-second actual CLI/PTY observation measured **141.081 ms p95**
before and **96.333 ms p95** after combining workers, with 100 and 107 input
observations respectively. Exactly four production source inputs differ;
controller/source/support inputs match. Both inventories are unchanged during
measurement; normal CLI/source exit, terminal restoration, unchanged kubeconfig,
zero watches after close and zero source overflow passed. Receipt SHA-256 values
are `d8366bb2d1ed86fa5c4e3db0a5d661f844215575347496e61ecd2df21ff451a1`
and `6e0edc5e203c74479c4079cde0dc342621ae0329493e80a825e71670dace0f12`.
This pair precedes the final shared JSON cancellation-drain correction; it is
not relabeled as final-source measurement or a statistically qualified claim.

The final-source actual CLI/PTY observation lasted 30.191 seconds, with 108
inputs and **80.443 ms p95**. Its receipt SHA-256 is
`284d43e1e518cfe3f48e8803a8549385041f840cb9072ea6adf15bbcca014d7b`.
All source inputs match this final production code. The independent producer
created 3,017 events, with 3,016 sent and one separately bracketed at pause;
overflow was zero. Terminal/source exit, restoration, unchanged kubeconfig and
zero final watches passed. This remains a single resource-only observation.

A headless normal-GC resource-only diagnosis measured 6.724 ms key-to-cursor
p95 and 16.895 ms public post-refresh p95, but a **1.531-second maximum heartbeat
gap** and observed version `q03/2315` still behind 3,014 independently produced
events. Its client, watch, renderer and source process closed normally. These
failures remain visible; low ordinary-input percentiles do not establish
sustained throughput or freedom from stalls.

Original argument vectors, source digests, timestamps, XML and receipts remain
under ignored `artifacts/watch50`; the producer/controller copies retain their
own inventories. The generators are diagnostic working files, not a completed
checked-in Q03 benchmark implementation.

## Original preceding-candidate failure

PR #176's original head `950f7840d03a0e7748bca46473b4bd45788e21bf`, run
`38036838862`, macOS job `114168938936` failed its required suite: 4,267 passed
and one failed. The noninstrumented positive aggregate runtime child measured
**165.123 ms** during round-two history input delivery, against the unchanged
150-ms limit. It completed only one full-history round; the normal after-viewer
record is absent, while the final application cleanup receipt records zero
registered viewers, API streams and watches. Its unchanged source inventory,
enabled default GC and absence of coverage/tracing/profiling were verified.

The original pulse records 165.314 ms process CPU and 0.943 ms main-thread CPU.
No retained slow-GC interval overlaps that pulse; bounded callback retention
does not prove the absence of all earlier collection. These observations alone
do not establish the cause. Passing working-source pipeline checks do not
qualify this failed candidate, and no CI retry replaces the failure.
Original artifact `11665006325` has ZIP SHA-256
`53afbc286c6503d1632e551aa6b6c18a27dd9da4d1ac0503329b7cd6c5b62f68`;
its positive heartbeat SHA-256 is
`ffcf1cc9db17bb2c6628c7a58b309231efb099796a44a2dbaa64fbc2f3174b93`.

Q03 remains open for combined 100 resource events/s and 2,000 logs/s,
10,000 retained lines, sustained p95 below 100 ms, a 30-minute memory plateau,
and context/slow-consumer/cancelled-forward lifecycle evidence. No workload,
timing/coverage gate, dependency, version or publication policy changes here.
