# Plugin execution acceptance

Scope: U04 #59 on the merged U03 contract. This checkpoint adds actual local
execution and interactive review; it does not assert community-plugin parity,
real-cloud certification or a newly published package.

## Behavioral evidence

`tests/contract/test_plugins.py` uses harmless real children and an owned loopback
Kubernetes API. It checks literal hostile argv, separate plugin cwd/environment,
mode-0600 single-context files under a mode-0700 session, one-use review identity,
explicit confirmation, read-only pre-lookup refusal, combined output overflow,
exit/signal/timeout, malformed environment, stale/recreated/forbidden/missing
targets, background waiter ownership, descendant termination and context cleanup.
Preparation cancellation drains its worker before releasing the captured client.

The credential-helper trial executes a real helper that reads a relative file
and requires its original profile while the plugin uses another cwd/profile.
The delegated helper receives client-go's fresh ExecCredential information,
retains its original identity and leaves no private files after completion.

`tests/ui/test_plugins.py` uses Textual Pilot at 44×14 and 110×35, actual command
and shortcut routing, typed inputs, explicit Review/Run/default Cancel, invalidated
reviews, duplicate-run refusal, read-only classification, completion, job output/
Stop, background persistence and context cleanup. It verifies inputs keep literal
keys, screenshot export is refused while raw plugin inputs are mounted, and the
root viewport survives return. These are local synthetic fixtures, never private
client contexts.

The unchanged `tests/terminal/test_handoff.py` runs real plugin-purpose terminal
handoff, interruption, repeated success/failure, startup error, cancellation,
parent shutdown, HUP and read-only refusal. It verifies original terminal modes,
foreground process ownership and restored responsive Textual input. This is the
foreground path used by explicit local plugins; embedded container shells retain
their separate emulator and lifecycle.

`tests/packaging/test_distribution.py::test_installed_private_credential_launcher_without_checkout_imports`
executes the installed launcher with `-I` outside checkout imports, verifying
original cwd/profile and fresh exec information. The standalone verifier additionally
executes each candidate's frozen private dispatch with its owned native C helper.
Linux uses the clean base with no Python package; macOS denies outside Python.
The verifier receipts record those observations; their execution is required by
the native matrix rather than inferred from unit mocks.

## Gates and limits

Local Linux / CPython 3.12.12 verification passed a 2,581-test unit/plugin/PTY/
safety cohort in 111.23 seconds and a 371-test focused process/plugin/UI cohort
in 56.99 seconds. These cohorts overlap and are not added together. Three final
concurrency/input-freeze/original-selection regressions passed in 1.36 seconds;
the fresh installed-wheel credential launcher passed in 5.78 seconds. The
focused measurement covered all 36 child statements/12 branches, all 238 plugin
statements/114 branches and all 109 process-domain statements/34 branches.
These are module/cohort measurements, not complete production coverage.

Ruff, formatting, strict mypy, repository validation and local two-surface site
build/check passed: 65 pages and 2,922 local links/assets. The build is local;
no website is deployed by these commands.

The private credential child is critical: 100% lines and branches are required,
alongside the existing critical plugin/process/runtime/CLI/command decisions.
Whole-package independent line/branch floors and changed-line gates remain
unchanged. Hosted source/native results and exact candidate identity belong in
the issue-linked PR; a passing focused cohort is not whole-package qualification.

Captured output is bounded and sanitized; arbitrary local programs can print
information the app cannot recognize as sensitive. Native foreground output goes
directly to TTY and cannot receive capture redaction or byte accounting. External
tools can act on other resources or connections deliberately: plugins are trusted
unsandboxed local code, not a Kubernetes permission or filesystem sandbox. Local
UID preflight does not make a later external write atomic. No tag, version bump,
package, tap, website or DNS publication is performed by this implementation.
