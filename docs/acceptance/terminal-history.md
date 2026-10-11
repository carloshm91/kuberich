# Embedded terminal history: #123

The production Pyte emulator retains normal-screen scrolling in a bounded ring;
the Textual shell reviews an immutable capture while the real PTY keeps running.
This is terminal output, not a mocked log widget. See
[controls and limits](../container-shell.md#review-output-without-sending-shell-commands).

## Behavior evidence

Actual model cases cover overflow/drop reporting, immutable styled Unicode rows,
partial/alternate-screen isolation, resize displacement, bounded session-owned
cell caching, literal case-folded search, marks and raw/escaped copy bounds.
The deterministic history module measured 100% line and branch coverage in its
initial 13-case cohort; the complete production gate remains required for merge.

Pilot drives an actual child PTY in KubeRich's running application. It emits more
than the history limit, Unicode and an inert remote OSC52 request, then continues
output while review remains frozen. Search/navigation/paste are not delivered to
the child. Explicit copy redacts recognized credentials; resize, mouse selection,
the History/Live button, alternate editors, stale context and repeated session
cleanup retain their production ownership contracts. Screenshots are retained
under `artifacts/ui/terminal-history-100.svg`.

Real console/module and freshly installed wheel PTYs passed all three history
cases in **19.11 seconds** before the bounded cell-cache optimization. The child
independently requires that its only post-output input is `exit\r`; the host
transcript contains the operator's redacted clipboard payload. Originals remain
`artifacts/shell123/pty-v2-original.log` and `artifacts/terminal/*history*`.

The owned-kind verifier passed normal/configured/missing shells, Unicode history,
local search/copy/return, actual full-screen vi, resize, repeated returns, TLS/
context alias/impersonation and synthetic exec-auth helper RBAC cases. It created
only its owned cluster and verified deletion. These synthetic helper trials do
not certify a cloud provider. Original evidence is
`artifacts/shell123/owned-shell-v1.json` and `owned-shell-v1-original.log`.

```sh
uv run pytest -q --tb=short tests/unit/test_terminal_history.py tests/ui/test_terminal_history.py
uv run pytest -q --tb=short tests/quality/test_terminal_history_stress.py
uv run pytest -q --tb=short tests/terminal/test_container_shell.py -k history
uv run pytest -q --tb=short tests/packaging/test_distribution.py::test_installed_terminal_history_search_copy_and_return
uv run python -m scripts.verify_shell_kind --kind /path/to/kind --kubectl /path/to/kubectl
```

## Sustained output and qualification boundary

Separate fresh child processes measure traced Python allocation plateau and
uninstrumented mounted production-widget latency. They are distinct results:
allocation tracing does not establish latency, and Python allocation is not RSS.
Each geometry receives 6,000 rows, retains at most 1,000 plus one frozen capture,
and must plateau across equal later workloads before releasing captured storage.
The 100×30 mounted widget consumes 9,000 colored Unicode rows in actual bounded
PTY-sized chunks while review is active; its unchanged maximum heartbeat is
150 ms. Original receipts are `artifacts/terminal/history-{memory,latency}.json`.

The optimized local stress cohort passed **2 cases in 50.58 seconds**. The
100×30 retained/captured Python allocations plateaued at 3,097,564 bytes and
400×150 at 19,878,728 bytes; later equal rounds varied by 64 bytes in the maximum
geometry. Clearing returned to within 16 KiB of the filled live-screen baseline.
The independent uninstrumented mounted-widget maximum heartbeat was **97.386 ms**
and maximum feed **43.813 ms**, below the unchanged 150-ms heartbeat requirement.
This is measured local component evidence, not a supported-platform promise.

The first cleanup assertion assumed clearing history would halve all model
allocation. After cell sharing, the still-live 400×150 screen legitimately
accounted for more than half. Its original failed assertion is retained in
`artifacts/shell123/memory-v2-original.log`. The revised measurement independently
fills and measures that live screen before history, preserves the same history
plateau requirement, and requires cleanup to return within 128 KiB of the live
baseline. It does not reduce retained-row limits or suppress a growth failure.

Full supported platform CI, installed bytes/audits, independent coverage and
final exact-candidate qualification remain merge/release requirements. This
issue does not activate public channels, publish a release or claim broader
keyboard/mouse protocol compatibility (#124).
