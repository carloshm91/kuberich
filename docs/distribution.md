# Installation and platform support

## Release channels

| Channel | First required release | Method |
| --- | --- | --- |
| PyPI | 0.1.0 (#89) | Wheel and source distribution; isolated installation using uv or pipx |
| Homebrew project tap | 0.1.0 (#89) | Python formula using virtualenv_install_with_resources and hashed resources |
| GitHub standalone executables | 0.1.0 (#89), after D05 qualification | Platform-built PyInstaller bundles with checksums and provenance |

The CLI and import package are named kuberich. Actual TestPyPI and PyPI Trusted
Publishing uploads established the first release in the owner-configured projects.
Later releases retain those project identities and immutable file checks.

The private preview was previously named Kubetrol. Checkout upgrades use
`uv sync --locked --group dev`, then `uv run kuberich`; the local directory name
does not determine the CLI name. A pre-existing isolated `uv tool`/`pipx`
installation of the old distribution must be uninstalled before installing
the new local candidate, because both expose the retained `kubetrol` alias.
Uninstalling a tool does not delete its preference files. See [preference compatibility](configuration.md) before changing installations.

The published Homebrew command is:

```sh
brew install kuberich/tap/kuberich
```

The public PyPI commands are:

```sh
uv tool install kuberich
# Alternative:
pipx install kuberich
```

Version 0.1.0 is published and verified. See [installation](installation.md) for
platform scope and the [release](https://github.com/carloshm91/kuberich/releases/tag/v0.1.0)
for four native archives, checksums and provenance.

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

The six source qualification environments are Ubuntu 24.04 x86_64 and macOS 26
ARM, each on CPython 3.12, 3.13 and 3.14. Native Homebrew source trials cover
Ubuntu 24.04 x86_64, macOS 14 ARM and macOS 15 Intel with formula Python 3.14.
Broader source/architecture combinations and physical macOS 14 Intel remain
unclaimed. The exact prepared version must pass these checks before release;
see the [installation scope](installation.md#qualification-scope).

Standalone release targets are Linux x86_64/arm64 with glibc 2.35+ and macOS
x86_64/arm64 on macOS 14+. Build separately for each target; PyInstaller is not
a universal cross-compiler. Alpine/musl and Windows bundles are not promised by
these milestones. Retain build provenance and test on clean target environments.

The Python runtime is included in standalone bundles. kubectl and cloud
credential executables remain external dependencies where the selected feature
or kubeconfig requires them. The application must detect missing executables
and give actionable instructions; basic API browsing must still work without
kubectl. The Homebrew formula declares its Kubernetes CLI dependency.

### Native build and qualification: #49

The optional `standalone` dependency group pins PyInstaller separately from the
application's runtime. From a native build host:

```sh
uv sync --locked --group dev --group standalone
uv run --no-sync python -m scripts.build_standalone --output artifacts/native-candidate
```

The output directory must be new. The recipe builds the actual wheel, installs
the hashed locked runtime/freezer dependencies in an owned environment, collects
styles and certificates, preserves original dependency/interpreter/library
notices, and archives the whole onedir bundle with contained relative symlinks.
Its manifest binds source inputs, wheel, native libraries, members and the archive
by SHA-256. Build success alone leaves `runtime_qualified: false`; clean-host,
owned-cluster and external-helper qualification is still required on each target.
Do not advertise the archive as a release solely because the builder exited zero.

An uncommitted developer build requires `--diagnostic` and is never a release
input. The Linux recipe rejects native library symbol requirements above glibc
2.35 outside diagnostic mode. It does not make a newer build compatible by merely
writing a lower declared minimum. macOS deployment floors and ad-hoc signatures
are inspected on the actual native files; Developer ID signing/notarization is
not claimed.

Pyte's original LGPL source stays outside the embedded Python archive and ships
with its license and replacement instructions. A local diagnostic trial exercised
an actual compatible source replacement in a copied bundle. The entire directory,
including `_internal` and notices, must be retained; the launcher alone is not a
portable installation. No standalone artifact has been published.

The freezing interpreter now comes from the full Python Build Standalone archive,
not the developer's interpreter or an install-only download. The reviewed
`packaging/standalone/python-runtime.json` pins CPython 3.12.15 / upstream release
20261009 independently for all four native targets, including size and SHA-256.
The recipe validates the archive, native header, target metadata and original
component notices before using its interpreter. Zstandard is confined to the
development/build groups; the installed application does not require it or the
standalone group.
An already-downloaded exact archive can be supplied with `--interpreter-archive`;
different bytes, architecture or interpreter metadata are rejected.

The full licensing inventory includes the original static component texts and
metadata. One upstream metadata entry names an alternative zlib-ng notice missing
from the full archive. The recipe retains that exact original upstream text from
a separately pinned source commit/digest and records it as supplemental, without
claiming the alternative is linked. A local native interpreter probe observed
Python 3.12.15, OpenSSL 3.5.9 and zlib 1.3.2. The original Python/library/metadata/
notice hashes are checked again after freezing.

The macOS recipe reads deployment floors from each actual Mach-O file and
verifies collected code signatures with `codesign`; it distinguishes ad-hoc
signatures from Developer ID and does not claim notarization. Actual Linux
x86_64/ARM64 and macOS Intel/ARM64 archives passed native runtime qualification.
Linux checks use a Python-free environment and exact-archive owned-kind exec;
Mac checks sandbox-deny outside Python and checkout/interpreter reads, including
Python invoked through the permitted system shell. Actual Mac hosts were macOS
14 ARM and macOS 15 Intel. Physical Python absence and macOS 14 Intel trials
remain unclaimed. The [D05 acceptance evidence](acceptance/standalone-executables.md)
retains original execution records, archive digests and compatibility limits.
Required full candidate checks and publication remain separate.

The native qualifier checks the original Git inputs and archive bytes, extracts
the exact archive outside the checkout, independently measures native floors and
signatures, and runs CLI/browsing/auth/embedded-shell PTYs. Linux uses the pinned
Python-free Ubuntu 22.04 base image. macOS uses a process sandbox that denies
execution of outside interpreters and access to the source/development environment;
this does not claim the physical macOS runner lacks Python. Original controls,
helper compilation and terminal-restoration receipts are retained:

```sh
uv run python -m scripts.verify_standalone --candidate artifacts/standalone-local --evidence artifacts/standalone-runtime
```

Application quality now selects four native jobs independently of the source
Python matrix: Ubuntu 22.04 x86_64/ARM64, macOS 14 ARM64 and macOS 15 Intel. The
labels are recorded in GitHub's [standard runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
Intel job measures the declared macOS 14 deployment floor but does not establish
an actual macOS 14 Intel host trial. The required aggregate refuses missing,
failed, cancelled or skipped native jobs and incomplete/wrong-target plans.
Both Linux jobs run the extracted executable's real selected-container/TLS/RBAC
shell scenarios on owned kind clusters. These four jobs and all six source
environments passed the completed [D06 checkpoint](acceptance/workload-checkpoint.md).
Version `0.1.0` passed its complete exact-main qualification and is published on
PyPI, GitHub Releases and the project Homebrew tap.

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

An unpinned published installation uses its actual
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

Public uv/pipx installation and no-op upgrade checks passed for the first release; distinct
version upgrades use the owned baseline trials until a public predecessor exists. Preserve
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

Version 0.1.0 has actual OIDC publication and public-channel installation evidence;
final website/domain verification remains in the first-channel activation task.

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
