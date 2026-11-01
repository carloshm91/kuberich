# Internal engineering records

This area contains historical implementation reports, acceptance records,
planning data and source inventories. It is excluded from user navigation,
website output and search. These records are not current user instructions or
proof that an unpublished candidate passed release qualification.

- `acceptance/` retains the original acceptance reports, images and CI data.
- `preview-history.md` and `first-preview-before-status.md` retain the previous
  development and checkpoint logs.
- `guide-history/` preserves the exact guides that preceded consolidation, with
  their individual hashes and byte ranges.
- `architecture-history/` preserves the previous architecture log, its section
  hashes and the mapping to current decision records.
- `backlog.json`, `github-issues.json` and `k9s-source-inventory.json` remain
  machine-readable planning and source inputs. GitHub is the live task status.

## Reading an original record

Historical files are listed in `preserved_sources` in
[the documentation inventory](../documentation-plan.json), with its original
source path, exact commit and SHA-256. The repository validator checks both the
current bytes and the corresponding Git blob. It checks active Markdown links
against that recorded source tree; code examples are not active links.

Relative links inside an unchanged historical record describe the original
source path and commit. Use that source snapshot to follow them. Some unchanged
reports predate guide consolidation, so their identical earlier snapshot is
recorded rather than pretending that a retired guide still exists today.

The `relocations` map in the same inventory translates former file locations to
this area's current locations. In particular, the unchanged guide and
architecture source-map JSON files keep their original `archive` values. Apply
that map before opening the archive, using `relocated_source` from
`scripts.documentation_links`. The original source-map bytes stay intact.

## Updating evidence

Keep new verification evidence in its pull request or release assets when
possible. Distinguish failures, supplemental controls and actual qualification.
Never rewrite an original failure into a pass or apply a directory-wide link
exemption. A new historical transfer needs its own source/hash record; any
unregistered Markdown file still receives ordinary current-source link checks.

The three operational JSON inputs remain editable and retain their normal plan,
schema and release checks. Their pre-migration source commit and SHA-256 are
recorded separately in `operational_sources`. The validator proves that original
Git blob without pinning the current working bytes or creating duplicate snapshots.

Current contributor instructions remain in
[CONTRIBUTING.md](../../CONTRIBUTING.md), the
[architecture overview](../architecture.md),
[quality policy](../quality.md) and [release procedure](../releases.md).
