# Themes and local appearance

These controls are implemented in the source checkout for the next release.
The published 0.1.0 package supports its configured built-in theme; it does not
include the theme picker, custom/context palettes, inversion or update notices.

Open `:themes` in the workspace, or launch `kuberich --command themes`.
The standalone picker reads local configuration without opening a Kubernetes
connection or executing authentication helpers. Arrow keys select a theme and
preview it immediately; Enter also previews. The Selected column and status text
identify the selection independently of its color.

- **Global** saves the selected global theme and the update-check checkbox.
- **Context** saves the theme for the context named in the dialog. It leaves the
  global theme and global update-check preference unchanged.
- **Back / Escape** restores the effective saved preferences. A preview or changed
  checkbox alone never writes a file or enables an external request.

A requested save finishes before the dialog can close. A save already requested
also finishes during graceful application exit. This is local configuration;
`--readonly` continues to allow appearance changes while blocking cluster writes.
Saving retains unrelated preferences and unknown fields. Runtime `--readonly`,
`--refresh`, log overrides and environment overrides are not written into the file.
A competing preference change is refused; restart to load it before saving.
Legacy Kubetrol paths require an explicit `kuberich config migrate` first.

## Which theme wins

The order is application environment (`KUBERICH_THEME`, then its legacy
`KUBETROL_THEME` alias), a matching context preference, the global `theme`, then
the built-in `k9s` default. An environment or context preference can therefore
continue to determine the effective theme after a global save; the dialog reports
that effective name. Context changes apply the corresponding theme immediately.

```sh
KUBERICH_THEME=textual-dark kuberich
kuberich --context demo-lab --command themes
kuberich --invert --command themes
```

`demo-lab` is fictional; choose an intended local kubeconfig context. `--invert`
reverses this session's resolved RGB palette and light/dark mode, repairing text
and accent contrast where needed. ANSI defaults resolve to explicit light/dark
colors for the inverted session. It does not change the terminal's own palette
or persist the modifier. The `kuberich-mono` theme provides black/white colors;
status words, selection markers and normal navigation remain available in narrow
or low-color terminals.

## Custom palettes

Add an `appearance` section to the preference file selected by `--config` or
shown by `kuberich info`. The root preference schema remains version 1; this
additive section also declares its own version. Existing files need no rewrite.

```yaml
schema_version: 1
theme: k9s
appearance:
  schema_version: 1
  check_updates: false
  themes:
    ocean:
      primary: '#5fd7ff'
      foreground: '#ffffff'
      background: '#000000'
      dark: true
  contexts:
    demo-lab: ocean
```

Custom names use 1–64 ASCII letters, digits, underscores or hyphens, beginning
with a letter. They cannot replace built-in names. A palette requires `primary`,
`foreground` and `background`; optional colors are `secondary`, `accent`,
`surface`, `panel`, `warning`, `error` and `success`. Colors are quoted six-digit
hexadecimal values. There is no executable CSS or Python in a palette.

Foreground contrast must be at least 4.5:1 against background, surface and panel;
primary/accent/status colors need 3:1 against the background. These numeric checks
and actual terminal tests complement readable state words; they do not certify
every terminal palette, font or color quantization. Limits are 32 custom themes,
128 context preferences and the existing 64 KiB total preference-file bound.
Framework CSS variables and icon preferences are not supported.

Set `background`, `surface` or `panel` to `'default'` to use the terminal's own
background, for example a transparent or blurred terminal window. Contrast checks
skip those colors because KubeRich cannot know the terminal's background. Pick a
`foreground` that is readable on it.

```yaml
appearance:
  themes:
    glass:
      primary: '#5fd7ff'
      foreground: '#ffffff'
      background: 'default'
      dark: true
```

Saved changes apply while KubeRich runs; see
[changing preferences](configuration.md#changing-preferences-while-kuberich-runs).

### Full resource titles

Set `appearance.full_gvr_titles: true` to show the API version in the title of
every resource view, for example `pods · v1`. Custom resources always show it.

An unavailable selection falls back to `k9s` with a warning. An invalid appearance
section uses working defaults, retains the original file and disables saves until
it is corrected. Run `kuberich config check` for an actionable validation error.
Loading, previewing and checking never repair or overwrite a file silently.

## About and optional version notices

`:about` or `kuberich --command about` shows original KubeRich branding, the
installed version, Apache-2.0 information and the version-check state. The content
scrolls and Back remains reachable in a 40×12 terminal.

Version checks are **off by default**. Enable the checkbox and choose Global,
or set `appearance.check_updates: true` explicitly. Context saves do not change
this application-wide option. Checks run asynchronously on terminal launch and
when requested preferences enable them; ordinary `info`, help, version and
`config check` remain offline operations.

The checker reads the public GitHub stable-release endpoint without credentials,
cookies or inherited proxy configuration. A request has a three-second deadline
and a 64 KiB response bound; redirects, unavailable/private releases, rate limits,
malformed data and prerelease announcements do not produce an update notice.
An installed prerelease/development build can still see a newer stable release.
The notice contains only a validated newer version and its canonical release URL.

Verified results may be reused for 24 hours from a private local cache. About
identifies cached results. An expired/corrupt cache, failed request or unwritable
cache cannot prevent startup. No package is downloaded, installed or executed;
follow the release notes and [installation guide](installation.md) when upgrading.
