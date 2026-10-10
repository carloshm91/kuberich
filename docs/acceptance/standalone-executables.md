# Standalone executables: D05 #49

Status: **in progress**. No release, tag, package or standalone download was
published. Build success and local runtime evidence do not complete all of #49.

## Full interpreter enrollment checkpoint

The recipe now prepares the reviewed full upstream CPython 3.12.15 / 20261009
distribution for each architecture. Original immutable release digests were
queried directly and pinned in `packaging/standalone/python-runtime.json`.
Extraction validates digest/size, contained paths and links, native headers,
version/target metadata, original component notices and interpreter/shared-library
identity. It retains the licensing inventory in the frozen bundle and rechecks
original hashes after construction. Zstandard is confined to the optional build
group.

An actual full Linux archive enrolled 17 metadata components and 20 notice texts.
An independently invoked native interpreter reported Python 3.12.15, OpenSSL
3.5.9 and zlib 1.3.2. Upstream metadata names both zlib implementations but omits
the zlib-ng text from its full archive; that separately pinned upstream source
text is retained as supplemental. This does not relabel the linked zlib version.
The initial missing-notice failure is retained alongside the corrected enrollment.

The developer-host full build has archive SHA-256
`91514d0a2da9165dad72a1d11271f202f55ac66d2e825e54d2537664eaaadae4`.
Its 128 input originals were retained separately. Its copied host `libstdc++`
advertises GLIBC 2.38: the archive is diagnostic and fails the whole-bundle floor.
The clean-host CLI preflight correctly refused it before container launch. A
separate actual C-auth/real-shell PTY on the base Ubuntu 22.04 image passed, but
that narrow behavior result cannot qualify an archive whose library inventory
exceeds the promised minimum. The committed-source minimum-floor build remains
the next required evidence.

Full-interpreter ingestion checks and Mach-O deployment parsing add 22 cases to
the archive/notice tests. Current combined scope is 67 cases; strict builder/
archive/interpreter types and Ruff pass. macOS floors are now read from actual
load commands, and code signatures are inspected/verified per native file. Pure
format tests do not establish actual macOS runtime/signing qualification.

The following report preserves the earlier install-only checkpoint and its
remaining limits; it does not claim the new full-interpreter candidate inherits
its qualification.

## Original local evidence: 2026-10-10

The frozen launcher uses the application executable for its owned PTY child,
then sanitizes loader state only for the external helper. Source/wheel execution
retains the isolated standard-library Python launcher. The original focused
runtime suite passed 219 cases; `kuberich.runtime` measured 100% lines/branches.
This is not the full production/changed-line qualification result.

Archive tests passed 35 cases, including actual contained relative symlinks,
duplicate source inodes, deterministic metadata/bytes, architecture mismatches,
traversal, cycles, dangling links, devices, permissions and limits. The current
notice/build tests passed 10 cases, including original notice retention,
tampered/missing license rejection and missing/ambiguous package ownership.
Ruff and strict builder/archive types passed. The commands were:

```sh
uv run --no-sync pytest -q tests/quality/test_standalone_archive.py tests/quality/test_standalone_build.py
uv run --no-sync pytest -q tests/quality/test_standalone_build.py
uv run --no-sync mypy --strict scripts/build_standalone.py scripts/standalone.py packaging/standalone/runtime_inventory.py
```

The first combined run had 41 cases; four package-ownership tests were added
after the clean container exposed merged-/usr lookup. Its next focused notice
run passed all 10 current notice cases. Do not interpret these focused results
as an original full-suite run.

The diagnostic developer-host archive retained notices, certificate/styles,
native/member hashes and a build manifest. Actual extraction outside the checkout
passed repeated shell, Unicode/protocol/resize and deliberate-close cases. Pyte's
original source matched the installed wheel and was absent from PYZ. A compatible
source replacement in the copied bundle was actually imported and another UI/PTY
scenario passed. This archive observed GLIBC 2.38 and is explicitly ineligible
for the promised Linux 2.35 minimum.

## Minimum-floor Linux x86_64 checkpoint

Frozen source commit: `af42daa0f6da26d4c99d524c0fdbe058c4f292a4`.

Owned build/test image:
`ubuntu@sha256:b8b6ee6aa931ecd9d0d952abc34dc0e5f7c6a30c6bb71b079fe399fde0329c02`.
The builder controller includes development gates; the separate freezing
environment contains the actual wheel plus locked runtime/freezer dependencies.
No interpreter or controller installation is mounted into the clean runtime image.

Archive: `kuberich-0.0.1.dev0-linux-x86_64.tar.gz`.
SHA-256: `5e4ba8c19a159c1b2618a937479bc68ceec250adfcb8c166e5b5998afaaba934`.
The actual highest observed GLIBC symbol version is 2.35. An independent original
reader matched 126 source inputs to Git, all 688 archive members and 15 native
files. The manifest preserves `runtime_qualified: false`.

On the unmodified base image, package inventory and executable discovery found
no system Python, uv, pip or kubectl. Frozen version/help/info succeeded. An
actual PTY listed 80 pods from an owned loopback API, opened containers and showed
the actionable missing-kubectl message. A separate trial mounted compiled C
credential/kubectl fixtures and executed the image's actual `/bin/sh`, verifying:

- Configured exec credentials reached the owned API with the expected synthetic
  token; the token was absent from the terminal transcript.
- The external helpers rejected leaked frozen loader state; the exec fixture
  received a private-mode kubeconfig snapshot.
- A shell command produced output, exited and returned to the resource view.
- The caller's owned kubeconfig bytes remained identical.
- Exit was zero; TTY attributes, alternate screen, cursor and reporting modes
  were restored. No issue-labelled container remained after cleanup.

The C helpers are explicitly test fixtures. This proves native frozen process
boundaries on the Python-free image, not real-provider authentication or actual
Kubernetes exec. The API/controller and PTY observer run on the test host;
the application and its external helpers execute inside the clean container.

Originals remain locally under `artifacts/standalone49/ubuntu22-native-v4` and
`artifacts/terminal/clean-ubuntu22-native-49-*.json`. The independent review is
`independent-original-review.json`; it reads originals and does not rerun tests.

## Retained failures and remaining gates

The original developer recipe failed parsing uv's generated comment header;
runtime export now omits it. Original container v1 lacked the documented
development gates and exited before the recipe. Container v2 could not rediscover
the owned nondefault interpreter after sanitization; the recipe now passes it
explicitly. Container v3 built the binary but notice lookup used a resolved
`/usr/lib` path while dpkg recorded `/lib`; lookup now uses original and verified
alias identities and rejects unavailable/ambiguous owners. Each original log
and its outcome are retained. These are distinct prerequisite/source corrections,
not unchanged reruns presented as fixes.

The runtime preserves CPython, original Python dependency/freezer and copied
system-library notices. Statically linked interpreter dependencies still require
complete notice/source enrollment. In particular, Python Build Standalone's
install-only archives omit full-build metadata and files outside the installation;
its full build carries licensing metadata and license texts. The original
corresponding interpreter source/notices must be verified before a release.
See the primary [distribution format](https://github.com/astral-sh/python-build-standalone/blob/main/docs/distributions.rst)
and [licensing guidance](https://gregoryszorc.com/docs/python-build-standalone/20240725/running.html).

| Target | Current evidence | Remaining qualification |
| --- | --- | --- |
| Linux x86_64, glibc 2.35+ | Exact committed native build, clean image CLI/UI, C auth/exec fixtures | Full notices, actual owned-cluster exec and protected CI/release enrollment |
| Linux arm64, glibc 2.35+ | Recipe and native architecture checks | Actual native build and equivalent runtime/cluster evidence |
| macOS x86_64, macOS 14+ | Recipe and native architecture checks | Actual native build, minimum OS, clean runtime, helper/cluster and signing evidence |
| macOS arm64, macOS 14+ | Recipe and native architecture checks | Actual native build, clean runtime, helper/cluster and signing evidence |

Four-target archive provenance, protected aggregate checks and exact release-input
consumption remain under development. Developer ID signing/notarization is not
claimed. Provider certification remains opt-in under #87. Public activation is
the separately approved task #89. No acceptance checkbox is marked complete from
these local checkpoints alone.
