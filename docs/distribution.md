# Installation and platform support

## Release channels

| Channel | First required release | Method |
| --- | --- | --- |
| PyPI | 0.1.0 (#89) | Wheel and source distribution; isolated installation using uv or pipx |
| Homebrew project tap | 0.1.0 (#89) | Python formula using virtualenv_install_with_resources and hashed resources |
| GitHub standalone executables | 0.1.0 (#89), after D05 qualification | Platform-built PyInstaller bundles with checksums and provenance |

The CLI and import package are named kuberich. PyPI name availability must be
rechecked when the pending publisher is configured; a 404 lookup is not ownership.
If the name cannot be acquired, resolve the naming issue before any public
release instead of silently changing the advertised package.

The private preview was previously named Kubetrol. Checkout upgrades use
`uv sync --locked --group dev`, then `uv run kuberich`; the local directory name
does not determine the CLI name. A pre-existing isolated `uv tool`/`pipx`
installation of the old distribution must be uninstalled before installing
the new local candidate, because both expose the retained `kubetrol` alias.
Uninstalling a tool does not delete its preference files. Public installation
still waits for the qualified release; see [preference compatibility](configuration.md).

The planned Homebrew command after publication is:

```sh
brew install kuberich/tap/kuberich
```

The planned Python commands after publication are:

```sh
uv tool install kuberich
# Alternative:
pipx install kuberich
```

These commands are intentionally documented as future release contracts. The
README switches to active installation instructions only after verification.

## Development artifacts: D01 #34

The build backend selects Python modules, Textual styles and `py.typed` explicitly.
The wheel adds runtime metadata, its CLI entry point, Apache-2.0 license and attribution NOTICE. The source
distribution adds `pyproject.toml`, README, changelog, license and Hatchling's
required `.gitignore`. Tests, development scripts, `uv.lock`, caches, temporary
files and undeclared credential/configuration files are excluded. The full test
suite and development lock remain in the Git repository.

Build and verify locally from the checkout:

```sh
uv sync --locked --group dev
uv build
uv run pytest tests/packaging
```

The required checks compare every packaged path and payload, validate version,
Python requirements, dependencies, license, URLs and console metadata, and
rebuild a wheel from the source archive with identical file contents. Synthetic
private-file traps verify exclusion independently of the developer's Git ignore
configuration.

Wheel and source archives each receive actual `uv tool` and pip-backed `pipx`
installations. Each test owns its installation, binary, cache, configuration and
log directories; it neither changes the user's managed tools nor edits shell
startup files. The exposed command runs from PATH outside the checkout, and an
isolated interpreter verifies the installed module origin and bundled styles.
Checks cover help/version, missing preferences, diagnostics, non-TTY refusal,
actual PTY resource navigation against an owned loopback API, wheel-installed
embedded shells, terminal restoration and uninstall cleanup.

`pipx` is a locked development-test dependency, not a runtime requirement.
Both managers use the explicit interpreter of their Linux/macOS matrix job.
The [D01 acceptance report](acceptance/distribution-artifacts.md) records measured
results and unavailable platform checks. Local artifact installation does not
publish packages or create a release.

## Supported targets

Source and Homebrew installations initially target Linux and macOS on x86_64
and arm64, with CPython 3.12, 3.13, and 3.14. The release gate must qualify each
advertised combination or explicitly narrow the published support matrix before
release. macOS 14+ is the initial qualification baseline.

Standalone release targets are Linux x86_64/arm64 with glibc 2.35+ and macOS
x86_64/arm64 on macOS 14+. Build separately for each target; PyInstaller is not
a universal cross-compiler. Alpine/musl and Windows bundles are not promised by
these milestones. Retain build provenance and test on clean target environments.

The Python runtime is included in standalone bundles. kubectl and cloud
credential executables remain external dependencies where the selected feature
or kubeconfig requires them. The application must detect missing executables
and give actionable instructions; basic API browsing must still work without
kubectl. The Homebrew formula declares its Kubernetes CLI dependency.

## Homebrew implementation

Prepare the dedicated kuberich/homebrew-tap scaffold in the distribution task.
Creating the public tap and activating the channel require concrete approval in
D10 #89. Install from the released source artifact with a recorded SHA-256 and
explicit dependency resources using Homebrew's Python formula conventions.
Run brew audit, formula tests, clean installation, version/help checks, and an
upgrade smoke test on the advertised platforms. Update by PR after the upstream
release is published; do not publish a formula pointing at unreleased main.

## Upgrade and uninstall contract

Fresh wheel/sdist uv-tool/pipx installs above do not prove upgrades. D04 #40 and
D06 #51 must retain actual local baseline-to-candidate update evidence for every
promised manager, including an explicitly identified immutable local baseline
for first 0.1.0. There is no previous public KubeRich release to claim. Later
releases must exercise the actual previous supported published artifact, with
public channel checks under #89.

After channel activation, an unpinned published installation uses its actual
manager update/uninstall path:

```sh
uv tool upgrade kuberich
uv tool uninstall kuberich
# Alternative manager:
pipx upgrade kuberich
pipx uninstall kuberich
# Approved project tap only:
brew upgrade kuberich/tap/kuberich
brew uninstall kuberich/tap/kuberich
```

These are future public-channel contracts, not completed update trials. Preserve
the original source/version constraints: `uv tool upgrade` respects install-time
constraints, so an exact version or file-path install cannot be assumed to select
a new release. D04/D06 must use a real supported channel, such as an owned
loopback index serving two immutable built artifacts, without deleting/reinstalling
the environment or overwriting the old artifact. Record old/new source/version/
digests, manager/interpreter/OS and exact commands. Verify installed CLI/module
origin/assets, unchanged preference and caller kubeconfig bytes, owned-API/PTY
behavior after update, and uninstall cleanup. A source `uv sync`, fresh reinstall,
generated note preview or mocked updater is not manager-upgrade evidence.
Standalone updates likewise need both real immutable bundles and post-replacement
behavior while preserving user configuration; no unqualified platform is promised.

## Release verification

- Install the built wheel and sdist independently in fresh environments.
- Verify version, help, packaged Textual styles/assets, and missing-config errors.
- Exercise the basic browser/logs/exec flow against a disposable cluster.
- Check actual local baseline-to-candidate updates; after first activation also
  use the actual previous supported published artifact.
- Verify checksums, dependency inventory, and artifact provenance.
- Publish only tested artifacts; retain known limitations and support evidence.

The repository starts without a PyPI publisher, Homebrew tap, or released
application. Those are explicit prerequisite tasks, not hidden assumptions.

## Sources

- [Homebrew Python formula conventions](https://docs.brew.sh/Python-for-Formula-Authors)
- [uv tools](https://docs.astral.sh/uv/guides/tools/)
- [PyInstaller operating model](https://pyinstaller.org/en/stable/operating-mode.html)

## Extended channels

v0.5.0 tracks Windows/PowerShell, shell completion, an OCI terminal image and
Linux/BSD/macOS package recipes. Each channel needs its own installation and
upgrade evidence. Registry submissions and third-party integrations have external
maintainers; acceptance is not guaranteed by creating a recipe. See D12-D14 in
[the backlog](backlog.md). No untested OS is advertised as supported.
