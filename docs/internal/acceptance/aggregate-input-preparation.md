# Bounded aggregate input preparation: Refs Q03 #50

The original runtime fixture prepares its second 5,000-line dataset in one
owned worker call. Production `KubernetesSession.log_bytes` reads at most
8 KiB per transport turn. The runtime fixture now prepares that same dataset
through owned turns bounded by the encoded line size and this byte budget.
It still exercises the complete retained window, two full-history rounds,
four navigation/reopen/picker/theme warm cycles and both 40×12/100×30 sizes.
Dataset content, source identities, clipboard/save/previous behavior and memory
limits are preserved. This aligns fixture input work with the transport contract;
it does not change application code or certify Q03's combined workload.

The parent verifies actual refill receipt values: 5,000 records, more than one
batch, maximum bytes within 8,192 and maximum records below one source window.
The measured fixture uses 230 batches, at most 22 records / 8,184 bytes each.
Maximum prepared records remain 5,000 and retained-plus-prepared remains 5,001.
The 150-ms positive heartbeat target, enabled default GC, source/nonce checks,
120-second owned-process deadline and 256-KiB output bound are unchanged.
The deliberate 200-ms callback must still fail the negative control. Coverage
replay proves functionality separately and does not qualify latency.

## Scoped local evidence

```sh
uv run pytest -q tests/ui/test_aggregate_logs.py tests/contract/test_aggregate_logs.py --cov=kuberich --cov-branch --cov-report=json:artifacts/refill50/coverage.json --cov-report=xml:artifacts/refill50/coverage.xml --cov-report= --junitxml=artifacts/refill50/final-aggregate.xml
```

All **30 cases passed in 132.62 seconds**. The final normal positive child
measured **114.769 ms** and completed both rounds; the expected negative child
failed at **206.152 ms**, while the instrumented functional replay completed
both rounds. Each owned process drained; both successful children retained
5,000 records and verified the bounded refill. Viewer/readers/registry/log
streams closed; one unchanged background workspace watch remained until full
application cleanup, which then recorded zero watches/streams/viewers.

Parent/child before-and-after source stamps verified 165 unchanged inputs,
including all 109 production modules, the test fixture and runtime owner.
The final runtime receipt SHA-256 is
`56cc8c96c962f5a12fc73d85f83d99a4b85e9589c773783bd3af6ff1c51c29a0`.
An earlier working fixture before the final explicit argument binding passed
its runtime node and remains under `artifacts/refill50/initial-*`; it is not
relabeled as final-source evidence. Ruff caught the implicit loop captures;
the final fixture uses explicitly captured `partial` arguments.

Subsequent Ruff formatting only wraps that same call over multiple lines.
An independent full-module AST comparison matched before/after; original runtime
source hashes remain unchanged in their receipts. Native checks must bind the
formatted committed source. Plan, Ruff, strict types, wheel/sdist build/Twine
and both 49-page site build/link checks passed after formatting.

Required frozen-head/native checks remain outstanding. The preceding original
macOS failure is preserved under [watch pipeline evidence](watch-pipeline-performance.md).
Its 165.123-ms pause is not made successful by later local passes; the original
cause remains unestablished. No original CI run is retried. Q03 remains open for
sustained resource/log throughput, 10,000-line retention, input p95, the
30-minute memory plateau and lifecycle qualification.
