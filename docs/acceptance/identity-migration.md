# KubeRich identity migration: #149

The maintainer chose KubeRich and confirmed acquiring kuberich.com. The migration
updates the distribution/import/CLI, UI identity, release/Homebrew/security tooling
and current documentation. The old `kubetrol` console command delegates to the
same entry point; no duplicate production package is shipped.

## Qualification in progress

Focused preference/CLI/logging/layout and actual installed-wheel metadata,
legacy-alias and migration verification passed 334 cases. CLI, path selection,
bounded preference read/write/migration and diagnostic logging reached 100%
lines/branches in that focused run; the complete critical inventory awaits the
full matrix. Independent quality/Homebrew verification passed 345 cases.
The exact CI-declared strict mypy command passed over 107 source files; Ruff,
formatting and the original plan inventory checks passed.

Actual installed-wheel CLI trials use owned default locations outside the
checkout, retain unknown/private fields without displaying them, preserve source
bytes/read-only settings, and verify canonical/legacy commands. Unit cases cover
canonical/legacy environment precedence, relative log paths, malformed/special
files, existing destinations, commit races, private permissions and idempotence.
Known legacy log, lock and archive headers remain usable; foreign-file protections
and existing signal/terminal ownership tests remain in the full suite.

The initial focused run caught an obsolete help snapshot (326 other cases passed).
Both reviewed argparse snapshots now describe the added migration command. An
initial matrix attempt caught an obsolete single-entry-point artifact assertion;
the next caught a real-terminal assertion expecting the old ASCII logo. Both
were interrupted, retained as controls, and corrected without changing the
production source. Final full reruns use explicit canonical/alias metadata and
the displayed KubeRich logo.
An
extra strict audit included two legacy untyped integration drivers outside the
existing CI type-check list and reported 61 diagnostics. Its output is retained;
the required typed runtime/tooling command is unchanged in scope and passes.

Full Linux CPython 3.12/3.13/3.14 suites, independent coverage/changed-line gates,
fresh artifacts and all eight owned Kubernetes rehearsals are in progress.
Repository rename/redirect/private-identity verification follows local qualification.
Native macOS/full hosted checks remain unavailable under the account billing
restriction and are mandatory before public release. No public artifact, tag,
release, website/DNS, organization creation or visibility change is made.

Historical acceptance reports retain their original artifact names, source trees
and measurements. Current evidence: `/tmp/kuberich-149-evidence` (local).
