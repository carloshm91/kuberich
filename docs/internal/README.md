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

A `-0.3` snapshot keeps later additions separately when an earlier report
or metadata file has already been preserved. Both byte-exact versions remain;
the relocation map selects the 0.3 engineering-phase version for current contributor links
and guide-source readers. This does not turn a source checkpoint into release
qualification or claim that a feature-branch blob is protected-main evidence.
The suffix identifies an engineering phase, not a published or qualified release.

## Source-history setup

Use a full-history clone. Before documentation link/history validation or the
local qualifier, fetch these existing PR histories once:

```sh
git fetch --no-tags origin refs/pull/277/head refs/pull/290/head
```

PR 277 retains the reviewed prerequisite ancestry for the three `1875994d5c`
records. PR 290 retains the internal-evidence source ancestry, including the
`aad1a0b2` and `dd0a67ee` origins. Their exact receipt identities remain unchanged;
fetching a source does not turn a feature-branch origin into protected-main proof.
CI performs this bounded setup before Repository plan validation and Quality
test shards. Current-only site builds, release-byte checks and installers do not
need these historical blobs. Ordinary Markdown validation never fetches from the
network: unavailable or different original objects still fail validation.

## Current maintained records

[Development checkpoint](first-preview-current.md),
[task-guide acceptance](acceptance/task-guides.md) and
[architecture acceptance](acceptance/architecture-overview.md) carry current
protected-parent facts and later verification. They receive ordinary current-source
Markdown link checks. The frozen `first-preview-0.3.md` remains its original
unprotected prepared snapshot; it is not the maintained checkpoint.

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
