# Architecture overview and decision records

## Scope and source

Issue [W07 #225](https://github.com/carloshm91/kuberich/issues/225) replaces the
architecture log with a short contributor overview, individual decisions and an
exact historical archive. This integration takes protected parent
`38bb0f9156999c5e2eae1bf6c3ed55b4da27101d` as the application, runtime,
qualification, packaging and task-guide baseline. It changes no application code,
workflow, dependency, publication setting or resource operation.

The overview names the actual layer modules, shows dependency/data/replacement
flow in three Mermaid diagrams, and explains concurrency, identity, cleanup and
security. It stays below the issue's 300-line maximum. Existing composition and
kubeconfig records retain their own status and filenames.

## Historical source

The migration adds 31 numbered decisions, their template and index. The archive
preserves all **79,512 bytes**, **1,237 lines** and **44 sections** of
`625086db1a75aab10ec28fe4d6440f7fb1d32849:docs/architecture.md`.
Its SHA-256 remains
`d5a8b04b2ec5f55cf703d9a9bc322d190425bd27828c69993784ba2c3fefe162`.
The original preamble, section ranges, hashes and destinations remain recorded;
no later decision or measurement is attributed to that earlier source.

The archive stays outside public user navigation. Old heading destinations are
checked against the actual recorded map. Current-note sections distinguish later
Basic credential handling, CLI header visibility, phase gates and failure
retention from the migrated rationale. They do not requalify historical evidence.

## Verification commands

Run the existing architecture, document-disposition and original-link controls,
including the pinned plugin census. Source-generated references and both local
site surfaces retain the task-guide contract from the protected parent.

```sh
uv run python -m pytest tests/quality/test_architecture_docs.py tests/quality/test_documentation_structure.py tests/quality/test_documentation_links.py tests/contract/test_plugin_examples.py::test_census_covers_every_pinned_source_and_all_workflows_without_bundling_scripts tests/quality/test_user_guides.py::test_every_user_page_fits_budget_and_checked_reference_is_current
uv run python -m scripts.validate_plan
uv run python -m scripts.build_site --output artifacts/issue225/site
uv run python -m scripts.check_site --output artifacts/issue225/site
```

## Measured local checks

On signed integration `f285c3248897e5df8e6473e554791e226f861265`, the 74 existing
architecture/disposition/link/plugin-census checks above passed in 14.074 seconds,
with no failures, errors or skips. All 927 tracked inputs stayed unchanged during
the ten recorded local commands, and every owned group was drained and reaped.
The current workflow's strict union passed over 234 source files; the seven
site/documentation scripts also passed strict typing. Ruff, formatting over 843
files, the public-boundary audit, generated-reference comparison, module planning
validator and whitespace checks passed. The planning validator checked 808 local
Markdown links.

This result belongs to that integration source. The following evidence-only
update adds these observations; it does not change its test/tool or application
bytes. Final local site generation and link/source checks use the final checkout.
Local command logs, XML, actual source comparisons and build/check receipts are
retained under the issue's ignored artifact directory. Required PR checks still
qualify the eventual delivered head; local documentation checks establish no new
application coverage, cloud-provider, native or performance qualification.
No cluster, installed application, browser/media campaign, website, package,
release, tag, DNS or visibility publication is part of this migration.

## Required-check synchronization correction

The original [Python 3.14 part failure](https://github.com/carloshm91/kuberich/actions/runs/41435801610/job/125247007601)
on source `17196855` retained 2,039 passing cases, one failure and one explicit
skip. The plugin-job test saw `Running · exit 0` with the expected literal output,
then checked the final visible status before its scheduled repaint.

A single controlled real-child/Pilot observation on unchanged `17196855` held only
the public process-cleanup boundary. The existing output predicate became true
while the model and rendered result were still Running. After cleanup was released,
the existing timer published Succeeded for the same opened job/widget without
another Enter or forced final refresh. Literal markup stayed literal; process,
client and renderer cleanup completed. This demonstrates a sufficient ordering,
not unique retrospective proof of the hosted scheduler's sequence.

Only that existing test's wait predicate now requires the final rendered status,
exit code and output marker together. The original job wait, model/result checks,
visible-result assertion, literal child output and cleanup assertion remain, as
does the five-second helper. Production status still becomes final after cleanup.
The original failed run and artifact 13135944907 are retained; no unchanged retry,
product lifecycle change, deadline increase or assertion removal is involved.
The earlier 74 documentation checks remain tied to their recorded source.
