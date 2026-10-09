# Initial KubeRich website

This is the **local, unpublished** launch material from #150, refined in #162.
It is a static landing page, 18 authored user guides and three generated references, without a backend, account system, analytics,
external fonts or cluster connectivity. Expanded/versioned MkDocs stays #90/#91.

The HTML guides are built from the maintained files in `docs/`; edit those
sources instead of duplicating installation instructions. The project version
comes from `pyproject.toml`. CLI flags/aliases/descriptions come from the actual
argument parser, resource aliases/scopes/columns from the application registry,
and capability status/differences from `docs/capabilities.json`. Both HTML surfaces retain explicit preview status
and noindex directives. Nothing here registers a hosted project or changes DNS.

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
   existing evidence policy; a partly delivered row stays planned until qualified.
2. For a new user guide, enroll its source, readable title and section in
   `GUIDES` in `scripts/build_site.py`. This allowlist owns both surfaces and their
   navigation. Keep acceptance reports, architecture and maintainer-only procedures
   out of that list. Existing verification/rehearsal sections stay source-only.
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
capability differences, and link to maintained sources. Generated Markdown exists
only in memory during the build. No generated HTML/reference file is hand edited.

## Media

`assets/media.json` identifies and hashes the actual rendered SVGs. The main
workspace uses original synthetic resources through the actual local HTTP client
and Textual UI. The logs screenshot comes from the qualified owned kind rehearsal;
its cluster was deleted. Both are labeled honestly in the page. Rich's external
font declarations are removed; vectors use local monospace fallbacks. These are
actual captures, not reconstructed product mockups.

To capture new media, use a new directory and an available owned-kind screenshot:

```sh
env -u NO_COLOR uv run python -m scripts.capture_site --output /absolute/path/to/new-media --logs-source /absolute/path/to/owned-kind-logs.svg
```

Review the rendered data and inventory before replacing the three corresponding
tracked assets. The producer uses only owned loopback fixtures, never ambient
kubeconfig. The historical source screenshot must be available to reproduce it;
its committed digest alone does not reconstruct missing original evidence.

See [hosting and release gates](../docs/website.md) and
[measured acceptance](../docs/acceptance/initial-website.md).

## Publication ownership

Local preparation #150 is delivered. Final-candidate regeneration, actual public
quickstart and protected GitHub Actions → Cloudflare Pages deployment are #89,
after product features and dedicated qualification. Package/site/DNS publication
needs approval of the concrete result. See [the deployment procedure](../docs/website.md).
