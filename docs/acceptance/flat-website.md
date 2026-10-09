# Flat landing and generated references: #162

## Scope and sources

This local preparation implements [#162](https://github.com/carloshm91/kuberich/issues/162)
on top of the qualified C08 product. It changes repository-owned static design,
build tooling and documentation; no production application module or runtime
dependency changes. Source version remains `0.0.1.dev0`. The source repository is
public, but packages, hosting and DNS remain unpublished. #162 is a readiness
prerequisite of #89; expanded/versioned documentation stays #90/#91.

The landing and both docs surfaces share light paper, ink text, one blue accent,
flat rules and spacing. The actual terminal SVGs and their original provenance
are unchanged. Desktop uses a guide sidebar; mobile uses a keyboard-operable
native disclosure. With JavaScript disabled, the full guide list remains usable.
There is no backend, tracker, external font or runtime asset dependency.

Eighteen authored guides are enrolled in `scripts/build_site.py::GUIDES`. Three
references derive launch flags/aliases/help from the actual parser, standard
resource aliases/scopes/columns from the registry, and unchanged status/difference
text from `docs/capabilities.json`. Isolated offline parser construction uses the
selected checkout, never CLI execution or kubeconfig loading. The generated
reference is distinct from authored behavior, prerequisites and limits.
[Contributor instructions](../../website/README.md#keep-documentation-current-in-each-product-pr)
require guide updates in the same behavior PR and explain new-guide enrollment.

The manifest records input/output SHA-256 receipts, including all production
Python modules that can supply imported declarations. Source checks reject edited
guides/contracts and newly added unreceipted modules. The regression suite changes
a parser flag and registry alias in a separate copied checkout and verifies both
surfaces actually change. Planned capability status and partial differences are
preserved. Repeated builds compare exact manifests, with no wall-clock fields.

## Local verification

Run from the issue worktree on Linux, CPython 3.12.12:

```sh
uv sync --locked --python 3.12 --group dev
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict scripts/build_site.py scripts/check_site.py scripts/site_reference.py
uv run pytest tests/quality/test_site.py tests/quality/test_release_policy.py -q
uv run python -m scripts.build_site
uv run python -m scripts.check_site
python3 scripts/validate_plan.py
mkdir -p artifacts/site-qa
cp website/qa/package.json website/qa/package-lock.json artifacts/site-qa/
npm ci --prefix artifacts/site-qa --ignore-scripts
npm audit --prefix artifacts/site-qa --audit-level=low --json
node scripts/verify_site_browser.mjs
```

Ruff, formatting and strict site typing pass. The focused site/release-policy
suite passes **122 tests**; 15 are site behavior/negative controls. Repository
validation passes, and the locked browser-tool audit reports zero vulnerabilities.

The static build contains 47 HTML pages across both surfaces; the link checker
validates 1,596 local links/assets. It preserves noindex, robots exclusion, the
restrictive `_headers` policy, offline assets, Apache-2.0 notices and qualified
media descriptions. Output is local under `artifacts/site/www` and
`artifacts/site/docs`; neither tree is uploaded by this workflow.

The browser rehearsal serves those declared headers on an owned loopback server,
closes its browser/server, and writes source-associated receipts to
`artifacts/site-qa/browser-report.json`. Desktop/mobile screenshots are retained
there as `landing-desktop.png`, `landing-mobile.png`, `docs-desktop.png` and
`docs-mobile.png`, with additional viewport captures for readable first-screen
review. `artifacts/site/build-manifest.json` binds the receipts to exact input and
output bytes. Browser results below refer to that final manifest, not a mockup.

Final browser result: **47/47 desktop and 47/47 mobile pages pass with zero
WCAG A/AA axe violations and no horizontal page overflow**. Narrow 320px
landing/CLI/resource references also pass. Keyboard skip navigation and mobile
menu expansion, direct reference navigation, clipboard success/denial and
navigation without JavaScript pass; there are zero external requests or browser
errors. Wide tables and code blocks accept keyboard focus for local scrolling;
long reference headings wrap without truncation.

- Chrome: `143.0.7499.169`; Playwright: `1.64.0`; axe: `4.14.0`.
- Build manifest SHA-256: `e391257bb93ad81eea70e7e69093b867227ac328079da304d0910dc5b0dacc28`.
- Browser report SHA-256: `7362959c42f589d528ebb5c9647fcf0ce2696443ac0385aa7859e32cd8747bf1`.

## Limits and release ownership

Automated axe checks and keyboard behavior do not establish screen-reader or
all-browser certification. Browser rehearsal verifies the declared security
headers locally, not enforcement by a provider. No hosting registration, provider
preview, DNS change, public package/tag or release occurs. No new real-cluster or
cloud-provider test is claimed. Unchanged executable application coverage is N/A
for this site-only delta; the four-platform application matrix and all independent
coverage gates remain mandatory on the issue PR. Final candidate qualification,
public quickstart, hosting and DNS are still the separately approved #89 task.
