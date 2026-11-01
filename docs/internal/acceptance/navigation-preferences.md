# U02 #57 acceptance evidence

The first completed hosted Python 3.14 suite passed 5,211 cases with two skips
in 1,653.34 seconds. Its independent gate correctly failed: `cli.py` had one
uncovered invalid-navigation fallback line/branch (99.35% lines / 97.73% branches)
despite 99.0589% production lines and 96.5133% branches. Other critical modules
measured 100%. These results are not final qualification and no merge occurred.
The original job is 116295227662 in run 38696757569; retained artifact 11956075948
has SHA-256 `f0fe9cf97c3ba3b94d22587941f5550fbeecaf5553e5a0a2b7958b1f1c9cb95a`.
An added actual CLI contract verifies that invalid navigation retains offline
diagnostics, refuses strict config validation and preserves the original file.
The critical inventory and thresholds remain unchanged; fresh final-head checks
must qualify the correction.

The corrected local CLI/preferences/appearance/navigation cohort passed 379
cases in 116.14 seconds. The critical CLI measured all 154 executable lines and
44 branches (100% independently), with no missing/excluded lines or branches.
The application production subtree remains unchanged; the correction adds the
missing behavioral test and records the original failure, without weakening a gate.

The next-release source supplies independently versioned navigation preferences,
per-owner remapping through public Textual bindings, literal bounded aliases and
captured resource-view editing. Native fallback/input/copy/quit keys remain
reserved; help/completion use effective configuration. Cluster actions retain
the original policy and explicit review. Invalid overrides preserve working
defaults and the original preference file.

Native and server-printer layouts have separate exact-version identifiers. The
latter fingerprint ordered printer fields, preventing positional reinterpretation
after a schema change. Context overrides win over global views. Display cells
retain full typed sort models, stable UID selection and guarded viewport
restoration. Column revisions reject old yielded patches. Metadata reload
ownership remains independent of value-disclosure navigation generations.

The initial pure/persistence cohort passed 130 cases; the four new deterministic
modules previously measured 100% before final applicability additions. The
corrected existing custom-browser cohort passed 21 cases. A real source PTY
passed configured keys, alias completion, an explicit private context save,
40-column resize, restart persistence and complete terminal restoration.
These are focused measurements, not full platform qualification. Final exact-head
measurements and required hosted coverage/native/kind evidence belong in the PR.

Initial regressions exposed a printer header being passed as a markup-enabled
string and a recreated resource retaining inapplicable session fields. Literal
Rich Text labels and schema/field cache invalidation correct those behaviors.
New test-fixture scope/schema errors were corrected without relaxing assertions.
Failed original local reports remain under artifacts; they are not relabeled.

The user guide is enrolled on both documentation surfaces. No version/tag,
package, Homebrew tap, website or DNS publication is performed by this change.
Real-cloud/provider and physical-terminal certification remain deferred. This
does not complete expanded navigation/filtering, reactive configuration or plugin
work tracked by #61/#64/#58-#60, or establish complete UI01/UI05/RES06/EXT02 parity.

The four final pure preference modules measured 100% lines/branches. The broader
view/appearance/log/launch cohort passed 218 cases; site regression tests passed
53 cases with 63 built pages and 2,770 checked local links/assets. Strict types
passed across 132 application/gate/site modules. A coverage-enabled real PTY
exposed queued nonpriority input-editing bindings erasing newer typeahead;
NavigationInput now promotes native editing bindings, and the view editor owns
priority Tab/descending changes. The corrected original PTY passed in 9.63 seconds
under coverage, preserving the complete input/save/restart/restoration assertions.
The diagnostic key-dispatch trace contains owned synthetic data only and is
retained locally alongside the failed original.

The actual key-dispatch trace showed native nonpriority editing reaching App
after newer printable input, and queued Tab presses retaining the old checkbox
owner. Native editing, editor focus traversal and checkbox toggling now finish
in their owned priority bindings. The corrected input/navigation regression
passed 48 cases. Four additional lifecycle cases passed explicit session use,
disabled-save guards, duplicate requests, Escape while saving, actual graceful
teardown waiting for the requested write, and bounded cache eviction. No pending
test gate is left unreleased on an assertion failure.
