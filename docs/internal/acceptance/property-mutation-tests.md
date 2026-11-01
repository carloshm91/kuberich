# Property and mutation testing

Recorded on 2026-11-01 for Q16 #217, against source base
`9e6ff5d451d52cdff4b1342b4bbdc40154330955`. This is scoped test-strength evidence,
not a whole-package mutation score or a new release gate.

## Scope and commands

Twenty-six Hypothesis properties exercise eight families through public APIs:

| Family | Independent oracle |
| --- | --- |
| Quantities | Decimal byte/exponent values, monotonicity, valid 64/invalid 65 characters, exponent ±30/±31 |
| Selectors | Set membership/complement, missing-label semantics and the field allowlist |
| Kubeconfig catalog | Whole-entry first-file precedence, provenance, defensive copies, source bytes/permissions and duplicate-key rejection |
| Redaction | Seeded credential removal, inert controls and no secret/control reappearance on a later pass |
| Aliases | Literal argument preservation, finite chains, cycle and preset-argument refusal |
| Keyboard maps | Unique effective owner bindings, reserved keys and log/text profile isolation |
| Terminal history | An independent retained-tail/cursor/viewport/inclusive-copy model |
| Log JSON | Decoded-key redaction, public fields, timestamp preservation, truncation/depth/expansion boundaries |

Each property uses up to 100 reproducible examples with shrinking and explicit
boundary examples. No health checks are suppressed. Per-example catalog files
are fresh mode-0600 children of the test-owned root; no ambient credentials or
cluster are used. The properties remain in the existing unit/fast/platform test
selection. Hypothesis is a locked development dependency.

```sh
uv sync --locked --group dev
uv run pytest tests/unit/property
uv sync --locked --group dev --group mutation
uv run --group mutation mutmut run --max-children 2
uv run --group mutation mutmut export-cicd-stats
uv run python scripts/report_mutations.py mutants/mutmut-cicd-stats.json \
  artifacts/mutations/report.json --metadata mutants
```

The separate optional mutation group pins mutmut 3.8.1. The weekly/manual Ubuntu
24.04 / Python 3.12 workflow owns a private temporary directory, limits workers
to two, bounds the campaign to 30 minutes inside a 45-minute job, and retains
raw logs, outcomes, generated sources, exit metadata and the strict report even
on failure. Its unchanged-test baseline and forced-failure control must work.

The eight explicitly selected critical modules are `domain/registry.py`,
`domain/selectors.py`, `config/catalog.py`, `diagnostics/redaction.py`,
`domain/aliases.py`, `domain/keyboard.py`, `domain/terminal_history.py` and
`domain/log_json.py`. No coverage filtering, type-check mutation filtering,
mutation-suppression pragmas or survivor exclusions are configured. Other
critical modules are outside this initial scheduled scope. Mutmut 3+ mutates
function bodies; top-level constant/regex declarations are a documented tool
[limitation](https://mutmut.readthedocs.io/en/latest/).

## Actual campaign and justified corrections

The first complete campaign assessed **1,943 mutants** in **642.79 seconds**:
1,647 normal pytest-exit-1 kills, 294 survivors and two bounded nontermination
timeouts. Its strict score was **84.765826%**, with `target_met=false`.
All source/test/lock inputs remained frozen. Original raw metadata and generated
sources remain archived under `artifacts/properties217/mutation01-cache`.

An independent Argon review consumed the actual property/source packet, verified
by a unique nonce and exact assertion quote. Two new-oracle corrections followed:

- Quote generated duplicate YAML keys and prove the single-key form parses
  first. A boolean/null key must not pass the test merely by failing key typing.
- Do not impose universal sanitizer idempotence. Escaping a whitespace control
  can permit additional safe redaction on a later pass; the actual invariant is
  that seeded credentials and raw controls never reappear.

Only 76 mutants in the affected catalog loader/mapping/parser and sanitizer
functions were retested, with fresh test-call associations, in 114.30 seconds.
The explicit credential/control case killed the sanitizer-default mutant that
enabled newlines by default. All unrelated outcomes remained unchanged.

Survivor inspection then exposed real missing quantity boundary assertions.
After verifying the unchanged function against the corrected mathematical
properties, only its 66 mutants were retested in 26.71 seconds. Valid-64 and
exponent ±30/±31 cases killed three boundary mutants. No production code changed.
Neither diagnosed nontermination function was rerun.

The final cumulative result is **1,651/1,943 actual assertion kills
(84.97169325784868%)**, **290 survivors** and **two timeouts**. No mutant is
unassessed, skipped, missing tests, suspicious, interrupted or killed by a
pytest internal error. The 85% target is **unmet**; rounding does not change it.
The final focused cohort passed **424 tests in 11.04 seconds**, including all
properties, score/error controls and the existing selected unit scenarios.
Whole-tree Ruff/format checks and strict typing of 157 application/tool files pass.
Plan validation passes after adding these actual evidence files. An initial
validation correctly rejected its link before the file existed; that original
failure was not treated as a pass. No platform/full-package run is inferred.

## Honest outcomes and survivor review

The strict report cross-checks every aggregate against the retained pinned-tool
exit metadata. Pytest exit 3 is an internal error, not an assertion kill. Timeouts
remain in the denominator and never count as killed. A campaign can finish with
diagnosed mutant timeouts while `clean_assertion_outcomes` remains false.
Unknown, unattempted, baseline or tool errors fail reporting. A completed result
below the advisory target reports a warning, not a new PR/release failure.

The two original timeout diffs are concrete:

- `aliases.x_expand_alias__mutmut_28` replaces `seen.add(name)` with
  `seen.add(None)`, making a generated alias cycle fail to terminate.
- `catalog.x_regular_bytes__mutmut_6` replaces the `O_NONBLOCK` flag union with
  an intersection, blocking the existing owned FIFO-refusal test at `os.open`.

Every final survivor is listed exactly once in the
[survivor inventory](property-mutation-survivors.json), checked against all raw
metadata. Argon reviewed the actual diff for each original survivor; final IDs
exclude only the four subsequently killed mutants. Source review corrected
context-dependent recommendations and identified three additional equivalent
selector defaults under the existing presence guards.

| Triage group | Final survivors | Disposition |
| --- | ---: | --- |
| Boundary/data/default behavior gaps | 103 | Future stronger public-behavior assertions; prioritize bounded I/O, nested JSON budgets and returned UID identity |
| Diagnostic-text oracle gaps | 134 | Assert useful failure distinctions where contractual; avoid blanket exact-wording tests |
| Caller/import/library context still needs certification | 40 | Keep uncertainty explicit; no declaration of harmlessness |
| Equivalent alternatives with a specific semantic reason | 13 | Retain in denominator without discounts |

Examples include `index` versus `rindex` over the unique `KMGTPE` alphabet and
selector defaults that cannot be observed because of presence short-circuits.
Remaining structured JSON depth/shape/default cases and exact defensive size
edges are useful follow-up oracle work. Surviving mutants do not establish a
production defect by themselves; no source workaround or score exemption was
added. This triage does not expand the 0.3.0 release gate.

The current line/branch/changed-line and critical 100% coverage gates remain
unchanged. Production bytes did not change in this issue, so changed-production
coverage is not applicable. Reconsidering any critical-line mandate requires
later stable mutation evidence and a separate maintainer decision. This scoped
local score does not certify a different integrated source or another platform.
