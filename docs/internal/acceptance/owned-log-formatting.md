# Collected parser outcomes and bounded log formatting: Refs Q03 #50

JSON/domain workers keep ownership through repeated cancellation. Their shield
now protects a `gather(return_exceptions=True)` collector; ordinary completion
returns the original task result or exception. In CPython 3.14.3, cancelling a
shield around a still-running task adds a callback that reports its later error
to the loop handler. Consuming the task afterwards does not remove that callback.
The collector consumes this error as data before the cancelled owner returns.
This uses public asyncio APIs; no exception handler or private callback is changed.
[CPython's pinned implementation](https://github.com/python/cpython/blob/v3.14.3/Lib/asyncio/tasks.py)
and [the public shield contract](https://docs.python.org/3.14/library/asyncio-task.html#shielding-from-cancellation)
support this distinction.

Aggregate layout/export formatting captures immutable records, mode, timestamps
and exact UID/container filter before awaiting. Owned turns format at most 32
records and 8 KiB of reserved output. A single larger retained record gets its
own turn without splitting or dropping it. Turns run sequentially, preserving
arrival order, redaction and byte-for-byte plain/JSON behavior. Repeated
cancellation waits for the active worker and starts no further turn. The UI
retains its generation/current-target checks and final owned export join.

## Original failure retained

The preceding source was `087ee65ba1f6b93df861a0459f0f34a4abdc27a8`, tree
`055ef922ce799fe423e992079a9873fce6e939fa`, tested checkout
`725b6461dfc5c0d47119c97345f92a695dfaafca`, run `38040168134`.
Linux 3.12 and 3.13 each independently passed 4,287 cases. Minimum line/branch
coverage was 99.1096% / 96.9526%; all 43 critical modules and 72 changed executable
lines met 100%. Original artifacts matched 109 production modules, 111 payload
files in both distributions, installer/security/runtime evidence and 215/203
native terminal receipts. This does not qualify a candidate whose other required
environments failed.

Python 3.14 job `114178671765` passed 4,285 cases and failed two combined-parser
cancellation cases through the loop handler. Original artifact `11665956588`
has ZIP SHA-256
`977bc3ffcba0a2f2c98e9e3147d16ee71b7db1cb6af8a95f57a984da46f1744e`.
A confirmed local CPython 3.14.3 baseline reproduced the same two failures:
17 passed, two failed in 0.84 seconds. Explicit `uv run --locked --python 3.14`
commands bind the interpreter; the earlier default-interpreter observation is
not Python 3.14 evidence.

macOS job `114178671771` passed 4,286 cases and failed the required positive
runtime heartbeat: **151.066541 ms** during round-two save against **150 ms**.
Only one full-history round completed; the normal after-viewer record was absent.
The final whole-app receipt records zero viewers, log streams and watches.
All 165 unchanged input hashes match the pinned Git source. Default GC was
enabled, and coverage/trace/profile instrumentation was inactive. A generation-two
collection of 49.647208 ms overlaps the worst pulse; that observation does not
establish the full cause. Original artifact `11665518680` has ZIP SHA-256
`5b96c7e97632d70c68f0a9075c87ac5546db36d6419b5ece290b909ebc491385`.
Its heartbeat SHA-256 is
`e3bd9c8768adab8263a1460ac45eaf05b9291359134386be1d976c870e60ff42`;
the independent original-failure review SHA-256 is
`6c04a89cd71b049a03ae892981b90248a212e05ef6aa4de829b071df124a1734`.
No CI retry, weakened assertion or failed-candidate merge replaces these failures.

## Working-source verification

The focused command is:

```sh
uv run --locked --python 3.14 pytest -q tests/contract/test_watch_pipeline.py tests/contract/test_custom_resources.py tests/contract/test_resources.py tests/contract/test_watches.py tests/contract/test_aggregate_format.py --no-cov
```

It passed 209 cases on each of Python 3.14 and 3.13, including exact normal
result/error forwarding, late-error-free compatibility GET/WATCH cancellation,
combined parser drain, literal Unicode/redaction, exact source filtering,
oversized single-record handling and cancellation during first/later formatting
turns. The actual worker finishes before cancellation returns; no later turn
starts and the loop receives no unhandled error.

The broad command is:

```sh
uv run --locked --python 3.12 pytest -q tests/unit tests/contract tests/ui/test_aggregate_logs.py tests/ui/test_logs.py tests/ui/test_sessions.py --cov=kuberich --cov-branch
```

It passed **2,992 cases in 396.92 seconds**. Actual source-terminal checks passed
**11 cases in 33.82 seconds** with:

```sh
uv run --locked --python 3.12 pytest -q tests/terminal/test_logs.py tests/terminal/test_aggregate_logs.py tests/terminal/test_pods.py tests/terminal/test_contexts.py tests/terminal/test_custom_resources.py --no-cov
```

All four receipts bind 532 unchanged tracked inputs, including all 109 production
modules, with no failures/errors/skips. Broad and terminal receipt SHA-256 values
are `b85ef539ceed8e3ad67869803e282deb01e0c1ea07a3c66e3f3d70304a8cd713`
and `a9f5b990cd9b5b6eb0b070d12989bb832adfeea80e6a78c665d22748de4cc57c`.
Python 3.13/3.14 receipt hashes are
`a66116c7deeda171fd553e0e9aba4546dfe2180d39616da4a5d52cbc3cfd8338`
and `0fc55347ec5e48871193751766775bf89d4c266354310bed1200bf2cbaf077c3`.

Required runtime replay coverage merged successfully over 109 production modules.
All 43 critical modules and the 29 owned changed executable lines measured 100%.
The scoped suite's overall **89.2599% line / 86.6836% branch** measurement does not
qualify the whole-package floors; full frozen-head/native qualification remains
required. The normal runtime positive child completed both warmed 5,000-record
rounds at **113.758007 ms**, below the unchanged 150-ms guard. The deliberate
blocking negative child failed at **204.496040 ms**; branch-covered functional
replay completed both rounds at 170.439075 ms, explicitly nonqualifying timing.
Normal viewer drain and all three final whole-app zero-owner/stream/watch receipts
passed. Workload, GC thresholds, warm cycles, deadlines and assertions stay intact.

These are working-source observations before final documentation, not native
qualification of a new frozen head. Original logs, XML, source inventories and
runtime evidence stay under ignored `artifacts/cancel50` and
`artifacts/refill50/pr176-revised-native`. Q03 stays open for the checked-in
combined 100-events/s and 2,000-lines/s generator, 10,000 retained lines,
sustained p95 below 100 ms, a 30-minute memory plateau and lifecycle qualification.
No release/version, public channel, workload or timing/coverage gate changes here.
