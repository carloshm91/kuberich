# Plugin configuration acceptance

Scope: U03 #58, the actual offline configuration, trusted-location loading and
immutable invocation contract. U04 #59 owns interactive execution; no execution,
terminal restoration or native plugin parity is claimed from parser tests.

## Measured local checks

On Linux / CPython 3.12.12, the focused plugin/file/configuration/CLI cohort passed
256 tests in 9.35 seconds. Both new critical modules and the explicit file adapter
measured 100% lines and branches in that cohort. That focused measurement is not
whole-package coverage; complete hosted source/native checks remain required.
Ruff and strict application types passed before the cohort.

The final expanded cohort passed **257 tests in 8.45 seconds** after adding
unresolvable-home and invalid-captured-scope regressions. It covered all 233
lines/112 branches in the plugin domain, 49 lines/20 branches in its configuration
parser and 66 lines/36 branches in the explicit file adapter. These counts are
focused evidence, not the complete application's coverage.

An additional real descriptor observation rejected twenty owned YAML-named
directories on the original head and measured descriptors growing from 4 to 24.
`fdopen` could fail before entering its stream context. The corrected adapter
owns the original descriptor in `finally`, checks regular-file identity before
stream wrapping, and retains ownership even when `fdopen` itself fails. Both
regressions assert the actual descriptor is closed after every rejection.
The corrected cohort passed **259 cases in 8.06 seconds**, with 68/68 adapter
lines and 36/36 branches; both critical-module totals above remain 100%.
Original run 39095176945 was cancelled after this local finding; its completed
native checks belong to the older source and do not qualify the correction.

## Required responsiveness correction

The next head, `510d48c2719eaa8af19ea9e37c90b96be9012f9e`, passed all four
native jobs and the Linux/Python 3.14 and macOS baseline source jobs. Its required
Python 3.13 job `117583801039` failed the original aggregate runtime heartbeat:
152.010 ms against the unchanged 150-ms maximum during warm resource route four.
The original job recorded 5,356 passed / one failed / two skipped in 2,110.05 s.
Artifact `12124858771` ZIP SHA-256
`455c8ba4dc9168aeb293eac5e3c448ff4fd60ae63368ae5a7a22c93be596ecf4`
was independently verified and retained, including complete positive-child
heartbeat/source receipts. GC occupied 97.881 ms of that pause inside native CSS
reparse; total main-thread CPU was 149.939 ms. A successful different platform
does not qualify this failed head.

The production correction retains three exact variable snapshots, each with the
native 64-source parse cache, within the app-owned stylesheet. It preserves
source/content/scope/priority keys, transactional errors, independent copies and
the existing component ownership. Native-control tests prove revisiting an exact
snapshot avoids repeated parsing while rules and errors remain equivalent.
The cache remains bounded and is not shared globally. No budget, GC threshold,
dataset, warmup, required job or failure condition was relaxed.

Ten focused cache/component/color cases passed on Python 3.13.12 in 9.76 s;
the complete cache module measured 73/73 lines and 14/14 branches. The broader
Python 3.12.12 UI cohort passed 49 cases in 248.53 s, covering themes, persisted
navigation/views and aggregate-log controls. A working-source Python 3.13 runtime
parent passed in 64.25 s: the real positive child completed both full-history
rounds with a 77.769-ms maximum; the deliberate 200-ms negative callback was
rejected at 202.538 ms; the complete branch-covered replay passed its functional
assertions (155.905-ms instrumentation timing is explicitly nonqualifying).
Normal GC remained enabled at that interpreter's default (2000, 10, 10).
Fresh full hosted qualification must verify the final frozen correction.

## Preference relocation

An explicit migration validates known plugin schema and rebases file locations
and every inline working directory against the original preference location.
Actual files verify identical global/context effective catalogues and executable
directories after migration, retained source bytes, private destination permissions
and no destination write for invalid definitions. The expanded plugin/config/CLI
cohort passed 261 cases in 8.27 s: plugin configuration 69/69 lines and 28/28
branches, domain 233/233 and 112/112, file adapter 68/68 and 36/36. These remain
focused measurements rather than complete-package qualification.

The original focused run exposed a NUL substitution crossing the internal dollar
marker boundary. The correction validates substituted values before marker
restoration; the negative control now rejects it. An initial broader command
named a nonexistent test file and ran no tests; the measured command uses the
actual config-store/schema and CLI test files.

```sh
uv run pytest tests/unit/test_plugins.py tests/contract/test_plugin_files.py \
  tests/unit/test_config_store.py tests/unit/test_config_schema.py \
  tests/unit/test_cli.py tests/unit/test_cli_config.py \
  --cov=kuberich --cov-branch --cov-report=json:artifacts/plugins58-local.json
```

Behavior includes no implicit current-directory discovery or command execution,
context replacement of complete definitions, exact scope/shortcut conflicts,
literal hostile argument values, unknown/malformed/control-containing variables,
typed defaults/required/choice/finite-number validation and cancellation without
an executable request. Real files cover special files, final symlinks, UTF-8/YAML,
duplicate keys/names, file/directory/catalogue bounds, permission errors and
offline configuration checks preserving original bytes.

The hosted PR record supplies exact source pins, complete platform/native counts,
whole-package coverage and required-check results after completion. Public
0.1.0 artifacts, website deployments, tags and DNS are unchanged.
