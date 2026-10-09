# Development Pages publication: #166

The maintainer explicitly authorized publishing the current landing and initial
documentation on two Cloudflare Pages provider hosts on 2026-10-09. Custom domains,
DNS and `www` are deferred. Application tags, packages and the first-product 1.0.0
gate remain separate. Committed B06 #53 work is preserved for resumption.

## Local verification before the publication PR

`uv run pytest tests/quality/test_pages.py tests/quality/test_site.py
tests/quality/test_supply_chain_policy.py tests/quality/test_ci_policy.py -q`
passed **121 cases in 48.31 seconds**. Publication tests use owned loopback HTTP
for authenticated API responses and actual file/header/404 probing, real Node
subprocesses for exact argv/failure receipts, and isolated Git for clean-source
identity. They cover missing/conflicting projects, failed auth, refused API
redirects, stale public bytes, bounded retries and first/second upload failures.
Synthetic provider responses are not claimed as real Cloudflare qualification.

Ruff, formatting, plan validation and strict mypy passed. Source plus site/deploy
scripts passed strict types over 107 files. No application production code changes;
changed executable application coverage is N/A. All required PR application and
independent coverage gates remain mandatory.

`uv run python -m scripts.build_site` and `uv run python -m scripts.check_site`
verified 49 HTML pages, 1,722 local links/assets and 64 total build files.
`node scripts/verify_site_browser.mjs` passed real Chrome 143.0.7499.169 desktop/
mobile checks on both surfaces, with zero automated accessibility violations.
The manifest SHA-256 was
`39431bf969de0a8f61d8ca8e48ef9afe50531beec98acdb1ea949dbbe024d3b5`.
Node dependencies were installed from locks with scripts disabled. The Wrangler
4.149.0 CLI actually ran; its npm audit reported zero vulnerabilities.

Local receipts are retained in `artifacts/pages-publication`, `artifacts/site`
and `artifacts/site-qa`. They do not establish provider publication or TLS.

## Actual provider acceptance

The workflow retains `checked-site`, `website-browser-evidence` and
`pages-publication-receipt` for 30 days. The receipt links the exact main source
and build manifest to project/deployment IDs and actual provider URLs. Each
successful surface requires HTTPS file digests, declared headers and custom 404
checks at both its immutable deployment and production hostname. `upload_attempted`
records possible partial publication even when the CLI fails. Only a verified
deployment establishes `publication_performed`; a failed second upload retains
the first result. No atomic two-project publication or untested rollback is claimed.

The live [issue #166](https://github.com/carloshm91/kuberich/issues/166) records
the exact required PR checks, source identity, manual dispatch, protected review
and actual publication result. Do not infer hosting from a prepared workflow or
proposed project name. Provider success closes this focused delivery, not #89.
