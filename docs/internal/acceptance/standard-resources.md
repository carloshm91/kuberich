# B05 #41 acceptance evidence

The implementation adds 15 discovered standard resource tables. It shares the
existing session/list-watch/inspection ownership contracts and uses a single
widget with resource-specific columns. No mutation action is advertised.

| Acceptance | Verification |
| --- | --- |
| Each advertised endpoint, scope and typed columns | Parameterized registry and group-aware projection contracts; every family runs real discovery/LIST/WATCH/GET through Pilot |
| Typed numeric/time ordering, unknowns | Counts versus lexical order; binary/decimal storage quantities; timezone-aware instants; unknowns last both directions |
| Safe ordinary views | ConfigMap/Secret rows contain only counts/type; payloads excluded from filters and redacted on GET/YAML |
| Supported actions and unavailable APIs | Per-view shortcuts; Enter details; pod-only logs; absent and denied API failures followed by successful navigation |
| Stable responsive tables | Bounded patches, generation invalidation, UID replacement/deletion, scroll anchors, sorting, age updates, retained history, 40×12 and 100×30 layouts |
| Real Kubernetes | Owned kind fixtures for all 15 families, actual annotation changes arriving through WATCH, UID preserved and individual YAML GETs |
| Actual terminal/install | Source and freshly installed console/module PTYs, initial scoped command, workload/service/storage/Secret navigation, resize and terminal restoration |

Measured private-development evidence (Linux; no new macOS qualification):

| Interpreter | Complete-suite result | Lines | Branches | Changed lines |
| --- | --- | --- | --- | --- |
| CPython 3.12.12 | 2,469 passed in each of two runs; affected corrected fixtures verified separately | 6,769/6,801 (99.5295%) | 1,989/2,034 (97.7876%) | 376/376 (100%) |
| CPython 3.13.12 | 2,469 passed in 1,354.69s; final handoff fixture verified separately | 6,770/6,801 (99.5442%) | 1,990/2,034 (97.8368%) | 376/376 (100%) |
| CPython 3.14.3 | 2,468 passed, one handoff fixture failure; corrected complete affected family passed | 6,648/6,680 (99.5210%) | 1,989/2,034 (97.7876%) | 362/362 (100%) |

Each interpreter independently passes the complete-production inventory and all
30 critical-module gates. Executable-line counts are interpreter-specific; every gate checks the same
complete production file inventory, with no production file excluded.
These results distinguish complete runs from targeted correction evidence.

- Production source was frozen at commit
  `25f9c1012b2917685895ea4ffe80585fe9b9e62e`, `src` tree
  `7a0e8c63fbd65cb594675b96420929dfa37ac7da`, against main
  `af3ec46a6e3015868638fae96ae37098b2dcfde4`.
- Python 3.12.12: two complete runs each passed **2,469 tests** in 1,691.93s
  and 1,697.94s. Retained logs are `py312-repeat-1.log` and
  `py312-repeat-2.log` under `/tmp/kubetrol-41-evidence`.
- A separate complete Python 3.12 run passed 2,468 and failed one installed
  navigation assertion: the namespace title arrived before its DataTable header.
  Test-only commit `2d78dfa07b3adad091ff937d3b5d84def2ec03a2` explicitly waits for
  the header and preserves the same content assertion. All eight affected
  source/installed navigation and installer trials passed in 126.33s at that
  commit (`navigation-final.log`). Its production tree is identical. This is
  combined verification, not a fabricated single complete rerun at that head.
- Independent complete-production gates measure **6,769/6,801 lines (99.5295%)**
  and **1,989/2,034 branches (97.7876%)**, including unimported modules. All 30
  designated critical modules reach 100% independently for lines and branches.
  Changed production coverage is **376/376 executable lines (100%)** against
  the exact main base on Python 3.12. Evidence: `py312-repeat-1.json`,
  `py312-repeat-1.xml` and `diff-py312-clean.json`.
- New registry: 143/143 lines and 32/32 branches (100%). New shared standard
  table: 136/136 lines and 36/36 branches (100%). The registry's semantic suite
  initially passed 109 cases; complete suites include its 15 additional initial
  CLI command cases. All-resource Pilot verification passed 20 cases, including
  absent/denied APIs, scopes, watch updates, history and context return.
- Source and freshly installed console/module PTYs passed real standard-resource
  navigation, scoped initial launch, details, redacted Secret YAML, narrow/wide
  resize and terminal restoration. Fresh wheel/sdist, isolated uv tool/pipx,
  dependency/security and release guard contracts run in the complete suites.
- `uv run python -m scripts.verify_contexts_kind --kind /tmp/kubetrol-tools/kind --evidence /tmp/kubetrol-41-evidence/kind-frozen.json`
  passed at the frozen production source against kind 0.33.0 / pinned Kubernetes
  1.36.4. Before writes, the generated endpoint and Docker node were verified as
  owned. Every family passed actual LIST/WATCH/GET with a watched annotation
  change and stable UID; the disposable cluster was removed afterward.
- Ruff, formatting (300 files), strict mypy (88 application/script files), plan
  validation, whitespace, wheel/source build and Twine metadata checks pass.
  Pinned actionlint 1.7.12 validates all three workflows; its optional shellcheck
  and pyflakes integrations were disabled, not reported as passing.

Commands for the complete interpreter-specific qualification:

```sh
uv sync --locked --group dev --python 3.13
uv run --locked --python 3.13 python -c 'import sys; print(sys.version); assert sys.version_info[:2] == (3, 13)'
COVERAGE_FILE=/tmp/kubetrol-41-evidence/py313.coverage uv run --locked --python 3.13 pytest --cov=kubetrol --cov-branch --cov-report=xml:/tmp/kubetrol-41-evidence/py313.xml --cov-report=json:/tmp/kubetrol-41-evidence/py313.json -q
uv run --locked --python 3.13 python scripts/check_coverage.py /tmp/kubetrol-41-evidence/py313.json
uv run --locked --python 3.13 diff-cover /tmp/kubetrol-41-evidence/py313.xml --compare-branch origin/main --fail-under 90 --total-percent-float
```

The 3.14 qualification uses the same commands with `--python 3.14` and
`py314` evidence paths, in a separate worktree. Complete logs and coverage
reports are `py313.log`/`.json`/`.xml` and `py314.log`/`.json`/`.xml`. The independent
gate outputs are `py313-gates.log` and `py314-gates.log`; diff JSONs are
`diff-py313.json` and `diff-py314.json`. Both suites run at test-only commit
`2d78dfa07b3adad091ff937d3b5d84def2ec03a2` with the identical frozen production tree.

The complete 3.14 run exposed a volatile test witness: the resource renderer
could overwrite the handoff probe's status row after resizing in tmux. The final
harness moves that probe to a stable unused command-border title and gives every
child/return/probe handshake a distinct attempt identity, so a tmux replay or a
previous probe cannot satisfy a later interaction. An initial counter counted a
failed spawn as a completed probe; that fixture error was corrected and its failed
trials retained. None of these changes alters production handoff or removes its
assertions about foreground ownership, resize, actual input, repeated returns,
process cleanup or TTY restoration.

All **22 affected native-handoff trials** pass on each actual interpreter at
`5377a62e978190d8c44378b02319f41d52cf70b3`: Python 3.12 in 59.86s, 3.13 in 48.45s,
and 3.14 in 51.33s. Logs are `handoff-qualified-py312.log`,
`handoff-qualified-py313.log`, and `handoff-qualified-py314.log`. Each run includes
source, fresh installed wheel, native PTY, real SSH and tmux variants:

```sh
uv run --locked --python 3.14 pytest tests/terminal/test_handoff.py tests/terminal/test_transports.py::test_real_transport_native_handoff tests/packaging/test_distribution.py::test_installed_terminal_handoff_uses_packaged_services tests/packaging/test_distribution.py::test_installed_wheel_native_handoff_over_ssh -q --maxfail=1
```

Use `--python 3.12` and `--python 3.13` for the corresponding separate runs.
The final production tree remains `7a0e8c63fbd65cb594675b96420929dfa37ac7da`.
These are successful corrected families combined with the recorded complete
suite results, not an invented all-green complete run at the final documentation head.

Initial synthetic-watch, constructor and verifier SDK response-map errors were
retained and corrected. Two worktrees initially intended for 3.13/3.14 used uv's
3.12 project pin; their successful results are correctly recorded as **3.12**
above. Explicit interpreter selection plus a version assertion corrects that
qualification error. None of these failures is counted as a successful check.

Hosted jobs did not start because GitHub rejected the account billing/spending
limit. DCO passed on the pushed implementation head; hosted quality/repository
jobs remain failed with zero runner time and no executed steps. Local merging
uses the maintainer-authorized private-development exception. The full six-job
Linux/macOS matrix remains mandatory before public release.

Remaining behavior is explicitly tracked: resource mutations #43–#46, generic
CRD/server columns #53, broader drill-down/navigation #61, ephemeral containers
#78, metrics #68 and real cloud/provider certification #87. No release or public
distribution artifact is published by this issue.
