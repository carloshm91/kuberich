# Task guide consolidation acceptance

## Scope and source

Issue [W06 #224](https://github.com/carloshm91/kuberich/issues/224) consolidates
the task guides and generated lookup pages. This delivery normally merges protected
main `c2dfc85486621ecb755d5ab0b19b896e25475064` into the prepared documentation
branch. Its application source, quality workflow, packaging inputs and runtime
validators are preserved from that parent. Non-documentation tests retain that
parent's behavior; the stage-catalog test adds the corrected plan argv assertion.

The narrow qualification correction invokes the existing planning validator as
`uv run python -m scripts.validate_plan`, matching Repository checks. The existing
private-access and actual startup stages, strict type union, complete suite,
coverage gates, deadlines, failure retention and process ownership remain intact.

## Acceptance mapping

- The navigation has 15 authored task guides and four generated references:
  19 canonical content pages plus the index, 20 total. Every page
  stays within the 250-line budget and follows `docs/STYLE.md`.
- Task guides cover installation, quick start, everyday workflow, navigation,
  logs, shells/attach, forwarding, files, editing, workload operations, contexts
  and authentication, configuration/themes, plugins and troubleshooting.
- CLI flags and local/in-app commands, keys, resource declarations, preference
  fields/defaults and public capability summaries come from the selected checkout.
  Four canonical `docs/*.md` snapshots are checked for declaration drift.
- Retired routes keep their old heading aliases. Redirect destinations omit
  fragments so browsers can retain an incoming fragment; internal links resolve
  directly to the active headings on both documentation surfaces.
- All 30 superseded guides retain their exact bytes, registered source identities
  and checksums outside public navigation. The pinned plugin census still checks
  its archived source range and all 50 records/108 command classifications.
- Examples use fictional names. User guides omit issue codes, CI IDs and delivery
  evidence; generated references omit internal tracking fields.

## Current local verification

The integrated candidate passed **174 checks in 75.47 seconds**: all guide,
Markdown-link, navigation, site and plugin-example cases, plus the existing
qualification stage-catalog contract. They cover declaration/schema drift,
250-line budgets, old routes/fragments, broken/unsafe links, exact archived bytes,
fictional examples and removal of internal tracking text from both site surfaces.

```sh
uv run pytest -q tests/quality/test_user_guides.py tests/quality/test_documentation_links.py tests/quality/test_documentation_structure.py tests/quality/test_site.py tests/contract/test_plugin_examples.py tests/quality/test_qualification.py::test_default_command_runs_all_layers_once_with_existing_independent_coverage_gates
```

The current workflow's complete strict type target union passed over **234 source
files**. The seven documentation/build/schema scripts also passed strict typing.
Ruff, formatting over 806 files, the private-access audit and generated-reference
comparison passed. The real planning/Markdown validator passed. Final static
build and link/source-receipt checks use both local surfaces:

```sh
uv run python -m scripts.site_reference
uv run python -m scripts.validate_plan
uv run python -m scripts.build_site --output artifacts/issue224/c2-delivery/site
uv run python -m scripts.check_site --output artifacts/issue224/c2-delivery/site
```

The original focused output/XML, type commands/results and final build/check
receipts are retained under `artifacts/issue224/c2-delivery/`. Application source
and current runtime/qualification behavior are compared directly with the
protected parent; the qualification command and its assertion are the only
intentional exceptions outside the documentation implementation.

## Limits

Earlier documentation receipts are historical evidence, including the prepared
127-case run and its three final identity checks. They do not qualify this parent
integration. Current application coverage is not newly measured by these
documentation checks; no executable application lines change.

Fresh required PR checks still qualify the delivered head. This local pass does
not claim browser, native/platform, provider, performance or release qualification.
Recorded media keeps its previous source identity; no new media was captured.
Architecture, acceptance-history and contribution migrations remain separate work.
No website, package, tag, release, DNS or visibility publication is included.
