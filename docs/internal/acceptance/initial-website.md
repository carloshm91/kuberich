# Initial private website preparation: #150

This ticket prepares reviewable static launch material. It does not complete
public release #40, publish a website, change DNS or certify native macOS/cloud
providers. The exact release-candidate and approved publication criteria stay open.

## Implemented local result

- Original responsive landing with actual, inventoried offline SVG captures.
- Sixteen user guides generated from the maintained Markdown sources, an index
  and 404 page, built for both `/docs/` and a separate root docs host.
- Version from `pyproject.toml`, read-only first launch, local wheel/checkout
  instructions, uninstall, helper prerequisites and explicit unavailable channels.
- Strict output ownership, deterministic source/output SHA-256 manifests,
  internal link/anchor checks, inactive screenshot content and no external assets.
- Keyboard navigation, optional code copying with a polite success/error result,
  JavaScript-free navigation, reduced-motion support and no hosted backend.
- A concrete Cloudflare Pages/custom-domain/deployment/rollback proposal with
  provider sources and separate publication/DNS approval.

The workspace image is rendered by the actual client/Textual code against an
owned local API with synthetic resources. The log image is retained from the
qualified owned-kind trial; its deleted cluster is not a current endpoint. Media
hashes and source conditions are recorded in `website/assets/media.json`.
No user context or private cluster data was read to make the site.

## Verification record

Frozen implementation: `22a65ac1aad597601e15e99798158a3fe5d512ff`.
Test tree: `73ecacb29f991b9e092a41387d1b328b76eaffb0`. Final delivery documentation does not change
the application, scripts, tests, site sources or any distribution input.

| Local Linux check | Measured result |
| --- | --- |
| CPython 3.12.12 quality/artifact/fresh-distribution suite | 405 passed in 161.58 s, no skips/failures |
| CPython 3.13.12 site regression suite | 13 passed in 2.31 s, no skips/failures |
| CPython 3.14.3 site regression suite | 13 passed in 2.15 s, no skips/failures |
| Static build and link/anchor/digest check | 37 pages, 52 output files, 1,056 local references |
| Build size, including retained manifest | 581,157 bytes across both surfaces |
| Chrome 143.0.7499.169 / Playwright 1.64.0 / axe 4.14.0 | All 37 desktop pages; mobile landing and quickstart; zero automated A/AA violations |
| Browser behavior | Keyboard skip focus, decoded images, copy success/denial, JavaScript-free navigation; zero runtime external requests/failures |
| Exact documented Python HTTP preview | Landing, docs index, quickstart and workspace image returned exact expected bytes; server stopped |
| Ruff and formatting | Passed, 362 Python files formatted |
| CI-declared strict types plus the new builder/checker | Passed, 109 files |
| Plan/links, whitespace and actionlint 1.7.12 | Passed; optional shellcheck/pyflakes integrations disabled |
| Rebuild / Twine / locked + fresh runtime security | Passed; 27 dependencies in each audit, no advisories/exceptions; SBOM/inventory/unsigned local provenance verified |
| Locked browser-tool npm audit | Zero reported vulnerabilities |

The initial browser iteration rejected insufficient contrast on the docs index;
that foreground was corrected. A premature all-image assertion was changed to
wait for actual lazy-image decoding. Mobile heading breaks and complete rendered
screenshots were visually inspected and corrected before the final green run.
Negative controls reject unsafe HTML/links, missing anchors, stale digests,
uninventoried files, changed captures and attempts to overwrite foreign output.

Commands include `uv run python -m scripts.build_site`,
`uv run python -m scripts.check_site`, the test suites above and
`node scripts/verify_site_browser.mjs`; Node dependencies/integrities are locked
in `website/qa`. Actual PNG/JUnit/audit/build outputs and browser report are
retained in ignored workspace `artifacts/site` and `artifacts/site-qa`, outside
`/tmp`. The exact build manifest SHA-256 is
`587f972ea91e4905eaff0722eb500cb1935456f9df394992c1b43b936f1806de`.

Rebuilt local development artifacts, not published:

- Wheel SHA-256: `109863a31e84734b4d1f4f98628aed826cf41742ef6b75d4488dcac96fdcdf9b`.
- Source distribution SHA-256: `345cc0f0a009cbd1e6e146d0a066d0aa303e6e00cc7007572e6fe170ba1d81a9`.

Fresh artifact tests verify actual installed entry points and payloads; website
sources/browser dependencies do not enter the runtime distributions. These are
`0.0.1.dev0` bytes, not public artifacts or the final #40 release candidate.

Application source is unchanged from the #149 qualified production tree
`7f64b0f1e46acaa60280ef006f6a1bf4ccca70bc`. This site-only delivery does not claim
a new application coverage percentage; changed executable application lines are
N/A. The direct Markdown builder dependency was already a locked runtime
dependency; no resolved package/version was added or upgraded.

## Honest limits

Hosted Actions remain unable to start because of account billing; the private
local-verification exception applies. Linux browser/installation evidence does
not establish native macOS, a working public PyPI/Homebrew channel, a qualified
final 0.0.1 release, screen-reader certification or provider-hosted header/TLS
behavior. Publication and DNS were not attempted. #150 remains open for those
final candidate/publication acceptance criteria; a prepared site is not a deployed
one. Real cloud trials remain the maintainer's later opt-in #87.
