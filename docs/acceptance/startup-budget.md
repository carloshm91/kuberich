# Startup budget acceptance

The startup boundary keeps offline commands independent of the terminal framework
and Kubernetes SDK. It does not change configured validation or claim provider,
macOS, native-archive or release qualification from Linux source tests.

## Behavioral evidence

An earlier functional-only source snapshot passes **1604 tests**, with the one
performance/runtime-control case explicitly deselected for its later isolated
qualification. It includes existing CLI, migration, configuration, navigation,
provider HTTP, proxy/TLS, update, mutation and modal UI controls. A separate
70-case startup smoke run includes all 13 real-terminal routes after HTTP/modal
import deferral. Those PTYs exercise default/context/retry/login/initial-view
launches, a real harmless credential helper, opt-in release reads against an
owned HTTP server, quit, cancellation and context replacement before readiness.
An audit hook rejects pre-refresh SDK imports, helper invocation or network work.
Fresh children separately reject eager HTTP/SDK and unused modal imports.

Coverage includes every production module, including modules not imported by the
focused tests. This subset is not whole-package qualification. Against source
base `459a2fa`, that snapshot's changed production coverage is **194/205 lines
(94.6341%)**. The critical CLI retains **160/160 lines and 48/48 branches**; navigation retains
**110/110 lines and 48/48 branches**; session ownership retains **68/68 lines and
14/14 branches**. The offline section validator retains **35/35 lines and 16/16
branches**. Eleven changed, type-only project/SDK/HTTP imports remain uncovered
and stay in the denominator. No coverage exclusion or threshold has changed.
Ruff, formatting and strict typing over 161 source/tool files pass.

A subsequent narrow editor/regex/import correction passes **285 tests**,
including all then-current 14 startup PTYs, with its own **14/14 changed
production lines** covered. That limited cohort covers only **156/219 (71.2329%)**
of the whole snapshot's changed production lines and therefore does not satisfy
the whole-change gate. Historical coverage from different source snapshots is
not combined to claim a pass.

The inactive-table prototype retains the selected real table, all original eager
column-model setup, input controls and validation. Four public Textual controls
verify registration/configure/focus, stable row and cursor identity, duplicate
registration and native completion on exit. A deliberately blocked third-party
Mount handler exposed a pinned framework limit: exit queues teardown behind that
handler rather than cancelling it. Its original failure is retained. The
prototype therefore owns waits for the concrete, nonblocking production tables;
it does not promise cancellation of arbitrary third-party Mount handlers.
Eight owned-scheduler controls pass, including completion cancellation, readiness
cancellation, early stop, errors and unchanged selected-table geometry. Fourteen
new initial-route PTYs verify actual mounted tables, columns and viewport bounds
before any SDK/helper/network work. These are functional controls, not new timing
qualification.

The inactive-DOM candidate's affected functional cohort passes **1901 tests in 313.73 seconds**
using three workers with performance/runtime-control markers explicitly excluded.
All 540 source, test, tool and configuration inputs remain byte-identical during
that run. A coherent diff, including the new registration owner, covers
**319/332 changed production lines (96.0843%)**. The critical CLI, navigation and
session modules retain the exact 100% line/branch counts recorded above; the
section validator and pure theme catalog also remain at 100%. The registration
owner covers **80/82 lines and 26/28 branches**. Eleven type-only lines and two
defensive owner guards remain in the denominator. No exclusions or thresholds
changed. Ruff checks and formatting cover 685 files; strict typing passes for
162 production/tool sources.

This affected cohort measures **89.5567% of all production lines and 76.9330% of
all production branches**, including unimported modules. It is not a passing
whole-package gate. The full integrated suite, its runtime controls, platform
matrix and fresh canonical startup reference remain required. Passing changed
coverage or these functional controls does not complete the startup budget.

An earlier attempt to form the modal functional cohort accidentally included a
runtime-control marker embedded in a UI file. The owner was interrupted (exit 2),
its process group/session was confirmed terminal, and its partial log/receipts
remain retained. Concurrent targeted work makes that run invalid as timing
evidence. It is not a passing cohort. The corrected command explicitly selects
`-m 'not performance and not runtime_control'`; the original runtime control is
still required separately before complete qualification.

## Reference measurements

The pristine source baseline used three ordinary fresh children and one
`-X importtime` child for each required offline path. After the initial cold
bytecode pass, ordinary commands took **1089.40–1129.32 ms**, with approximately
92.17–92.30 MiB peak RSS. The first cold `--version` took 4045.12 ms. Import
profiles recorded 1006 Textual/SDK module entries and 964.8–994.8 ms aggregate
import self time. These are retained failures, not a baseline qualification.

The first new canonical run also failed and remains retained: `--version`
completed cleanly in **197.856859 ms**, with **27,713,536 bytes** peak RSS. The
150 ms wall-time limit rejected that first sample; no later cases, first-paint
sample or negative control ran. The correction subsequently deferred unused
navigation/command imports and installed-metadata lookup without replacing the
canonical `importlib.metadata.version` implementation. New reference results
must establish the unchanged budget on those corrected inputs.

The second canonical run passed five `--version` observations at
**99.759–102.737 ms** and five `--help` observations at **75.471–77.038 ms**,
with **21,757,952 bytes** peak RSS each. Their aggregate import self times were
**82.903 ms** and **57.826 ms**. It then rejected the first `info` sample at
**155.273 ms** / **26,017,792 bytes**. The retained diagnostic profile identified
27.492 ms of navigation imports with no extension configured. No config-check,
first-paint or negative-control qualification is inferred from this failed run.

The subsequent correction avoids importing a section parser only when that
extension key is absent. Explicit empty, null, false and malformed values still
run the original validators; theme validation is unconditional. Fresh child
controls retain configured imports, mixed-section error ordering, per-context
plugin files and key conflicts.

The third canonical run passed all 20 offline wall/RSS observations and all four
import profiles. On Linux x86_64 / CPython 3.12.12:

| Path | Five ordinary wall-time samples | Peak RSS | Aggregate import self time |
| --- | --- | --- | --- |
| `--version` | 99.431–103.740 ms | 21,757,952 bytes | 79.406 ms |
| `--help` | 74.409–77.147 ms | 21,757,952 bytes | 58.365 ms |
| `info` | 138.284–145.633 ms | 21,757,952 bytes | 114.735 ms |
| `config check` | 112.305–115.177 ms | 21,757,952 bytes | 93.616 ms |

It then rejected the first actual PTY frame at **917.499158 ms** against the
unchanged 600 ms limit. The actual resources table and viewport were visible;
SDK/helper/network work remained deferred, client cleanup and alternate-screen
restoration completed. Neither negative control ran after that first failure.
Further UI startup work and a fresh complete reference remain required; these
passing offline samples do not qualify first paint or complete this issue.

The fourth reference passed all 20 offline observations again, then rejected
actual first paint at **709.528229 ms**. Narrow HTTP/modal import deferral improved
the previous result, but the unchanged 600 ms limit still failed. The visible
header arrived at 669.908869 ms; it does not replace the later actual refresh.

The fifth reference, after editor/regex/action-service import deferral, again
passed all 20 offline observations and four import profiles:

| Path | Five ordinary wall-time samples | Peak RSS | Aggregate import self time |
| --- | --- | --- | --- |
| `--version` | 100.136–100.719 ms | 21,757,952 bytes | 79.983 ms |
| `--help` | 75.374–78.908 ms | 21,757,952 bytes | 58.084 ms |
| `info` | 139.827–141.408 ms | 21,757,952 bytes | 114.028 ms |
| `config check` | 112.649–113.411 ms | 21,757,952 bytes | 96.165 ms |

It rejected actual first paint at **681.614565 ms**; the visible header arrived
at 642.880921 ms. Original launch-relative timestamps record imports finished at
471.858576 ms, constructor entry/return at 479.974185/492.408194 ms, and mount
entry/return at 582.612714/587.037384 ms. The actual refresh remains the measured
endpoint. Neither negative control ran after this first failure. No later
startup pass is inferred for the inactive-DOM prototype without a fresh canonical
reference, and no threshold or clock subtraction has changed.

The sixth canonical reference, on signed candidate `1c84901`, stopped before
measuring the new DOM behavior. Five version samples completed in
101.348–109.516 ms and five help samples in 78.974–82.438 ms. The first two info
samples took 142.898 and 146.705 ms; the third failed at **153.155201 ms** against
the unchanged 150 ms limit. Peak RSS remained 21,757,952 bytes. Its automatic
diagnostic import profile is retained, but cannot replace that failed sample.
No config-check, first-paint or negative-control result is inferred.

The following correction skips unused default connection construction only for
inspection commands, after connection flags have already been rejected. Terminal
connection validation stays before configuration I/O in its original position.
The bootstrap's annotation-only `Logger` import is also deferred under existing
future annotations. All seven fresh offline routes now reject logging,
connection-request, override and target imports as well as Textual/SDK imports.
The complete focused offline/configuration/migration cohort passes **589 tests**,
retaining **161/161 CLI lines and 50/50 branches**. Precise logger annotations
remain; six type-only bootstrap lines stay uncovered in the denominator. Strict
typing passes over 162 sources. A fresh coordinated reference is still required.

The seventh canonical reference passed all 20 offline observations again:

| Path | Five ordinary wall-time samples | Peak RSS | Aggregate import self time |
| --- | --- | --- | --- |
| `--version` | 97.585–98.734 ms | 21,757,952 bytes | 78.443 ms |
| `--help` | 71.429–73.749 ms | 21,757,952 bytes | 54.631 ms |
| `info` | 128.949–137.160 ms | 21,757,952 bytes | 105.067 ms |
| `config check` | 99.665–100.372 ms | 21,757,952 bytes | 82.462 ms |

It then rejected actual first paint at **687.126287 ms**, with the visible header
at 637.405989 ms. The real six-column resources table was mounted and inside the
viewport; shutdown completed and SDK/helper/network guards stayed clear.
Import/constructor/mount timestamps remained near the preceding measurements.
Inactive-DOM deferral provided no measured improvement over 681.614565 ms, so its
registration owner, prototype-only tests and App routing hooks were removed.
The original eager composition and model setup are restored. The failed
prototype and all earlier raw evidence remain retained; it is not a startup pass.

A bounded, isolated import diagnostic on that source identifies the otherwise
unused read-only editor/document graph beneath scroll navigation. The unchanged
editor subclass moves to a dedicated module, with canonical inspection imports
and the existing lazy public compatibility export. No further timing result is
inferred from that change without a new canonical reference.

Rollback exposed a real late-quit race: a queued refresh could release connection
preparation after `App.exit`, before asynchronous shutdown. The original cohort
retains its **173 passes and 10 failures**. A minimal App-owned stopped flag now
rejects that late release inside the existing owned connection boundary. The
corrected inspection/navigation/App/startup cohort passes **183 tests**, including
all 30 actual startup PTYs. Three additional real editor/scroll navigation
controls pass, preserving Vim edges, half pages, literal read-only content and
canonical compatibility imports. The moved editor class has **12/12 lines**
covered; lightweight scrolling has **28/29 lines**, with its type-only export in
the denominator. Strict typing passes over 162 sources. Whole current-source
coverage and a new coordinated timing reference remain required.

The next import correction separates the three plugin modal classes from their
original controller module. The loader injection port, hotkeys, manager and
captured-source body remain unchanged; source comparisons verify the capture
body and modal class blocks byte-for-byte. Original named imports remain literal
aliases to the canonical screen classes. Forwarding dialogs import in their
requesting actions.

Two original cohorts retain **212 passes / one failure** and **217 passes / one
failure**. Each failure came from a newly proposed assumption that default TUI
imports could exclude Textual's selector widget. An import-origin trace instead
shows that pinned `textual.app` loads it through `textual.command` and
`textual.types`. That additional test specification was corrected to reject
unused project plugin/forwarding modules. Original offline Textual/SDK, HTTP and
first-paint gates remain unchanged; no upstream import workaround is introduced.
Five corrected fresh-import/worker/alias controls pass on the same production
source. All 217 actual plugin, forwarding and startup controls already pass.
The moved screens cover **202/211 lines and 38/42 branches** in this subset;
strict typing passes over 163 sources. An independent Argon review confirms the
actual loader/manager/capture and screenshot identities; its claim that Select
was unique to plugin screens was contradicted by the retained runtime trace.
No selector-specific startup saving or passing timing result is claimed.

## Reproduction and limits

From a development checkout with its locked environment:

```console
uv sync --locked --group dev
uv run python -m scripts.check_startup --output artifacts/startup/qualification
```

The output directory must be new. The canonical command runs five observations
per offline path and five actual first frames; CI uses that same command without
skip or budget options. All four paths must finish below **150 ms** and
**40,000,000 bytes**. Every import profile must avoid Textual/SDK and keep both
aggregate import self time and maximum cumulative time below **150,000 µs**.
Actual first paint, including PTY delivery, must finish below **600 ms** before
connection work. A deliberate 700 ms mount and an explicit Textual import must
both be rejected. No failed observation is replaced by an unchanged retry.

The qualifier verifies the editable source identity, freezes production/tool/lock
inputs, records raw stdout/stderr, import profiles and ANSI transcripts, and uses
owned subprocess groups with deadlines and cooperative signal cancellation.
Linux peak RSS is converted from KiB; Darwin's byte value stays unchanged. The
required source matrix retains the observations even when a gate fails. A fresh
failed offline sample also records a diagnostic import profile without promoting
that profile or a later sample into a pass.

The real-terminal tests use explicit synthetic loopback fixtures and isolated
preferences. Source PTYs are not installed-wheel/native-archive startup evidence.
Full platform, runtime, coverage, package and release gates remain required on
the integrated source before publication.
