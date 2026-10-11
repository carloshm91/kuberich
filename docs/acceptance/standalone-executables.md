# Standalone executables: D05 #49

Status: **in progress**. No release, tag, package or standalone download was
published. Build success and local runtime evidence do not complete all of #49.

## Four-target native execution and original enrollment passed

Corrected run `38098818073`, head `00f41ab`, passed Linux x86_64/ARM64 and
macOS Intel/ARM64. Its native archives bind the actual PR merge source
`3255a0f7e3aa449da363fff4b126387f9b41c519`. Mac jobs `114350286523`
(Intel) and `114350286580` (ARM) passed CLI, owned auth/interactive shell, native
signature inspection and terminal restoration. The system-shell positive controls
succeeded; both direct outside-Python controls and Python invoked through the
allowed system shell remained denied. This confirms the delegate correction on
both architectures. Linux jobs `114350286632` and `114350286565` passed their
Python-free runtimes and exact-native-executable owned-kind/TLS/RBAC controls.

All four outer ZIP digests matched GitHub. Independent readers accepted each
actual archive, 193 original Git inputs, complete native/assets/notices and its
12 original JSON records. Each Linux archive contains 15 native files; each Mac
contains 13. Actual local `enroll()` and `verify()` then preserved and re-read the
four original archives and unique raw-provenance sidecars without rebuilding.
This is actual native evidence rather than controlled parser-fixture coverage.
Original ZIPs, detached source and independent results remain under
`artifacts/standalone49/pr181-shell-delegate-ci` and `pr181-shell-delegate-source`.
The final local native-enrollment receipt is `native-enrollment-result-original.json`.

The complete source matrix remains in progress. Repository validation and DCO
passed, but #49/PR #181 remain open until the required full candidate gates pass.
This does not resolve the separate original #40 performance failure below or
claim public release qualification. No publication was performed. Physical Mac
Python absence, macOS 14 Intel trials and Developer ID/notarization remain unclaimed.

## Separate original source performance failure: D04 #40

The parent verifier now checks the child's original process/JUnit result after
source, instrumentation and cleanup validation, before checking successful-work
refill counters. Two controlled regressions reproduced the misleading assertion
before the correction; all three then passed, including continued refusal of a
successful but incomplete workload. This changes failure attribution only. The
150-ms threshold, dataset, GC and all successful/negative-control acceptance
checks remain enforced; it does not resolve the performance failure below.
The exact local command was:

```sh
uv run --no-sync pytest -q --tb=short tests/quality/test_aggregate_runtime_failure.py
```

The second run's macOS source job `114343581231` failed the full retained
aggregate-history scenario: 1 failed, 4,704 passed and 3 skipped in 1,942.47
seconds. The parent refill assertion obscured the child's original heartbeat
failure. Its fresh positive child measured 150.267833 ms during `warm 2 resource
route`, with 148.478 ms of main-thread CPU. A generation-two collection overlapped
for 64.916208 ms and collected 29,067 objects while Textual composed strips.
The overlap does not establish the complete cause. Coverage/tracing/profiling were
inactive, the development grammar was absent, source identity stayed unchanged,
normal GC remained enabled and app/API/watch ownership drained. The child did not
complete a full history round or refill; later negative/coverage children did not
run. The failed source job does not qualify this candidate.

Original artifact `11686237488` matches GitHub ZIP SHA-256
`8a6c2ebe578bbfe4c2606a0ddb56c01a2597735a14406bf1d147f9218cbfec19`.
Its complete original ZIP/job log and child receipts/stdout/JUnit/heartbeat remain
under `artifacts/standalone49/pr181-corrected-ci`. The existing #40 retains this
unresolved performance observation; the prepared D05 sandbox-shell correction
does not change that path or resolve it. No unchanged retry, threshold relaxation,
GC policy change or skipped gate is used as a performance fix.

## macOS shell delegation correction under verification

The second native run, `38096565815` at head `8fc22a2`, passed both Linux native
jobs. Both macOS archives now passed version/help/info and the missing-tool UI
scenario, including terminal restoration. This confirms the owned-cwd correction
for those actual archives. The C credential/exec fixtures reached the shell-start
marker, but `/bin/sh` exited with status 1 before executing the command; both Mac
original logs and GitHub-digest-verified ZIPs remain under
`artifacts/standalone49/pr181-corrected-ci`. This is a failed native qualification.

The sandbox permitted `/bin/sh` but denied its system-shell delegates. Apple
documents the macOS [shell selection mechanism](https://support.apple.com/en-us/102360#how-to-test-your-shell-scripts)
through `/var/select/sh`. The corrected profile permits only the exact system
bash/dash/zsh paths in addition to the existing app/helper/sh paths. It still
denies other executables and checkout/interpreter reads. Original controls now
require a real system-shell builtin to succeed and Python launched through that
shell to fail specifically with the sandbox denial; the release reader requires
both original controls. This diagnosis remains provisional until a fresh native
macOS candidate passes the complete auth/interactive-shell scenario.

The corrected host/release-reader cohort passed 92 local cases in 51.93 seconds;
the actual macOS sandbox regression is explicitly skipped on this Linux host.
Strict types passed for the two changed verification scripts. These checks do not
establish macOS execution success.

The frozen correction at `50fe5cb` subsequently passed the complete combined
host/native-reader/release-policy/archive/owned-HTTP cohort: 397 passed and one
actual-Mac test skipped, in 73.14 seconds. All 28 packaging/Homebrew cases then
passed in 352.36 seconds, retaining the original log at
`artifacts/standalone49/macos-shell-delegate-packaging-v1-original.log`.
The full strict workflow command passed 141 source files; lint/formatting passed
515 files and site checks passed 49 pages, 1,726 links/assets and 64 files.

Independent readers also accepted the second run's two actual Linux archives,
including each original source/archive-bound host and native-kind record. Each
retained 193 Git inputs, 15 native files and 12 original JSON records. The two Mac
archives passed the independent source/member/header/notice/asset reader, with
13 native files each; their highest original deployment commands were 11.0
(ARM64) and 10.15 (Intel). This does not change the declared macOS 14 floor or
qualify their failed interactive runtime. All four bind original merge source
`271b1d6015d2726566492baabc7298f7b72aa56d`; reader originals remain beside the
GitHub-digest-verified ZIPs under `pr181-corrected-ci`.

The frozen `8fc22a2` download-checksum candidate passed all 28 packaging/Homebrew
cases in 352.31 seconds. The retained original is
`artifacts/standalone49/packaging-download-checksums-stable-v1-original.log`.
The result includes checking actual flattened download names with the platform
checksum command; it does not qualify a public package or the subsequent Mac fix.

## Exact release enrollment under verification

The public candidate pipeline now consumes the source artifact and all four
standalone artifacts from one successful protected manual qualification run.
Preflight rejects missing/failed/skipped/wrong-runner/duplicate native jobs and
missing/expired/duplicate/shared-ID native artifacts. Its 257 decision tests passed.
The full strict workflow command passed 141 source files. Native archives stay
outside PyPI's wheel/sdist directory and keep unique original-provenance assets.
The reader independently checks original Git inputs, archive members, actual
ELF/Mach-O architecture and ABI floors, interpreter notices, styles/certificates,
CLI controls, complete terminal restoration and archive-bound native kind records.
The parser fixtures contain controlled non-executable headers and reports; they
are not native runtime evidence. Corrected actual macOS execution and fresh full
candidate qualification remain required. No publication or release dispatch ran.

The first local packaging observation ran while the reader inputs were still
changing: its original audit correctly rejected the source-policy digest mismatch.
It also found a real Homebrew integration defect: selecting every `.tar.gz` in the
complete bundle confused the four native archives with the source distribution.
Homebrew now selects only the verified `dist/` sdist. Original failed reports and
the controlled canonical fixture are retained under
`artifacts/standalone49/packaging-pre-freeze-original-v1`; a stable-source packaging
check is required rather than treating that observation as a passing candidate.

Original source Python 3.14 job `114333977651` completed successfully with 4,591
cases in 1,211.97 seconds. Its artifact `11685187401` ZIP checksum matches GitHub's
original `13858680d2aa4c295bb7aafe85ba1b7e3e379fc43d638879ad745219cbec2870`.
Independent reading measured 99.0694% lines and 96.8664% branches, all designated
critical modules at 100%, and 52 changed executable lines at 100%. This evidence
belongs to the original `bcbc09b` PR source, not the subsequent release-enrollment
changes; the original overall run remains incomplete and its macOS failures remain.

That original run has subsequently completed: all four source jobs succeeded;
the aggregate correctly failed because the two native macOS jobs failed. Linux
3.12 passed 4,591 cases in 1,910.89 seconds plus all owned-cluster/installed-guide
checks. Its original artifact `11684929644` matches GitHub ZIP SHA-256
`d72e51d61bc97df26f68da02f1c990d9893deb61687bde5a5cfa1fc811e0d06d`.
It measured 99.1090% lines, 97.0038% branches and all 52 changed executable lines
at 100%; raw run/jobs/artifact records and original logs remain retained.

The reviewed `83b7c89` source was then built independently in an owned pinned
Ubuntu 22.04 container, in 143.48 seconds. Its archive checksum is
`e971f996ddd19a2ca4878cc574c247ecb89eb3d932728b47f07c3434ac170993`.
The exact archive passed original-source/member/native/notices checks and the
Python-free CLI, loopback browsing, optional-tool, C auth helper and real `/bin/sh`
controls. These originals are retained in the `ubuntu22-release-enrollment-*`
paths under `artifacts/standalone49`. The corrected Mac candidate remains pending.

The stable `8022f60` release-enrollment candidate passed all 27 packaging/Homebrew
cases in 350.36 seconds; the original log is
`artifacts/standalone49/packaging-release-enrollment-stable-v1-original.log`.
The corrected parser/original-record/archive/owned-HTTP cohort passed 379 cases.
The complete strict command passed 141 source files; Ruff/formatting passed over
515 files. Site building/checking passed 49 pages, 1,726 local links/assets and
64 files. These are local preparation/controlled-fixture results, not a public
package or a substitute for fresh native qualification.

Both original Linux archives were independently re-read from the original
`a06fba3` Git source after each outer ZIP matched the corresponding GitHub digest.
The complete 188 Git inputs, tar member checksums, actual native architecture/
GLIBC floor, original interpreter metadata, 20 notices and required runtime assets
passed for x86_64 and ARM64. The detached original source and reader outputs remain
under `artifacts/standalone49/pr181-original-source` and `pr181-original-ci`.

## First hosted native observations: PR #181

Application quality run `38093295317` at head `bcbc09b` selected all four native
targets; artifacts bind the actual PR merge source `a06fba34508e9a00b7668ff10d13d5674a58af4e`.
Linux x86_64 job `114333977598` and ARM64 job `114333977574` completed successfully,
including Python-free runtime and real extracted-archive kind execution. Original
artifacts are retained for independent review; this is not a complete green run.

Both macOS jobs completed native construction then failed isolated `--version`.
The ARM original artifact `11684797107` has ZIP SHA-256
`4c7e06714eb6c8a9d1cbda9c92b589c3da244de1b732230f9ecbd5da6ac72c42`;
its inner archive is `f05f01fab4a35498ff66bd7d2e53660d28a1bcf7b3fbc4376a00d7b73360f483`.
All 13 native ad-hoc signatures were verified; actual load commands measured 11.0.
The declared macOS minimum stays 14 and no Developer ID/notarization is claimed.
External and system Python controls both failed with the intended sandbox denial.
Version failed at Rich's `os.getcwd()` import because the controller inherited
the deliberately forbidden repository cwd. The CLI observer now sets its owned
temporary cwd and retains that path with the control result. The sandbox rules
remain unchanged. Eight actual host/helper regressions and strict verifier types
passed locally; corrected macOS execution still needs fresh native evidence.
Original logs/archives are under `artifacts/standalone49/pr181-original-ci`.

## Reproducible qualification and CI preparation

The reusable reader rejects stale/dirty Git inputs, tampered archive/member
identity, native architecture mismatches, overclaimed minimum versions, changed
original interpreter pins/licenses and missing certificate/source/style assets.
Actual native symbol/load-command/signature observations take precedence over
producer compatibility flags. The executor extracts those exact checked bytes
outside the checkout and retains original CLI, helper-compiler and PTY controls.
The Linux base is physically Python-free; macOS's external-interpreter/source
denial is explicitly process isolation rather than physical host absence.

The retained `a2002de6...` Linux archive passed the executor. Its initial reader
incorrectly assumed Textual had separate `.tcss` files; the actual retained
inline stylesheet source and KubeRich `.tcss` are now checked. The next failure
exposed relative controller Docker lookup after the application's PATH was
isolated; absolute controller capture fixes that boundary, with a real-subprocess
regression. The successful execution and original failure log remain separate
under `artifacts/standalone49/formal-host-runtime-v2-original.log` and
`formal-host-runtime-v3-original.log`; no failing original was overwritten.

An actual owned-kind trial used the retained executable for all nine shell
scenarios, including fullscreen `vi`, real selected-container exec, TLS overrides,
impersonation/token/role denials and synthetic EKS/AKS helpers against a real API.
The fixture uses typed SDK request models, with the source controller retained
before execution. It exited zero, removed its owned cluster and verified absence.
Evidence is `owned-kind-native-v1.json` / `owned-kind-native-v1-original.log`.
This does not certify real AWS/Azure or the later committed CI candidate.

The current focused cohort passed 163 cases; nine strict scripts and Ruff passed.
Application quality now prepares four native jobs plus the unchanged source
Python matrix, complete native planner validation and protected aggregate
dependencies. Linux jobs require actual extracted-archive kind execution.
Actual hosted matrix results, original cross-target evidence and exact
release-candidate enrollment remain necessary before completion.

## Committed full-interpreter Linux checkpoint

The owned Ubuntu 22.04 x86_64 build of `f2a0e310ff67e35b9f02f0ad33b3e96ef6c9a1ce`
completed successfully in 146.24 seconds. It used the pinned full CPython 3.12.15
archive, retained 17 metadata components / 20 original notice texts and produced
archive SHA-256
`a2002de6ddddd4f8bba1ee995ccbd657aefb18a3e413739c87c60cfdaf120428`.
The whole native inventory's highest GLIBC symbols were 2.35; source was clean
and this build was not diagnostic. `runtime_qualified` remains false pending
the complete delivery contract.

The exact bundle passed seven clean-base checks: package inventory, GLIBC,
absence of system Python/uv/pip/kubectl, version, help, info, and an actual PTY
pod/container browser with the explicit missing-kubectl behavior. A separate
actual PTY passed the owned C exec-credential helper, private snapshot,
sanitized external loader environment, real `/bin/sh` output, unchanged caller
kubeconfig and UI return. Both sessions exited zero with exact terminal-mode,
alternate-screen, cursor and reporting-mode restoration.

The independent original reader matched all 128 source inputs against the Git
commit, the archive/member/native-file hashes, original interpreter executable,
shared library and metadata, every original and bundled notice text, the wheel,
build logs and terminal receipts. Evidence stays under
`artifacts/standalone49/ubuntu22-full-native-v1`; the two terminal receipts are
`clean-full-ubuntu22-native-49-missing-kubectl.json` and
`clean-full-ubuntu22-native-49-c-auth-exec.json`. No owned #49 containers remained.
This is x86_64 Linux plus owned synthetic API/auth/exec behavior, not actual
provider or cluster exec certification. macOS/ARM, protected native CI and
exact release-candidate integration remain open requirements.

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
exceeds the promised minimum. That diagnostic checkpoint preceded the
committed-source minimum-floor evidence recorded above.

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
