# Q04 #35 dependency and supply-chain qualification

This task adds executable development/CI security gates for actual installed
runtimes and distribution bytes. It changes no application operation, publishes
nothing, and leaves the installed version at `0.0.1.dev0`.

| Acceptance behavior | Executed evidence |
| --- | --- |
| Complete installed locked/fresh dependency audits | Actual `pip-audit --strict --no-deps --disable-pip` reports for 27 runtime dependencies per scope/interpreter |
| Vulnerabilities cannot silently pass | Live advisory lookup for known-vulnerable `requests==2.19.1` exits 1; the gate rejects that report without installing the vulnerable version |
| Narrow reviewed exceptions only | Exact package/version/advisory, responsible owner, repository issue, mitigation and expiry; missing, ambiguous and expired exceptions fail |
| SBOM and artifact provenance sidecars | Actual CycloneDX 1.6 environment inventory/schema validation, exact component versions, artifact/lock/input SHA-256 attachment |
| License compatibility and retained notices | Approved SPDX policy, exact legacy-license reviews, original notice bytes/digests; explicit Pyte LGPL source and wcwidth inventory |
| Hostile process/display/export boundaries | Actual literal subprocess argv and markup, exclusive export refusal for existing paths/hardlinks/symlinks/directories and destination-creation race |
| Scanner/report integrity failures | Behavioral negative controls for missing/skipped/altered audits, inventories, notices, hashes, symlinks, unsigned-attestation claims and altered artifacts |

Plugin execution still belongs to U03 #58. These tests qualify the shared literal
process boundary, not an implemented plugin system. Sidecars are **unsigned**;
OIDC publication/attestation belongs to D02 #36. No real provider environment or
new kind trial was run for this unchanged application source.

## Measured local checks: 2026-10-07

Frozen executable/test/script/workflow candidate:
`00b69bfddbdf9e6c98e85c78521c9b217ba8833c`; base:
`8f1eda3a437be201a859b4deb42bf0f62342ed33`.
Final evidence-document edits preserve those four trees and the artifact inputs.

| CPython | Passing tests | Production lines | Production branches | Changed executable production lines |
| --- | --- | --- | --- | --- |
| 3.12.12 | 2,100 | 6419/6451 (99.50%) | 1891/1936 (97.68%) | N/A (0) |
| 3.13.12 | 2,100 | 6420/6451 (99.52%) | 1892/1936 (97.73%) | N/A (0) |
| 3.14.3 | 2,100 | 6312/6344 (99.50%) | 1891/1936 (97.68%) | N/A (0) |

Every minor independently passed all 29 critical modules at 100% lines/branches,
Ruff lint/format, strict application/gate/provider-verifier types, planning/link
validation, complete behavioral suite, coverage gates, wheel/sdist build, Twine,
and final offline verification against the exact built bytes. Each retained 59
UI SVGs and 140 terminal summaries/ANSI records, including owned SSH/tmux trials
and fresh installed-entry-point trials. The focused new-boundary preflight passed
91 tests before the frozen full matrices.

Full suite times were 1,245.49 seconds (3.12), 923.46 seconds (3.13), and 755.35
seconds (3.14). Host: Linux x86_64, kernel 6.8.0-142-generic/glibc 2.39,
uv 0.10.4, OpenSSH 9.6p1 and tmux 3.4. Security tools: pip-audit 2.10.1,
cyclonedx-bom 7.5.0 and cyclonedx-python-lib 11.12.0. Build backend remains
Hatchling 1.32.4. New dependencies are confined to the development group;
no existing locked package version changed.

## Candidate artifact identity

All three interpreters produced the same bytes for each format:

- `kubetrol-0.0.1.dev0-py3-none-any.whl`: SHA-256 `66efc09eab7d9f9d0b2a00eb87bee9f690179db415955a139c2acbd959df78e0`.
- `kubetrol-0.0.1.dev0.tar.gz`: SHA-256 `f4c1f11edd11860533d77a0dd7cc199de023b3556461d54e367a230afd948217`.

Both locked/fresh installed runtimes contain exactly the declared recursive
runtime closure, 27 audited dependencies, no development tooling and no accepted
vulnerability exceptions. Both scanners exit 0. Locked aiohttp is 3.14.3;
fresh installations resolved 3.14.4. Textual is 8.2.8, kubernetes-asyncio 36.1.0,
Pyte 0.8.2 and regex 2026.9.29. Future index resolution is not certified by these
measured current versions. The earlier D01 evidence's locked-aiohttp typo is
corrected to match its actual frozen lock.

The live vulnerable-version negative control found ten advisories, including
CVE-2018-18074/PYSEC-2018-28. Scanner exit 1 and gate refusal are required negative
results, not suppressed failures. Tests also reject altered evidence after its
outer report hash has been recomputed.

## Commands and evidence

For each explicit minor in an independent worktree:

```sh
uv sync --locked --group dev --python 3.12
uv run --locked --python 3.12 ruff check .
uv run --locked --python 3.12 ruff format --check .
uv run --locked --python 3.12 mypy --strict src/kubetrol scripts/check_coverage.py scripts/check_quality_gate.py scripts/check_supply_chain.py scripts/supply_chain.py scripts/dependency_inventory.py
MYPYPATH=src uv run --locked --python 3.12 mypy --strict --explicit-package-bases -m scripts.verify_aks_auth -m scripts.verify_eks_auth
uv run --locked --python 3.12 python scripts/validate_plan.py
uv run --locked --python 3.12 pytest -x --basetemp /tmp/kubetrol-35-evidence/full-3.12 --cov=kubetrol --cov-branch --cov-report=term-missing --cov-report=xml --cov-report=json
uv run --locked --python 3.12 python scripts/check_coverage.py coverage.json
uv run --locked --python 3.12 diff-cover coverage.xml --compare-branch origin/main --fail-under 90 --total-percent-float --format json:diff-coverage.json
uv build --python 3.12
uv run --locked --python 3.12 twine check dist/*
uv run --locked --python 3.12 python -m scripts.check_supply_chain --verify
```

The same matrix used 3.13 and 3.14. Packaging tests generate fresh security
evidence; the last command verifies it against the final build. Manual generation
is `uv build` followed by `uv run python -m scripts.check_supply_chain`.

Raw measured evidence, host/tool versions, complete matrix commands, coverage,
installed-runtime reports/notices, candidate bytes and known-vulnerable controls
are retained in `/tmp/kubetrol-35-evidence`. An earlier preflight correctly failed
because an input changed during generation; the subsequent frozen preflight and
all final matrices pass. No failed gate is used as successful acceptance evidence.

DCO succeeds. Eight hosted application/repository/gate jobs cannot start due to
the existing billing/spending restriction; they are not reported as passing.
The authorized local private-development procedure applies. macOS/arm64,
protected-main enforcement, release-environment approval, real provider trials
and public-channel qualification remain explicit gates in #40/#87/#109.

See [dependency security](../dependency-security.md) for policy, original upstream
license/source references, bounded exceptions and the 24-hour refresh rule.
