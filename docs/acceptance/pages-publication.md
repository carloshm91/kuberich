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

Ruff, formatting, plan validation and strict mypy passed. The initial site-only
source plus site/deploy scripts passed strict types over 107 files; its executable
application coverage diff was N/A. The first hosted macOS run subsequently exposed
the existing subprocess group exit race described below. The correction changes
application code, so final changed-line coverage must be measured. All required PR
application and independent coverage gates remain mandatory.

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

## Required macOS subprocess prerequisite

The first PR run failed the stderr-limit download contract while sending SIGCONT
to an exiting owned group. Apple's [XNU signal implementation](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/kern_sig.c)
can find a group but filter out its zombie members and return EPERM. Cleanup now
probes a denied Darwin group with signal zero after up to five nonblocking 10 ms waits, accepting only
ESRCH as confirmation that the group disappeared. Live-group and persistent
permission errors still propagate; non-Darwin permission errors remain immediate.
No real permission failure is silently treated as successful cleanup.

Regressions exercise disappearance after transient denials, persistent/live
negative controls and actual owned-child exit/reaping. Existing real-descendant,
timeout, repeated-cancellation, PTY, attach, forwarding and transfer contracts
remain required. The local process/transfer/attach/forward/PTY cohort passed
163 cases in 23.15 seconds. All 17 changed executable production lines were
covered (100%). Ruff/formatting and strict types over 108 files passed. This
focused run does not replace the full hosted coverage gates; final native
evidence is recorded on the live issue.

The second native macOS run passed the process regression but failed an installed
pipx navigation probe: an age-only repaint erased the rejected `:ns` feedback
while namespace discovery was gated. A local owned-API/Pilot regression reproduced
that overwrite before the fix (1 failed in 1.50 seconds). The UI now preserves
this notice for the exact pending view and clears it when the connection changes.
The original installed/source PTY and pipx/uv installation trials remain required;
their visible feedback assertion is retained. The navigation/installer/process
cohort passed 103 cases in 204.03 seconds, including real source terminal and
all four isolated uv/pipx wheel/sdist installs. All 28 changed executable
production lines were covered (100%); lint/formatting and strict types passed.

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
