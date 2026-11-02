# Plugin compatibility acceptance

Scope: U05 #60, on merged U04 #59 / PR #203 (`f104ea33754f08266ca809649ae568317836a486`).
This checkpoint documents compatibility and verifies original workflows; it does
not certify external products or publish a package, tag, website or DNS change.

## Audited source boundary

`docs/plugin-compatibility.json` classifies every one of the 50 plugin records in
`docs/k9s-source-inventory.json` at K9s v0.51.0 commit
`558caafe7ba067467de46b320cc22ef11fef9c34`: 48 manifests/108 commands and two
extensionless Bash helpers. Original source byte counts, Git blob identities and
SHA-256 digests were recorded from read-only downloads. No upstream script was
copied into executable project code or run. `tests/contract/test_plugin_examples.py`
requires the complete path set, pin, classifications and 18 exact fixture links.
The user guide lists each file's dependencies, free inspection alternatives and
specific limitations. External cloud/model services may have costs; their
programs and licenses remain independent.

The field matrix covers the complete pinned Plugin structure, inputs/defaults,
explicit wrapper/path translation, shortcut/scope differences and unsupported
pipes/overwriteOutput. Variable research uses pinned config/plugin.go and
view/{env,helpers,table,container}.go. Inversion really negates a parsed boolean;
RESOURCE_* and container NAME/POD semantics differ from the independent schema.
The guide states literal/one-pass behavior, visible-column normalization,
FILTER fallback differences, separate external service identities and conservative
read-only trust. There is no automatic importer or native parity claim.

## Executable evidence

The 18 original adaptation fixtures cover literal argv/scope/input/trust decisions
for eligible direct commands, recording each narrowed scope or changed behavior.
They do not launch third-party tools. Inversion is replaced by desired-state
booleans; PVC JSON quantities are constrained by a reviewed dropdown. Unsupported
upstream fields and untranslated variable forms fail closed.

Three original standalone manifests load through the actual explicit-file adapter.
Harmless owned kubectl stand-ins verify capture and completed background output,
read-only refusal before execution, deliberate cancellation, stopping a blocked
background read, missing executable handling and private mode-0600 file cleanup.
All API traffic uses an owned loopback fixture and synthetic credentials.

A real CLI PTY repeats the original interactive manifest twice. It fills the
required container field with shell metacharacters, verifies that exact single
argv value in a harmless child, sends actual terminal input and checks the original
terminal modes, return to the table, unchanged source kubeconfig and deleted
private delegation path. Potential sentinel writes refer only to its owned temp
directory. No real container, cluster or third-party program is used.

This unpaced test originally lost the beginning of input and never reached Review.
A key/focus trace confirmed that default non-priority Tab bindings bubbled after
subsequent keys had already been forwarded to the old button. PluginScreen now
owns priority Tab/Shift+Tab decisions, preserving native field traversal and the
Cancel default before the next printable key. The same real-PTY case passed in
3.65 seconds without pacing or a longer timeout. Initial harness setup was also
corrected to use the shared API fixture's exact synthetic token and the documented
Cancel-to-Run reverse Tab; these were fixture corrections, not application fixes.

## Measured gates and limits

Local Linux / CPython 3.12.12 passed 172 focused plugin/compatibility cases in
1.11 seconds before the final shared-helper move, plus the final original
interactive PTY above. These are focused cohorts, not full-package coverage.
The final broad unit/plugin/UI/terminal/site/safety cohort passed 2,683 tests
in 141.02 seconds. The final compatibility cohort passed 36 cases in 2.88
seconds, including real offline CLI checks with a missing kubeconfig and both
present and absent stand-ins; neither can start during validation. Cohorts
overlap and are not added. Focused plugin-domain measurement covered all 239
statements and 114 branches (100% each). Ruff, formatting, strict application/
site types, repository plan and whitespace checks passed. The local two-surface
build/check passed 67 pages and 3,084 links/assets. Actual Google Chrome
keyboard/accessibility/copy/no-JavaScript verification passed all 67 pages with
zero automated violations. These are local builds, not a deployment. Fresh protected
source/native results and exact candidate identity belong to the issue-linked PR. The critical module list
and its 100% line/branch requirement, independent 90% whole-package floors and
90% changed-line gate remain unchanged.

Scope validation now accepts valid hyphenated DNS1035 resource plurals and
rejects invalid label boundaries/lengths. Both unsupported boolean-inversion
spellings receive the correct diagnostic after literal-dollar protection.
Original/escaped/malformed substitutions retain their existing tests.

Foreground plugin output is direct TTY output, outside capture redaction/limits.
Background output is presented at completion rather than streamed; cancellation
can discard partial capture. External programs can ignore a connection or perform
side effects before errors. Real Argo/Flux/Helm/Loki/Stern/KubeVirt/Spark/storage
integration and provider certification are not inferred from these fixtures.
KubeRich 0.1.0 remains the published package; this checkpoint is next-release source.
