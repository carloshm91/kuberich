# Initial landing page and launch documentation

#150 delivered local preparation of the initial static product website. The proposed public
addresses are **kuberich.com** and **docs.kuberich.com**; the maintainer confirmed
buying the domain. Neither address is claimed to host this site yet.
Repository visibility, hosting and DNS remain unchanged by this implementation.

The landing page introduces the actual workspace, captured local UI, 15 standard
resource families, logs, embedded exec, forwarding and guarded changes. It leads
to a read-only first launch. Sixteen initial guides reuse the repository sources
for installation, navigation, configuration, inspection, logs, shells, forwarding,
editing/workloads and EKS/AKS prerequisites. Current public distribution is absent;
the page states that directly rather than supplying invented install/download links.

## Local reviewable result

```sh
uv sync --locked --group dev
uv run python -m scripts.build_site
uv run python -m scripts.check_site
uv run python -m http.server 8715 --bind 127.0.0.1 --directory artifacts/site/www
```

Open `http://127.0.0.1:8715/` on that machine. Initial docs live under `/docs/`.
`artifacts/site/docs` is also built for a separate docs host. Both trees are plain
HTML/CSS/JS/SVG; the optional script only copies examples. There is no server-side
application, Kubernetes access, analytics or external asset dependency.
Build hashes, actual local browser checks and limits appear in
[acceptance evidence](acceptance/initial-website.md). Reproduction/tool/media
instructions are in [website/README](../website/README.md).

## Proposed hosting: Cloudflare Pages

Use two proposed Direct Upload projects: `kuberich-site` for
`artifacts/site/www` and `kuberich-docs` for `artifacts/site/docs`. GitHub Actions
will deploy the reviewed prebuilt directories with Wrangler after feature and
final release qualification. Direct Upload supports this CI workflow;
see [Cloudflare's GitHub Actions procedure](https://developers.cloudflare.com/pages/how-to/use-direct-upload-with-continuous-integration/).
Project names are proposals, not reserved resources. No project, deployment,
credential or DNS record is created by #154.

Prepare a protected maintainer-reviewed deployment environment, a pinned Wrangler
version/action, `CLOUDFLARE_ACCOUNT_ID` and a limited Pages Edit API token held in
that environment's secrets. Ordinary/fork PRs build/check only and cannot deploy
production. Deploy the immutable checked site artifact rather than rebuilding
inside the publishing job. Record the source commit, application candidate, build
manifest and provider deployment IDs together. Implement and verify this concrete
workflow in #89; an empty placeholder workflow does not qualify deployment.

Before an approved deployment:

1. Freeze and qualify the exact release candidate through #89. Regenerate the
   guides and installed version from that source. Replace preview availability
   text only with actual verified publication/install results; remove noindex
   only as part of the separately approved public launch.
2. Rebuild/check/browser-verify the exact website bytes, retain the manifest,
   screenshots and artifact digests, and obtain explicit website/visibility/DNS
   approval from the maintainer for the concrete result.
3. After approval, create the two proposed Direct Upload projects and dispatch
   the protected GitHub Actions job to deploy each exact output directory. Even provider preview URLs are a publication step.
   Record the actual deployment/project IDs and URL-to-manifest association.
4. Associate kuberich.com with the landing project and docs.kuberich.com with the
   docs project in Pages before adding DNS records. For the apex, Pages requires
   a Cloudflare zone and delegation to its nameservers. A separate docs subdomain
   can use a CNAME to the actual docs project's pages.dev address. Preserve all
   existing records during any approved delegation. These provider requirements
   are documented in [custom domains](https://developers.cloudflare.com/pages/configuration/custom-domains/).
5. Wait for active custom domains/certificates, then verify HTTPS, both homepages,
   local assets, direct guide URLs, 404 behavior, redirects and the `_headers`
   policy at the actual hosts. The browser rehearsal serves the declared headers;
   that does not establish provider enforcement or successful TLS provisioning.
6. Record actual publication and public-install verification under #89. #150
   closed its local preparation scope; its final-candidate quickstart and public
   acceptance moved to #89. Expanded/versioned docs remain #90/#91.

No DNS records are precomputed from a guessed project URL. No registrar transfer
is needed just to use a separately approved DNS provider.

## Deployment and rollback

Keep the immutable build directory, its manifest, browser report, deployment ID
and associated application candidate for each deployment. Prepare the next build
locally and verify it before any new upload. If an approved production deployment
is wrong, select the recorded last known-good production deployment using Pages'
[rollback control](https://developers.cloudflare.com/pages/configuration/rollbacks/).
Then verify both hosts against that manifest. A source fix receives a new build
and deployment; it does not rewrite the prior evidence. Preview deployments need
an approved production deployment before they can serve as a rollback target.

These are a concrete proposed procedure, not claims that HTTPS, public package
channels, provider accounts or deployment recovery have been exercised.
