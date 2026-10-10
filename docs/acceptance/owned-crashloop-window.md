# Owned CrashLoop enrollment window: Refs Q03 #50

Required PR run `38047239771` tested source `0dc9a98`. All four native
environments passed 4,349 behavioral cases. Linux/Python 3.13, Linux/Python
3.14 and macOS/Python 3.12 completed their full required jobs; independently
reviewed originals measured at least 99.0887% lines and 96.8750% branches,
with all 43 critical modules and 114 changed executable lines at 100%.
These results do not qualify the failed overall candidate.

Linux/Python 3.12 job `114199150115` failed later in the owned-kind aggregate
trial. Its container left CrashLoopBackOff between the precondition read and
initial enrollment. One line of the expected output arrived and the reader
ended normally, using the actual current `terminated` instance; the scenario
required `last-terminated` enrollment from a waiting instance. The original
failure, ZIP and complete log remain retained, including verified owned-cluster
deletion. No Actions retry or failed-head merge replaces them.

Original artifact `11668962191` has ZIP SHA-256
`0219e24223f5c2a8c5966e32d2833a65cdef647928b24478fadb1effa1df5921`.
Changed-coverage and final distribution steps did not run on this failed job;
their absence must not be filled with another environment's artifacts.

## Scenario correction

The owned verifier now observes the real container's termination followed by
CrashLoopBackOff with the same terminated container identity. It enrolls within
three monotonic seconds of observing that transition, after at least three
restarts, and rechecks the actual observation before requesting logs. Each mode
has its own eligible observation. The existing 120-second scenario deadline,
current/previous output assertions and exact initial `last-terminated` assertion
remain unchanged. Production log admission and replay semantics are unchanged.

The window uses receipt time because Kubernetes status propagation can lag
the container's `finishedAt`. A preliminary local predicate based on that server
timestamp timed out; its source, diagnostic and deletion log are retained under
ignored `artifacts/crash50/first-precondition` and are not passing evidence.

## Local evidence

```sh
uv run pytest -q tests/quality/test_aggregate_kind.py tests/quality/test_owned_kind.py tests/quality/test_ci_policy.py
uv run python -m scripts.verify_aggregate_logs_kind --kind /home/develop/projects/personal/kubetrol/artifacts/operations-46/tools/kind --evidence artifacts/crash50/transition-kind.json
```

The 62 fixture/ownership/CI cases passed in 18.02 seconds. The real disposable
Kubernetes 1.36.4 trial passed all 11 scenarios, with current and previous modes
enrolling the actual waiting container's last instance at restart counts three
and four. All membership/log tasks drained before client closure, the caller's
configuration stayed unchanged and the owned cluster was deleted with absence
verified. No maintainer context was used. Its receipt SHA-256 is
`ee061c46595469dff4f4bb9a3645081f52b92384fad78c686a642527e1398278`;
the tested verifier SHA-256 is
`53e54c5237336d816eb1963d06d29bed18b3671c18440d576df033d25ec6daad`.

Ruff and formatting passed for the repository; the complete required strict
type command passed all 133 source files. No production executable lines changed
in this scenario correction, so it adds no new production-coverage percentage.
New frozen-head native checks remain required. Q03 stays open for the combined
load's p95 target, 30-minute memory plateau and lifecycle qualification.
