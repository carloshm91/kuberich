# Aggregate container/workload logs: S06 #54

This issue implements the existing viewer controls over independently admitted
regular/init/ephemeral container sources and controller-owned workload Pods.
The [user guide](../log-viewer.md#all-container-and-workload-logs-s06-54) specifies
exact controls, membership, admission, clock, JSON, retention and replay limits.
Pod Enter still opens containers and only selected-container logs. Generic
resources retain their read-only inspection routes. Embedded-shell terminal history
qualification remains open in #123; this issue does not complete it.

## Local preparation receipts

Owned HTTP fixtures exercise actual per-client requests, response framing and
watch delivery. Pilot uses real public controls at 40×12 and 100×30. The corrected
JSON scalar domain cohort passed 84 cases in 4.52 seconds with:

```sh
uv run pytest tests/unit/test_aggregate_logs.py tests/unit/test_logs.py -q --cov=kuberich --cov-branch --cov-report=json:artifacts/aggregated-logs-54/domain-coverage.json --cov-report=
```

At that point aggregate decisions measured 169/169 lines and 48/48 branches,
JSON 38/38 and 12/12, and framing 124/124 and 46/46. Startup decisions subsequently
extended aggregate coverage to 195/195 and 62/62. These are independent critical
domain receipts, not whole-production or final-head qualification.

The initial HTTP/Pilot cohort passed 12 cases in 14.45 seconds. Subsequent owned
intermediate-controller and 64-KiB tiny-line/slow-source cases passed three cases
in 2.89 seconds; the tiny-line case also passed with full package branch
instrumentation in 5.71 seconds. The completion deadline permits instrumentation
and host variation; the separately asserted heartbeat gap remains below 150 ms.
New correction cases passed four cases in 6.01 seconds: 70 source-UID/read cycles
with 64 removed-status and retained-source bounds, workload picker UID churn/
expired selection/Space admission, Pending/init/ephemeral start evidence with
pre-open 400 recovery, and detached export drain before context-client cleanup.

Source and fresh wheel console/module native aggregate trials passed three cases
in 18.99 seconds before the final startup/lifecycle changes. They run outside
the source tree for installed cases, resize 100×30→220×30→40×12→100×30, navigate
actual viewer/picker controls, assert private values absent, exit zero and restore
terminal modes. Stable receipts under `artifacts/terminal` are:

- `aggregate-logs.json` and transcript;
- `installed-aggregate-logs-console.json` and transcript;
- `installed-aggregate-logs-module.json` and transcript.

The final pure suite passed 1,996 cases in 41.13 seconds with an independent
owned coverage file. New aggregate decisions measured 207/207 lines and 68/68
branches; JSON measured 38/38 and 12/12, and shared framing 124/124 and 46/46.
The full source inventory is 109 Python files with 43 declared critical modules.
The unit-only suite does not completely cover the existing Pod/session domains;
their complete coverage remains part of mandatory full-suite qualification.

The final-focused command passed 200 cases in 168.18 seconds:

```sh
env COVERAGE_FILE=artifacts/aggregated-logs-54/final-focused.coverage uv run pytest -q tests/unit/test_aggregate_logs.py tests/unit/test_logs.py tests/contract/test_aggregate_logs.py tests/contract/test_logs.py tests/ui/test_aggregate_logs.py tests/ui/test_logs.py tests/terminal/test_aggregate_logs.py tests/packaging/test_distribution.py::test_installed_aggregate_logs_and_terminal_restore tests/quality/test_ci_policy.py --tb=short --cov=kuberich --cov-branch --cov-report=json:artifacts/aggregated-logs-54/final-focused-coverage.json --cov-report= --junitxml=artifacts/aggregated-logs-54/final-focused.xml
```

It includes source and fresh-installed aggregate PTYs, old single-log controls,
full 5,000-line rendering/formatting/export heartbeat, protected file refusal,
clipboard bound and real Pending/CrashLoop current/Previous reads. Ruff/format
and both local site digest/link checks pass; the actual browser checked all
49 desktop/mobile pages with zero violations/errors/external requests. Mandatory
frozen four-native/eight-check PR qualification remains separate.

The subsequent footer/lifecycle and malformed-array correction cohort passed
125 cases in 72.61 seconds, including all three real source/fresh-installed PTYs.
The final object/array-boundary cohort passed 120 cases in 4.51 seconds:

```sh
env COVERAGE_FILE=artifacts/aggregated-logs-54/json-boundary.coverage uv run pytest tests/unit/test_aggregate_logs.py tests/unit/test_logs.py -q --tb=short --cov=kuberich --cov-branch --cov-report=json:artifacts/aggregated-logs-54/json-boundary-coverage.json --cov-report= --junitxml=artifacts/aggregated-logs-54/json-boundary.xml
```

It measures aggregate decisions 207/207 lines and 68/68 branches, JSON 49/49
and 18/18, and shared framing 124/124 and 46/46. These local correction receipts
supersede the earlier domain shape; full frozen native qualification still follows.

An enlarged diagnostic cohort ended 2,188 passing cases and one failure in
501.17 seconds. Its empty-source UI command preceded usable discovery, now
corrected. Concurrent coverage runs accidentally shared `.coverage`, invalidating
that run's report; it is retained without any passing coverage claim. All later
runs use separate owned `COVERAGE_FILE` paths. Another focused attempt measured
a 151.99-ms heartbeat gap under instrumentation/load; framing now runs in the
existing owned parser, retaining the 150-ms assertion rather than loosening it.
Passive source-picker refresh also erased an admission error; the error now
remains until the next choice. No diagnostic substitutes for frozen qualification.

## Actual disposable Kubernetes receipt

```sh
uv run python -m scripts.verify_aggregate_logs_kind --kind /PATH/TO/OWNED/kind
```

The corrected verifier passed eleven checks on owned cluster
`kuberich-test-7e49fc8ba0e8419b98217ecafc1e98b7`, then deleted it and verified absence.
It uses kind v0.33.0, pinned Kubernetes 1.36.4 node and pinned Alpine container
images through the shared owned-cluster wrapper. Caller kubeconfig bytes remained
unchanged. Actual controller membership excludes a matching-label Pod with another
controller; Deployment→ReplicaSet→Pod and CronJob→Job→Pod are verified against
captured actual UIDs. Regular/init/multiple-Pod logs, decoded JSON/plain output,
live ephemeral enrollment, Pod deletion/replacement, actual Pilot controls and
all reader/watch cleanup before SDK close passed.

The CronJob child uses an eight-second init sleep. The verifier observes its app
source **starting** before app output, then receives app logs without any
`choose`/reopen invocation. This proves enrollment rather than relying on a Pod
that had already started before LIST. `artifacts/cluster/aggregate-logs-kind.json`
records the eleven check names, limits, pins, unique cluster and deletion status;
`aggregate-logs-kind.svg` retains the actual API/Pilot view.
An actual Pod was observed waiting in CrashLoopBackOff with a valid terminated
container ID before opening aggregate readers. Current and Previous both
delivered its first snapshot without manual selection/reopen, then reached EOF.
The first delivered source token is asserted `last-terminated`, so a racing
restart into Running cannot qualify the initial-waiting case. This remains a
local draft receipt until the frozen source runs the mandatory verifier again.

## Discovered failures and corrections

The first kind draft reached CronJob membership but timed out after 120 seconds
waiting for output: admission requested logs before container start, got 400 and
never reconsidered start evidence. Its cluster
`kuberich-test-89c5c0936b80486c992befd7f99ea694` was deleted. A second diagnostic
rehearsal waited for Running and manually reopened, passing nine checks on
`kuberich-test-67eaf5ec554d44cfb041044a9d794be9` and deleting it; that workaround
does not qualify startup. The ten-check startup rehearsal on
`kuberich-test-29c01bc570c540eba64677f4917ff414` replaced that workaround and
deleted its owned cluster; the eleven-check CrashLoop receipt above extends it.

Review reproduced JSON/control expansion exceeding the old line presentation
bound, ordinary bracket logs being withheld, valid object shape lost by pre-parse
redaction, and escaped credentials in top-level JSON strings. Actual decoder→
aggregate/body/export regressions now cover bounded visible truncation, useful
fields and typed scalar/decoded-key redaction without retaining raw secrets.
Malformed first object/array tokens followed by encoded credential keys also
reproduced a plain-text fallback leak; one explicit candidate rule now withholds
those structures while preserving ordinary completed bracket prefixes followed
by prose and keeping whole arrays typed.
Source picker state/column widths and selected identity were corrected after
native/Pilot failures. Selection pruning keeps explicit empty admission when a
Pod disappears, preventing automatic replacement-UID admission.

A public Escape/save/context-change probe reproduced captured SDK cleanup while
a dismissed viewer still drained export work. A bounded ownership registry now
retains that viewer until every task finishes, and before-close drains it even
when absent from the visible screen stack. The corrected behavioral regression
passes. Earlier failed/partial runs are diagnostic, never passing qualification.

An independent context-change probe showed already-drained readers with a stale
footer still reporting reception enabled. Closing/stale presentation now says
reception stopped, reports zero readers and clears draining feedback after
cleanup. The first correction attempted a DOM query during detached unmount,
failing eleven cases in 95.57 seconds; it now updates only the retained mounted
status reference during close. The subsequent 125-case correction cohort passed.

## Qualification limits

The source remains a local implementation candidate until its signed frozen PR
passes all required native/gates and independent review. No provider certification,
user-cluster trial, package/version/tag or website publication occurs here.
Memory bounds apply to application histories/source metadata; transport/socket,
layout and runtime allocation are separate. No overall RSS, synchronized-clock,
maximum-load or secret-recognition guarantee is claimed. Q03 and Q05 retain
sustained performance and optional real-provider certification.
