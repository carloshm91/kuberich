# HTTP benchmark acceptance

Issue: [A04 #79](https://github.com/carloshm91/kuberich/issues/79).
Phase: v0.5.0. Source metadata and published packages remain 0.4.0.
This record distinguishes the measured early service checkpoint from the final
UI, installed, platform and protected-delivery evidence still required.

## Implemented contract

Explicit reviewed load uses a configured free Vegeta v12.13.0 executable and
one freshly verified backend Pod behind a dedicated loopback forward. Immutable
load/request limits, one-use service consent, read-only policy and current
client/UID/port checks precede effects. Existing forwards supply selection only.
Observed loss never authorizes another listener/backend or restarts load.

Requests stay in private files and receive no inherited proxy/provider/API
credentials. Owned process/parser/file work drains before the forward/client.
Normalized records omit request path/query/header/body values and raw tool
reports. Browser operations are local, read-only until explicit Delete, and
never create/prune folders. Save validates all records before age/count pruning.

## Early actual owned-cluster checkpoint

Clean signed development source `a69eb6a02c954f958f683197f2286c8cf1e7e413`,
tree `e3ac77560cbefdfc1337077c1275a018bd1ca964`, passes the actual service
spine. The executed command is shown with its installation-specific verified
tool paths parameterized as `KIND`, `KUBECTL` and `VEGETA`:

```sh
uv run python -m scripts.verify_benchmarks_kind \
  --kind "$KIND" --kubectl "$KUBECTL" --vegeta "$VEGETA" \
  --evidence artifacts/issue79/early-kind-03.json
```

The receipt observes two successful requests and two reported attempts, fresh
Service/Pod UID checks, one backend and zero dedicated-forward retries. It saves
and reopens the normalized record. Killing the actual forward during a second
run leaves three observed requests, then stops further load with target-lost
completion. All five task-owned child PIDs are reaped, private files are gone,
the caller's kubeconfig is unchanged and the disposable cluster is deleted.
This is real local traffic through kubectl, rather than a mocked load generator.

The early invocation first failed from a verifier import boundary, then from
valid real-API PodList items omitting TypeMeta in the strict service capture. Both original failures remain
failures; the receipt above binds the corrected source. Later source changes
need their own frozen evidence.

## Focused core and filesystem evidence

The following focused cohort passes 175 tests with a fresh physical temporary
base and separate full-package coverage report. The measured absolute artifact
directory is parameterized below as `CORE_EVIDENCE`:

```sh
COVERAGE_FILE="$CORE_EVIDENCE/.coverage" \
uv run pytest tests/unit/test_benchmarks.py tests/unit/test_benchmark_config.py \
  tests/unit/test_benchmark_results.py tests/contract/test_benchmark_store.py \
  tests/contract/test_benchmark_scan_limit.py -n 0 \
  --basetemp=/tmp/kuberich-79-core-04 -o addopts='' -q \
  --cov=kuberich --cov-branch \
  --cov-report="json:$CORE_EVIDENCE/coverage.json"
```

Measured deterministic modules reach 100% lines and branches: request contracts
94/94 lines and 28/28 branches; report/results 224/224 and 78/78; configuration
47/47 and 20/20. The effectful store reaches 107/107 lines and 22/24 branches
(91.67%). This focused report includes unimported production, but does not
satisfy the complete application gate. Scoped Ruff, formatting and strict types
pass. Target extraction separately reaches 102/102 lines and 52/52 branches
in the lead's 51-case focused cohort; final combined qualification is pending.

Adversarial coverage includes malformed/duplicate/nonfinite reports, exact
nanosecond interval arithmetic, independent error/status semantics, unavailable
single-sample rates, strict saved-field allowlists and missing producer versions.
Real filesystem tests cover private permissions, restart, confirmed deletion,
100-record/30-day pruning, unknown files, physical symlink/hardlink refusal,
changed entry identity, overflow, uncertain durability and repeated cancellation
while a worker drains. The browser does not prune expired records by opening.

## Optional development tool provenance

The explicit development helper provisions one selected Linux/macOS amd64/arm64
release archive. All four downloaded official archives match the maintainer's
reviewed checksum document and GitHub release metadata. SHA-256 is checked before
opening the archive; extraction admits exactly one regular `vegeta` member with
the reviewed byte count and binary digest. Existing/partial inputs are preserved,
never overwritten or repaired silently. Physical ancestors and assets reject
links, foreign ownership and unsafe permissions.

```sh
uv run pytest tests/quality/test_benchmark_tools.py -n 0 \
  --basetemp=/tmp/kuberich-79-core-05 -o addopts='' -q
```

All 38 cases pass in 5.86 seconds, including real process output/time limits.
Actual preparation and cache revalidation pass for all four platforms; only the
Linux amd64 binary executes locally, with a successful explicit version probe.
Foreign-platform binaries are not executed. Their prepared digests are:

| Platform | Binary SHA-256 |
| --- | --- |
| Linux amd64 | `c54d905541485153542dfcb850f9ab8ef801e7ab1a652d2cfc69cafdd4a5363f` |
| Linux arm64 | `2355df87f054ddbee28bee0b31c741836fa35619f329f664af29fa80910420c4` |
| macOS amd64 | `dae9dfe4b1b84745764d96248b7285c90200d9f92d6e9095b23b10286208a5c0` |
| macOS arm64 | `15d6cd01fc412e70a11243006de4e5fd68d505a13848ae3312d83d49b64fd087` |

The helper writes `prepared-provenance.json` with MIT/source links, source commit
`507c4f028fbad80168f3b734dab9530d3aabfefa`, archive/binary hashes, sizes and
`host_executed: false`. Release signatures are **not verified**. The checksum
document SHA-256 is
`384239c939594c6a4e3b1da4b336728a0d70ed8e77636af92984cdf036a816e7`.
An explicit verifier authenticates current-host binary bytes before a separate
5-second/16-KiB version probe. Production startup, installation and browser paths
never invoke this development provisioner.

## UI and process diagnostics

The development UI cohort passes 51 focused cases, including native Service
entry, explicit backend choice, private review, edit revocation, read-only
refusal, selected-forward identity, settings reload and client retirement.
Browser tests cover offline reopening, physical records, confirmed deletion,
filtering, stable selection, small terminals and held-worker drainage. Two real
framework ownership defects were found and fixed: generic Escape dismissal
returned before drainage, and browser fields collided with Textual's shutdown
state/task fields. Original failures remain retained.

Actual pinned-tool terminal diagnostics exercise completion, Cancel, Escape,
repeated Ctrl-C and repeated SIGTERM, with no later HTTP requests after observed
cleanup, exact terminal restoration and a separate offline result-browser restart.
A missing optional tool produces no forward and no load. `--benchmark-directory`
keeps every fixture's local state separate on Linux and macOS. These diagnostics
on the evolving source do not qualify an unchanged final candidate.

The actual HTTP contracts separately exercise success, redirects, 4xx/5xx,
timeouts, truncated bodies, worker bounds and cancellation. Their server counts,
private files and recorded child PIDs are checked. Requested pacing and observed
catch-up intervals remain distinct; no rolling traffic ceiling is claimed.

## Final qualification contract and limits

Before merge, the linked issue/PR must retain the unchanged signed source's
focused source/installed/native/owned-cluster receipts and ordinary hosted
matrix. Full production line/branch, changed-line and critical-module gates and
all required source/native/platform/repository/DCO checks remain mandatory.
The final receipts identify their actual checkout commit and input hashes;
earlier development evidence is never relabeled as final qualification.

The native benchmark cohort uses the frozen application, an authenticated
Vegeta binary and a compiled owned TCP bridge with a synthetic API. It shares
Linux host network/PID identity for private-file ownership and recorded-PID
checks; this exposes host `/proc` and does not qualify filesystem isolation or
outside-interpreter inaccessibility. Generic native isolation controls remain a
separate cohort. The real owned-kind verifier separately exercises kubectl/API
transport; neither cohort certifies a cloud provider.
No tags, package publication, website publication, hosting or DNS changes occur.

The supported test is HTTP/1.1 through one backend. Desired pacing can catch up;
the tool's measured rate uses first-to-last-start time, not wall-clock duration.
Single-sample rates remain unavailable. Percentiles include failures and are
estimates. Raw distinct error messages are discarded instead of counted as
requests. Retaining zero response bytes still drains the wire: received bytes,
response headers and external RSS are not capped by `max-body=0`.

kubectl's final remote selection is name-based, and forward loss notification
cannot eliminate the listener-reuse race, including scheduled/in-flight connects
during observed-loss cancellation and drainage. Stop reacts to observed loss;
it never treats an old port as ownership proof. Real provider/network/runtime
certification remains the maintainer's later opt-in work, separate from this issue.


## Retained final-verifier cancellation-window failure

The first frozen final verifier on `a1aeb3c4adc2676ecf422b3565cbbe3d660c3d0a`
fails an overstrong assertion that an immediate replacement listener receives
zero connections before generator drainage completes. The original receipt
`artifacts/issue79/frozen-kind-01.json` records all 331 inputs unchanged and
owned-cluster/private-directory deletion. It records only that the replacement
count was nonzero; the exact count and child-PID assertions were not retained
before that failure, so they cannot be claimed for this attempt.

The corrected verifier separates accepted connections/requests during the
cancellation window from traffic after confirmed process/handler drainage.
It retains those counts and cleanup facts incrementally, rejects a new ready
forward or a consumed review, and fails any deliberately injected post-drain
traffic. Product code, load limits, cleanup deadlines and source guards are
unchanged. The original failed attempt remains failed.

## Retained local native environment and readiness failures

The first workstation native build correctly fails the unchanged GLIBC 2.35
floor: this host's `libstdc++.so.6` requires GLIBC 2.38. The original
`artifacts/issue79/native-build-01.log` and build environment remain retained.
A pinned Ubuntu 22.04 builder with read-only source, isolated writable output,
the same full interpreter and lock passes that original floor. Its archive and
input hashes are retained separately; the failed workstation build is not
qualified or relabeled.

The first normal runtime verifier of that archive fails before the benchmark
cohort: it sends `G` immediately after changing terminal size, before observing
the compact container layout, and the required `worker` field remains outside
the viewport. The original `native-runtime-02.log` and
`terminal/failure-1794347073097713008` receipt/ANSI retain the failure and terminal
cleanup. Controlled public Pilot cases reproduce the old-layout ordering and
prove that observing the compact 40-column/12-line frame before one `G` reveals
the actual worker field. A source PTY confirms the same protocol. The verifier
adds only that frame-readiness guard; its single command, original field
assertion and deadline remain unchanged. No production table code changes.

Review also identifies the Linux benchmark wrapper's missing working directory
before its cohort runs. It now selects its fixed owned fixture directory with
`--workdir`; command and filesystem tests enforce that private journal boundary.
Final rebuilt native/runtime receipts remain separate from these original
failed attempts.

The next native runtime attempt passes that baseline but stops before benchmark
load at the optional-tool physical-directory guard: the generic tools folder
inherited a group-writable host umask. The original `native-runtime-03.log` is
retained. The verifier now creates its owned tools directory with mode 0700;
the benchmark adapter independently refuses group-writable or linked tool
folders before copy/compile. Authentication and filesystem guards are preserved.
