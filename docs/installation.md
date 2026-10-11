# Installation and upgrades

The first prepared public version is **0.1.0**. Channel activation is still
pending: use a trusted checkout or a supplied local candidate now. The PyPI,
Homebrew and GitHub commands below become public installation instructions only
after their artifacts and channels are published and verified.

Choose one installation method. Every method provides the `kuberich` command;
preferences and kubeconfig remain separate from the application installation.

## Python on Linux or macOS

Use CPython **3.12–3.14** and an isolated [uv tool](https://docs.astral.sh/uv/guides/tools/)
or [pipx](https://pipx.pypa.io/stable/installation/) environment. For a supplied
candidate, run outside the source checkout:

```sh
uv tool install --python 3.12 /absolute/path/to/kuberich-0.1.0-py3-none-any.whl
kuberich --version
kuberich config check
```

Alternatively:

```sh
pipx install --python python3.12 /absolute/path/to/kuberich-0.1.0-py3-none-any.whl
```

Use the actual trusted file path. If the manager reports a missing executable
directory on PATH, add the directory it reports through your normal shell setup.
KubeRich does not modify your shell startup files.

After public PyPI activation, the normal installation commands will be:

```sh
uv tool install --python 3.12 kuberich
# Alternative:
pipx install --python python3.12 kuberich
```

These unpinned installs allow normal manager upgrades. A file-path installation
or an exact version constraint does not automatically select future releases;
see the upgrade section before changing installation methods.

## Homebrew on Linux or macOS

The approved channel proposal is the project organization **kuberich**, with
repository `kuberich/homebrew-tap`. Once activated, install with:

```sh
brew install kuberich/tap/kuberich
kuberich --version
```

The initial formula builds from source and declares Python 3.14, kubectl and
libyaml. Homebrew manages these dependencies; a separate Python environment is
unnecessary. A source installation can take several minutes. No public tap or
bottle is currently available. Owned native qualification and later public
channel verification are separate steps.

## Standalone Linux and macOS archives

A supplied standalone candidate includes its own Python runtime. The proposed
GitHub Release contains these four archives and `DOWNLOAD-SHA256SUMS`:

| System | Architecture | Archive |
| --- | --- | --- |
| Linux | x86_64 | `kuberich-0.1.0-linux-x86_64.tar.gz` |
| Linux | ARM64 | `kuberich-0.1.0-linux-arm64.tar.gz` |
| macOS | Intel | `kuberich-0.1.0-macos-x86_64.tar.gz` |
| macOS | Apple Silicon | `kuberich-0.1.0-macos-arm64.tar.gz` |

Linux archives require glibc 2.35 or newer; Alpine/musl and Windows are outside
this release. macOS archives have a measured deployment floor of 14. Native
trials cover macOS 14 ARM and macOS 15 Intel; a physical macOS 14 Intel trial is
not claimed. The archives use ad-hoc signatures; Developer ID notarization is
not claimed.

Compare the selected archive's SHA-256 with its exact line in the supplied
`DOWNLOAD-SHA256SUMS`. On Linux, use `sha256sum ARCHIVE.tar.gz`; on macOS, use
`shasum -a 256 ARCHIVE.tar.gz`. Reject different bytes before extracting.

Extract into a new directory, retaining the complete `kuberich/` tree:

```sh
mkdir kuberich-0.1.0
tar -xzf /absolute/path/to/ARCHIVE.tar.gz -C kuberich-0.1.0
./kuberich-0.1.0/kuberich/kuberich --version
```

Replace `ARCHIVE.tar.gz` with the selected filename. The launcher depends on its
adjacent `_internal` files and notices; copying only the executable is insufficient.
Move the whole directory to your preferred location, then use its absolute
launcher path or create a symlink in a directory already on PATH.

## Qualification scope

The complete source matrix covers Ubuntu 24.04 x86_64 and macOS 26 ARM, each with
CPython 3.12, 3.13 and 3.14. Native archive trials separately cover Ubuntu 22.04
x86_64/ARM64, macOS 14 ARM and macOS 15 Intel. Homebrew trials cover Ubuntu 24.04
x86_64, macOS 14 ARM and macOS 15 Intel with its declared Python dependency.
Exact first-version results are retained with the release candidate; a supported
runtime range does not establish every OS/architecture/terminal combination.

Use an interactive UTF-8 terminal. SSH and tmux transport/restoration have owned
automated trials; physical terminal-emulator, font and clipboard certification
remains separate. See [terminal compatibility](terminal-compatibility.md).

## First launch

Local version/help/config commands need no cluster. For the UI, select a trusted
kubeconfig and an explicitly permitted context/namespace:

```sh
kuberich --kubeconfig /absolute/path/to/kubeconfig --context YOUR_CONTEXT --namespace YOUR_NAMESPACE --readonly
```

Use the actual path and names. The first-launch guide covers `:ctx`, `:ns`, `/`,
pod → container → logs and shell return. Shells, attach, transfers and forwarding
need kubectl on PATH and the corresponding Kubernetes permissions; read-only
mode blocks effectful actions. Provider exec helpers remain external tools.
See [first launch](quickstart.md), [EKS](eks-authentication.md) and
[AKS](aks-authentication.md). Owned helper trials do not certify real clouds.

## Upgrade and uninstall

After channel activation, update an unpinned managed installation with:

```sh
uv tool upgrade kuberich
# Or, for the method originally chosen:
pipx upgrade kuberich
brew upgrade kuberich/tap/kuberich
```

The first public release has no previous public KubeRich version. Its owned
upgrade trials use identified immutable local versions and the manager's actual
upgrade command. Later releases must also qualify the genuine published baseline.
To replace a supplied local wheel, use the same manager with its explicit new
file/install constraint; a reinstall is not proof of a normal channel upgrade.

For an archive update, verify a new archive, extract it into a new version
directory and run its version/first-launch checks before switching your launcher.
Keep the previous verified directory until the replacement works.

Remove the application with the chosen manager:

```sh
uv tool uninstall kuberich
# Alternatives:
pipx uninstall kuberich
brew uninstall kuberich/tap/kuberich
```

For an archive install, remove only its extracted directory and your own symlink.
Preferences, logs and kubeconfig stay intact. Use `kuberich info` before uninstall
to locate your preference/log paths; deleting those files is a separate choice.

## Troubleshooting

| Symptom | Next step |
| --- | --- |
| Command not found | Check the manager's reported executable directory or the complete archive launcher path |
| Unsupported Python | Select Python 3.12–3.14 explicitly; standalone archives include their runtime |
| Executable format/library error | Match OS/architecture, verify the checksum and retain the full directory; check the documented native floor |
| Package/tap unavailable | Use a supplied candidate or source while public activation is pending |
| UI does not open | Use an interactive terminal and run `kuberich config check` |
| kubectl works but KubeRich fails | Compare the exact context, kubeconfig, namespace, helper PATH and provider session; see the connection guides |

Report the version, OS/architecture, installation method and a sanitized error.
Do not include tokens or kubeconfig contents in reports.
