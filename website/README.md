# Initial KubeRich website

This is the development launch material from #150, refined in #162.
It is a static landing page, authored user guides and four generated references, without a backend, account system, analytics,
external fonts or cluster connectivity. Expanded/versioned MkDocs stays #90/#91.

The HTML guides are built from the maintained files in `docs/`; edit those
sources instead of duplicating installation instructions. The project version
comes from `pyproject.toml`. CLI flags/aliases/descriptions come from the actual
argument parser, resource aliases/scopes/columns from the application registry,
and capability status/public summaries from `docs/capabilities.json`. The default
build retains noindex directives. An explicit public-launch build requires an
exact verified published release; prepared future versions remain previews.
The builder never registers a project or changes DNS.
The separately authorized #166 workflow publishes checked bytes to provider hosts;
its publication receipt records actual URLs and IDs. See
[development publication](../docs/website.md#development-publication-166).

## Build and preview

From the repository root:

```sh
uv sync --locked --group dev
uv run python -m scripts.build_site
uv run python -m scripts.check_site
uv run python -m http.server 8715 --bind 127.0.0.1 --directory artifacts/site/www
```

The local landing page is at `http://127.0.0.1:8715/`; its guides are at
`http://127.0.0.1:8715/docs/`. Stop the owned server with Ctrl+C. This loopback URL
is reachable on the machine running the command; it is not a hosted preview.
The second output, `artifacts/site/docs`, is the same initial documentation
prepared to serve at the root of the proposed docs.kuberich.com host.

Build output is exclusive unless its inventory identifies an earlier owned
build. Unexpected files, symlinks, changed media or broken links fail the checks.
`build-manifest.json` retains source/output SHA-256 digests and publication status.
Generated output is ignored and never enters the Python wheel/source allowlists.
The checker also compares every input receipt with the current checkout: changed
guides, contracts, imported application modules or newly added modules require a
rebuild. Use `--source PATH` when checking a build made from a different checkout.

## Browser verification

Use Node 20+ and an installed Google Chrome. These are developer QA prerequisites,
not KubeRich runtime dependencies:

```sh
mkdir -p artifacts/site-qa
cp website/qa/package.json website/qa/package-lock.json artifacts/site-qa/
npm ci --prefix artifacts/site-qa --ignore-scripts
node scripts/verify_site_browser.mjs
```

The locked Playwright/axe tools run against an owned loopback server, close the
browser/server, and retain desktop/mobile PNGs and `browser-report.json` in
`artifacts/site-qa`. The checks cover every HTML page at desktop and 390px mobile widths with A/AA
automated accessibility and page overflow checks, plus 320px landing/reference
checks. They verify decoded images, keyboard skip navigation, the native mobile
guide menu, clipboard success/denial and guide navigation with JavaScript disabled. Runtime external requests are rejected.
Automated accessibility does not establish screen-reader certification.

## Keep documentation current in each product PR

1. Update the relevant authored guide in `docs/` with the new behavior, keys,
   prerequisites, failure/permission paths and honest limits. Prose cannot be
   inferred from an implementation. Update `docs/capabilities.json` under its
   existing evidence policy; a partly delivered audit row stays planned until qualified.
   Update `public_summary` and `public_status` for reader-facing availability
   (available, partial, planned or unverified). Keep internal task IDs and historic
   acceptance records out of public guide prose and generated reference text.
2. Edit `docs/navigation.json` to change user navigation on both surfaces. It
   lists the four Diátaxis types and 23 canonical content pages plus the index:
   24 pages total, including four generated references. Keep acceptance
   reports, architecture and maintainer-only procedures outside user navigation.
   Follow [the documentation style](../docs/STYLE.md) and update every document's
   disposition in `docs/documentation-plan.json` when a source changes purpose.
   The task guides and generated references meet the 250-line page budget.
   Their sources are rendered once and included in the source receipt.
3. CLI and standard-resource declaration changes appear automatically in the
   reference on the next build. `scripts/site_reference.py` constructs the parser
   and reads the registry in an isolated subprocess against the selected checkout;
   it never launches the UI, reads kubeconfig or makes a cluster request. Extend
   that generator deliberately when a new declarative contract needs a reference;
   do not maintain a second hand-copied flag/resource catalogue.
4. Run the build, checker and relevant site tests. Review changed guide/reference
   output on **both** surfaces. Repository checks on every PR/main push rebuild
   both trees, check source receipts and run browser/accessibility verification;
   application CI retains site regression tests and all existing coverage gates.
5. A release candidate uses the same sources and generator. Rebuild and verify
   the exact qualified candidate under #89 before any approved publication.
   Build automation is already active; deployment/DNS automation is a separate gate.

The references display the source version, retain unavailable options and planned
capability differences, and link to maintained sources. Generated Markdown is
checked in at its canonical `docs/*.md` paths so links also work in GitHub.
Run `uv run python -m scripts.site_reference --write` to regenerate it and
`uv run python -m scripts.site_reference` to check declaration drift. Do not edit
generated Markdown or HTML by hand.

Retired guide paths have explicit `legacy_routes` in `docs/navigation.json`.
The builder rewrites internal links to real canonical headings and emits local
301 rules for both extensionless and `.html` paths. Redirect destinations omit
fragments so browsers can preserve an incoming fragment. Canonical pages publish
aliases for retired headings, while internal links map directly to active headings.
When a later rewrite removes a source fragment, preserve its route and aliases
and update its `heading` to the corresponding canonical heading. The checker rejects
missing target anchors, unexpected pages, changed routes and source drift.

## Media

`assets/media.json` identifies and hashes the actual rendered SVGs. The main
workspace and logs use synthetic resources through the actual local HTTP client
and Textual UI. Both screenshots come from the same disposable loopback API;
neither needs a cluster or customer data. Rich's external font declarations are
removed; vectors use local monospace fallbacks. These are actual application
renders, not reconstructed product mockups.

To capture both images, use a new directory:

```sh
env -u NO_COLOR uv run python -m scripts.capture_site --output /absolute/path/to/new-media
```

Review the rendered data and inventory before replacing the three corresponding
tracked assets. The producer refuses dirty or foreign application sources and records
the exact commit/runtime tree/version, redaction and stream/client/handler cleanup. The producer uses only its loopback fixture, never ambient
kubeconfig, and checks log redaction and stream/client shutdown. The optional
`--logs-source /absolute/path/to/previous.svg` imports an existing offline SVG;
its inventory explicitly records that it was not regenerated and that the
producer cannot establish its source or privacy status. Review such an image
separately before tracking it; a digest does not reconstruct missing evidence.

See [hosting and release gates](../docs/website.md) and
[measured acceptance](../docs/internal/acceptance/initial-website.md).

## Publication ownership

Initial local preparation and the first public deployment are delivered. Each
release updates its verified publication record and guides, then checks both
static surfaces from that exact documentation source. The protected GitHub
Actions → Cloudflare Pages workflow deploys the checked bytes after concrete
website approval; a source merge alone does not update hosting. Package/site/DNS
publication needs its applicable authorization. Existing production hosts need
no DNS change for a content update. See [the deployment procedure](../docs/website.md).

## Published installation status

`docs/published-releases.json` records versions whose actual package, GitHub and
Homebrew publication passed verification. Update it with the retained channel
evidence after activation. The builder enrolls this file in its source manifest
and shows public installation status only for an exact recorded version. A new
source version stays a prepared release until its own activation is recorded;
changing `pyproject.toml` alone never advertises published packages. Building the
site still does not deploy it.

## Prepare the public website

After verified artifact activation, prepare indexable landing/docs output:

```sh
uv run python -m scripts.build_site --public-launch --output artifacts/site-public
uv run python -m scripts.check_site --output artifacts/site-public
node scripts/verify_site_browser.mjs artifacts/site-public artifacts/site-qa
```

The explicit mode updates HTML metadata, response headers and robots files on
both surfaces while retaining the existing security headers. It refuses a
development or unpublished source version before replacing existing output.
Public output puts the landing page on `kuberich.com` and guides exclusively
on `docs.kuberich.com`, with canonical URLs and direct documentation links.
Legacy `/docs` paths have checked 301 redirects. Default preview output keeps
its nested guides for offline local navigation; public deployment omits that
duplicate tree. Browser qualification maps the two declared public hosts to
owned loopback responses, never to a real cluster or live provider deployment.
The checker rejects inconsistent version, indexing policy and output/source
digests. Every build manifest still records `publication_performed: false`.

Only after concrete owner approval, dispatch the protected Website publication
workflow with its `public_launch` input enabled. It rebuilds and browser-verifies
that mode without credentials, then uploads the exact checked artifact after
environment review. Public verification compares the selected headers as well
as every file digest. The input defaults to preview mode; repository checks
and ordinary PRs do not publish. See [launch procedure](../docs/website.md).
