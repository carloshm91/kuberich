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

Local measurements are being finalized before the private PR merge. The commands
are `uv run python -m scripts.build_site`, `uv run python -m scripts.check_site`,
`uv run pytest tests/quality/test_site.py` and
`node scripts/verify_site_browser.mjs`; browser dependency versions/integrities are
locked in `website/qa`. Evidence remains in ignored workspace `artifacts/site` and
`artifacts/site-qa`, rather than disposable `/tmp` directories.

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
