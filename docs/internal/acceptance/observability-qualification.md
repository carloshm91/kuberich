# Observability checkpoint preparation

This records the source preparation for
[D08 #75](https://github.com/carloshm91/kuberich/issues/75), based on protected
main `389babca15ab15e0ef8317a815afbeda1e8e9f73` after PR #320. It does not
complete the cumulative release gate or authorize publication. Exact final
candidate commits, artifact hashes and cumulative reports belong to the live
issue's retained qualification evidence.

## Changes

- Set source/own-lock metadata to 0.4.0 without third-party dependency updates.
- Remove the deprecated console entry and Python shim, preserving legacy
  preferences, environment/log compatibility and explicit migration behavior.
- Preserve Home/End intent against earlier animations/restorations and show
  long synthetic identity values using single-line header ellipsis.
- Separate native Homebrew core-dependency setup from application verification,
  binding its receipt to the exact clean source, workflow job and owned runner.
- Retain actual command failures/timeouts, partial output and elapsed times;
  drain owned installer descendants on successful and failed leader exits.
- Require candidate bottle cache bytes to match before a warm-pour measurement.
- Synchronize the source tap scaffold with scoped formula trust and the active
  public tap. This does not modify the public tap.

## Measured preparation evidence

These scoped checks used synthetic fixtures and isolated installer state.
They do not replace whole-candidate coverage, supported-host results or release
repetitions. The ignored originals remain under `artifacts/issue75/`.

| Check | Observed result | Limit |
| --- | --- | --- |
| CLI, migration and public predecessor pins | 52 passed in 1.51 seconds | Canonical stdout/errors, legacy bytes and reviewed immutable 0.3.0 artifact |
| Fresh installs and real predecessor transitions | 31 passed in 338.64 seconds | Wheel/sdist, private RC and actual public 0.3.0, uv/pipx, installed terminal and removal |
| Dependency receipts and real process ownership | 21 passed in 1.68 seconds | Seventeen dependency guards plus four real detached-stdio/TERM-ignoring child controls |
| Initial source-formula and tap-tooling cohort | 79 passed in 322.49 seconds | Scoped generation/fixtures; no native Homebrew installation is claimed |
| Shared ordinary/Events navigation | 30 passed in 17.32 seconds | Home/End, selected identity, cursor modes and deferred restoration |
| Actual App and SVG headers | Three passed in 7.77 seconds | Nine captures at 120, 100 and 40 columns |
| Native header/identity/navigation | One passed in 7.54 seconds | Forty-four positive frame stages, expected/observed UID, Back, rules and terminal cleanup |
| Corrected native frame/access path | Three passed in 14.35 seconds | Default and fragmented reads, explicit live rows, same-UID Inspector/YAML, one horizontal step, Back and mixed-frame rejection |
| Zero-desired DaemonSet | Owned API proof plus 17 controls passed | Kubernetes 1.36.4 omitted optional zero counters; Pulse correctly retained unknown |
| Documentation and authored-note contracts | 148 passed in 34.78 seconds | Source structure/links and note machinery; final publication remains separate |
| Strict workflow-derived type targets | 314 source files passed | Source preparation, not a full runtime result |
| Local static surfaces and browser | 53 desktop and 53 mobile pages passed | 2,188 local links/assets, no browser failures/violations or external requests; no deployment |

## Original failures and retained limits

The original pipx normal-upgrade cohort passed 28 cases and failed one: its new
0.4.0 package was correct, but the exposed retired alias was a dangling symlink.
Do not relabel that normal upgrade as successful. The corrected supported
transition uses a preventive direct pipx reinstall for an unpinned requirement.
An explicit old version constraint is first shown to remain old on reinstall,
then deliberately replaced using manager uninstall/install. Strict alias absence,
configuration/log bytes and ownership, actual installed navigation/shell,
restoration and removal remain required. This does not prove that reinstall
after an already-completed problematic upgrade repairs its exposed links.

The first clean committed broad interface cohort passed 1,334 cases and failed
the new native header probe while waiting for its first horizontal heading
translation. Its original log, XML and native frame directory remain retained;
the earlier isolated native success does not qualify that broadened result.
Independent tracked-document review also found two missing disposition entries
after the new Markdown files were staged. Exactly two entries were appended;
all 364 existing records and 105 historical pins remain unchanged, with nine
focused internal-document/navigation/source checks passing after the correction.
Original hosted failures also exposed two stale text oracles requiring the 0.3
qualifier command and a future alias-removal notice. Both were reproduced as
controlled failures, then updated to the actual 0.4 contract while retaining
explicit migration, canonical output/exit and legacy-file/privacy requirements.
The full requested documentation/oracle selection passed 33 cases.

The installer helper originally left an owned descendant alive after both a
successful leader exit and a timeout whose leader exited on SIGTERM. Original
red receipts retain explicit independent cleanup. The correction always drains
the owned process group and retains the original output, exit and deadline.

Initial UI controls reproduced four pending-animation and four queued-restoration
failures. Original blank-header App/SVG/native captures remain intact. Several
new native capture oracles sampled loading or partial resized frames; corrected
proof requires complete positive layout/source witnesses. A one-packet batch of
twenty `h` inputs did not expose rule prefixes. An earlier isolated passing native
sequence used twenty individually acknowledged real inputs and did not qualify or relabel
that batched path. Wide rule/relationship cells still need horizontal navigation;
no density redesign or complete product parity is claimed.

A later default-size native read also failed the ninth one-cell acknowledgment,
while fragmented reads completed that sequence. Pixel movement is not a
quiescence fence for deferred/animated scrolling. The final native acceptance
checks one horizontal step and full rule fields through the supported
`o` → same-UID Role table → Inspector/YAML path, with a fresh exact object GET,
strict Back/viewport and explicit live-row guards. It does not claim to fix rapid
input or qualify twenty exact native increments. The original fixed output
directory was overwritten by a later failed broad run; its original green XML
remains historical, while the current raw bytes belong to that failure. New
native runs retain unique private directories under
`artifacts/terminal/header-identity`, covered by the existing CI artifact policy.

## Final gate

After protected preparation delivery, freeze the exact main candidate. Require
its successful manual six-environment Application matrix, four standalone targets,
Repository checks, all six native Homebrew lanes, independent production/critical/
changed-line coverage, three contract/owned-cluster rounds, exact audited
artifacts and the separate sustained-resource trial. Keep every failure, explicit
skip and provider-certification gap visible. The coordinator's `report.json` and
`summary.md` are necessary but do not incorporate every native/soak criterion;
see [release verification](../../releases.md#reproduce-phase-verification).

Published channels remain 0.3.0 during preparation. Tags, packages, tap/bottle
activation, website deployment and DNS require their separate concrete approval.
