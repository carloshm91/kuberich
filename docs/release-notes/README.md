# Authored release notes

Ordinary merges update Unreleased. A public release PR adds
`docs/release-notes/X.Y.Z.md` (or `X.Y.ZrcN.md`) and the matching source/lock version.
Start with `# KubeRich X.Y.Z`, then provide these nonempty sections:

- `## Features`: actual user behavior and issue links.
- `## Fixes`: concrete corrected behavior.
- `## Compatibility and migrations`: supported versions, breaking changes and
  explicit preference/configuration migrations, or a clear no-migration statement.
- `## Installation`: exact commands for actually qualified channels/platforms.
- `## Upgrade and uninstall`: tested baseline, commands, selection constraints and
  preference/configuration preservation; first release has no prior public version.
- `## Known limits`: unresolved scope, provider/native evidence and unavailable channels.

Use bounded UTF-8 Markdown without terminal controls. The authored file must be
a regular Git blob at the exact candidate commit, with matching working bytes and
no symlinked note directories. Each authored/optional generated part is limited
to 32 KiB. Public preparation freezes body/source/version/tag identity and digests
into `release.json` and `release-notes.md`; bundle checksums cover the frozen file.
This preparation neither creates a tag nor publishes a release.

Authored notes alone are a complete supported path: leave optional
`notes_preview` empty on the approved release-workflow dispatch. A local public
candidate can likewise omit the preview:

```sh
uv run python -m scripts.release prepare --source qualified --bundle release-candidate --commit "$RELEASE_COMMIT" --version "$RELEASE_VERSION"
```

The normal release workflow additionally requires real main/six-native/security/
phase readiness and protected owner review. Local development `--candidate`
bundles need no public notes and cannot publish.

## Optional owner-reviewed generated preview

In a separately authorized owner context, GitHub can generate a nonpersisted PR
summary. This endpoint requires Contents write; the read-only validation job does
not call it or receive extra permissions. Before candidate preparation, an owner
may run:

```sh
gh api --method POST repos/carloshm91/kuberich/releases/generate-notes -f tag_name="$RELEASE_TAG" -f target_commitish="$RELEASE_COMMIT" > generated-notes.json
```

For later releases, supply `-f previous_tag_name=ACTUAL_PREVIOUS_TAG` to identify
the reviewed range; do not invent a previous public tag for first 0.1.0. Review
the returned body, then put that exact text in a JSON file with this schema:

```json
{
  "schema_version": 1,
  "commit": "EXACT_40_CHARACTER_SOURCE_SHA",
  "version": "0.1.0",
  "tag": "v0.1.0",
  "body": "Exact owner-reviewed generated Markdown"
}
```

The example SHA placeholder must be replaced by the qualified commit. Use the
canonical RC package/tag spellings when preparing an RC. Submit this exact JSON
as workflow-dispatch `notes_preview`, or use the supported local CLI path:

```sh
uv run python -m scripts.release prepare --source qualified --bundle release-candidate --commit "$RELEASE_COMMIT" --version "$RELEASE_VERSION" --notes-preview reviewed-preview.json
uv run python -m scripts.release verify --bundle release-candidate --commit "$RELEASE_COMMIT" --version "$RELEASE_VERSION" --notes-preview reviewed-preview.json
```

Preparation combines authored text, two newlines and the reviewed preview. The
publisher sends this exact body with automatic generation disabled. Retried
candidates compare committed authored bytes, the supplied preview and frozen
body; existing remote release identity/body must match before uploads. No retry
regenerates notes, and no completed release is edited to accept changed content.

Source: [GitHub generated-notes API](https://docs.github.com/en/rest/releases/releases#generate-release-notes-content-for-a-release).
