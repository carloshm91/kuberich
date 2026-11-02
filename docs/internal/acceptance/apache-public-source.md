# Apache-2.0 and public source acceptance: #155

> Historical receipt: the later maintainer-requested phased policy starts at
> qualified 0.1.0. See [current release policy](../releases.md); this record
> preserves the original source, scope and measurements.

The maintainer approved Apache-2.0 and opening the source repository on
2026-10-08. This task changes project licensing, notice inclusion and current
source/release guidance; it changes no application behavior or version.

## Qualified source and checks

The frozen implementation commit is `e15ddc89b1fd4a501e8582864ae40c88c997d74b`;
its scripts tree is `dcbb9b719a046f29dee466b23355067acccbbb0f` and tests tree is
`4c009fec283424c08979f04d5dacaad788ee9c95`. Final evidence-only documentation
does not change those trees, project metadata or artifact inputs. The application
tree remains `15fd0846629430a4ce413f87548818cf0ee4952f`, identical to base main
`f561cc4928852366c343dad20f57f0a3fa53957e`. Changed executable application
coverage is N/A; existing whole-code and critical-module gates are preserved,
and this task does not claim a new application coverage measurement.

Measured on Linux with uv 0.10.4:

- CPython 3.12.12: `uv run --locked pytest tests/quality tests/packaging`
  passed **464 cases in 564.83 seconds**. This includes complete wheel/sdist
  payloads and source rebuild equivalence, private-file traps, fresh installed
  CLI/PTY trials, actual isolated uv/pipx installers, audited unpublished RC
  formula generation, release-source guards and supply-chain negative controls.
- Python 3.13 and 3.14 each ran `tests/packaging/test_artifacts.py`,
  `tests/quality/test_release_transport.py` and `tests/quality/test_site.py`:
  **34 passed** in 10.69 / 10.63 seconds respectively. These are focused
  interpreter checks, not the full application matrix or a new macOS result.
- Ruff check and format check passed (364 Python files); strict mypy passed
  over all application modules and required verification/delivery scripts
  plus the site tools (109 source files). Plan/link validation passed.
- `uv build --out-dir artifacts/apache-public-source/dist` and `twine check`
  passed. The wheel metadata is `License-Expression: Apache-2.0`; both artifacts
  carry byte-identical LICENSE and NOTICE. The official license SHA-256 is
  `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`.
- Locked and fresh installed runtime audits each checked 27 dependencies with
  **zero findings**; retained original dependency licenses remain unchanged.
  Audit provenance names the exact distribution digests below.
- Site build/check passed: **37 pages, 52 files and 1,056 local references**.
  Real Chrome 143.0.7499.169, Playwright 1.64.0 and axe 4.14.0 checked every
  desktop page with **zero accessibility violations**, plus existing keyboard,
  mobile/copy/no-JavaScript behavior. npm audit reported no vulnerabilities.

## Publication review

Owned Gitleaks 8.30.1 was downloaded from its official release with verified
archive SHA-256 `551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb`.
The raw all-ref historical scan returned exit 1 for six findings; that failure
is retained. Each finding was reviewed in `test_logs.py` / `test_diagnostics.py`:
they are deliberately malformed synthetic PEM markers exercising redaction,
not usable private keys. A separate scan of the licensing commit passed with
zero findings. This review does not claim that a scanner proves absence of all
possible sensitive information. No local untracked experiment was included.

Repository name, tracked source/history and repository-visible issue/PR metadata
were reviewed. No existing GitHub release or GitHub Pages deployment was found;
the separate GitHub project was verified private. The maintainer's explicit
approval covers opening only `carloshm91/kuberich` after the checked license PR.
The resulting visibility and anonymous LICENSE access are checked after opening
and recorded in #155. Website/DNS, public tap, package uploads and tags remain
separate gates. First public product release remains 1.0.0.

Hosted checks were blocked by the account quota/billing restriction before
opening; the private merge uses the authorized measured local exception and
preserves their real status. Recheck hosted CI after opening. Native macOS/full
platform, provider and final-candidate release qualification remain pending.

## Retained local evidence

`artifacts/apache-public-source` retains commands/logs, JUnit, official-license
and distribution digests, redacted scanner reports and finding review. Existing
`artifacts/security`, `artifacts/releases`, `artifacts/packaging`,
`artifacts/terminal`, `artifacts/site` and `artifacts/site-qa` retain actual
audit/RC/installer/terminal/browser evidence. These developer artifacts remain
outside Git and package payloads.

Distribution SHA-256 values:

- wheel: `c04ebfe5a251719580a33658e458a2b60c3843f195a9a417a112b4b728a7e352`
- sdist: `89b75b5bbf2ecf310097e29e72ed1f6dd1e2a03bb83429ebcacd188dec4e6909`
