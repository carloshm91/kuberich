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
