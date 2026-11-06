# Install and upgrade

Version 0.3.0 is available from PyPI, GitHub Releases and the project Homebrew
tap, with prebuilt Homebrew bottles for the targets below.

Install the `kuberich` command on Linux or macOS. Choose one method so that
upgrades and removal use the same package manager. Preferences and kubeconfig
stay separate from the application.

## Homebrew

```sh
brew install kuberich/tap/kuberich
kuberich --version
```

The project tap is `kuberich/homebrew-tap`. Homebrew installs Python, kubectl, and
libyaml as dependencies. It pours a compatible prebuilt KubeRich bottle when
one is available; otherwise it builds KubeRich from source.

The 0.3.0 bottle targets are macOS 15 Apple Silicon (`arm64_sequoia`), macOS
Intel (`sequoia`) and Linux x86_64 (`x86_64_linux`). Published 0.2.0 Sonoma
bottles keep their existing files. When no compatible bottle exists, Homebrew
builds from source; dependencies may also need source builds on older systems.

A KubeRich bottle still needs its Homebrew runtime dependencies. Homebrew's
[support policy](https://docs.brew.sh/Support-Tiers#tier-3) lists Intel macOS as
Tier 3. On affected configurations, missing core bottles can make Python,
kubectl or libyaml build from source and take substantial time. For an alternative,
use the [Python tools](#python-tools) method below with a
[uv-managed Python](https://docs.astral.sh/uv/guides/install-python/), or choose a
[standalone archive](#standalone-archives), which includes its Python runtime.
Delegated operations still need kubectl as documented below.

## Python tools

Use CPython 3.12–3.14 and an isolated tool environment:

```sh
uv tool install --python 3.12 kuberich
kuberich --version
```

Alternatively, use `pipx install --python python3.12 kuberich`. If the command is
missing afterward, add the executable directory reported by your tool manager
to PATH through your normal shell setup.

To install a trusted local wheel, replace `kuberich` in the install command with
its absolute file path. A file-path install or an exact version pin does not
select future versions automatically.

## Standalone archives

[GitHub Releases](https://github.com/carloshm91/kuberich/releases) provides archives
with a Python runtime included:

| Platform | Architecture | Filename suffix |
| --- | --- | --- |
| Linux | x86_64 | `linux-x86_64.tar.gz` |
| Linux | ARM64 | `linux-arm64.tar.gz` |
| macOS | Intel | `macos-x86_64.tar.gz` |
| macOS | Apple Silicon | `macos-arm64.tar.gz` |

Select an archive from the same release as its `DOWNLOAD-SHA256SUMS` file. Linux
archives require glibc 2.35 or newer. macOS archives require macOS 14 or newer;
macOS 14 Intel has no physical-machine trial. Alpine/musl and Windows are outside
the current archive support. macOS archives use ad-hoc signatures and are not
Developer ID notarized.

1. Compare the archive's SHA-256 with its line in `DOWNLOAD-SHA256SUMS`. Use
   `sha256sum FILE` on Linux or `shasum -a 256 FILE` on macOS. Reject a mismatch.
2. Extract into a new directory. Keep the complete `kuberich/` tree.
3. Run the launcher from that directory and check its version.

For example, with the published 0.3.0 Linux x86_64 archive:

```sh
mkdir kuberich-0.3.0
tar -xzf kuberich-0.3.0-linux-x86_64.tar.gz -C kuberich-0.3.0
./kuberich-0.3.0/kuberich/kuberich --version
```

The `_internal` directory and notices must stay beside the launcher. Move the
whole directory, then use its absolute launcher path or create your own symlink
in a directory on PATH. Shells, attach, file transfers, and port forwarding also
need kubectl on PATH.

## First launch

Use an interactive UTF-8 terminal:

```sh
kuberich config check
kuberich --context demo-lab --namespace demo-apps --readonly
```

Replace the fictional names with your intended scope. To select a specific
Kubernetes file, add `--kubeconfig /absolute/path/to/kubeconfig`.
`--config` instead selects KubeRich preferences. See [quick start](quickstart.md).

## Upgrade

Use the command for your installation method:

```sh
brew upgrade kuberich/tap/kuberich
uv tool upgrade kuberich
pipx upgrade kuberich
```

Run only the applicable command. Upgrades keep preferences and kubeconfig.
For a local-wheel install, explicitly install the new trusted wheel using the
same manager. For an archive, verify and extract a new version into a separate
directory, check its version, then switch your launcher. Keep the previous
archive directory until the replacement works.

Homebrew keeps old versions until `brew cleanup` removes them; it has no general
downgrade command. An exact Python version pin needs an explicit version change.

### Upcoming 0.4 command migration

The prepared 0.4 source removes the deprecated `kubetrol` command. Published
channels still deliver 0.3. Use `kuberich` in scripts and launchers now.

When 0.4 becomes available, an unpinned pipx installation needs a one-time
`pipx reinstall kuberich` directly from 0.3, before plain `pipx upgrade`.
The reinstall removes the old command links while selecting the new version.
Plain upgrade can leave a dangling `kubetrol` link after removing its target.

If the recorded pipx requirement explicitly pins 0.3, reinstall preserves that
constraint. Deliberately replace it through the same manager after publication:

```sh
pipx uninstall kuberich
pipx install --python python3.12 kuberich==0.4.0
```

These operations keep application preferences, diagnostic logs and kubeconfig.
Uv and Homebrew retain their normal upgrade commands; explicit version pins
still need deliberate replacement. The [prepared notes](release-notes/0.4.0.md)
describe the remaining compatibility changes.

## Remove the application

Use `brew uninstall kuberich/tap/kuberich`, `uv tool uninstall kuberich`, or
`pipx uninstall kuberich`, matching your install method. For an archive, remove
its extracted directory and your own symlink.

Removal leaves preferences, diagnostic logs, and kubeconfig intact. Run
`kuberich info` beforehand if you want to locate preference and log files.

If installation fails, check the architecture, Python version, package index,
PATH, and archive checksum. See [troubleshooting](troubleshooting.md) before
reporting a sanitized error with your version and installation method.
