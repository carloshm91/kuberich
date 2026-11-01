# M05 #55 acceptance evidence

The data view stores key metadata without payloads, keeps values hidden on entry,
and requires an explicit reveal or copy. Each disclosure uses a fresh captured
UID/version-bound GET. Key, encoding, context and namespace changes hide the
previous value and reject late work. Ordinary details/YAML remain redacted;
application SVG export is refused while the data screen is mounted.

Secret editing uses the existing full-manifest disclosure checkbox, private
0700/0600 draft, separately redacted review, strict server dry-run, distinct
one-use Apply and common conflict/read-only checks. Payloads are absent from
public receipts and errors. Cleanup drains reads before disconnecting the client.
This does not promise secure memory/clipboard erasure or control external captures.

## Verification record

Initial parser/service/UI contracts: 59 passed. The deterministic parser and
service both reached 100% lines and branches in the focused instrumented run.
Additional empty/malformed/denied, large-preview/clipboard, button and scope
lifecycle cases pass in Pilot. The final screenshot/lifecycle Pilot cohort has
10 passes in 10.47 seconds; the source PTY and extended UI cohort has 11 passes
in 18.72 seconds. These focused counts are not whole-package qualification.
The issue-linked PR records the exact final full-suite coverage and required
platform checks; they remain mandatory before merge.

The extended owned-kind verifier passed all 21 checks against pinned Kubernetes
1.36.4, including real Secret text/binary reads, read-only denial, nonpersisting
dry-run, exact Apply, version conflict, get-only RBAC and immutable rejection.
It deleted its owned cluster and verified absence; the caller's configuration
remained byte-identical. Existing ConfigMap checks remain mandatory. The final
receipt is `artifacts/configuration-kind-final.json`.

Both static surfaces built and passed link/media/source checks: 59 HTML pages
and 2,476 local links/assets. All 46 site regressions passed. Locked Chrome
qualification covered desktop/mobile pages with zero automated accessibility
violations. Build and Twine passed for the local wheel/sdist; nothing was
published or version-bumped.

The first extended PTY fixture sent `v` immediately after Escape, allowing the
terminal decoder to interpret an Alt sequence; the corrected fixture waits for
the resource table before sending the next key. The first owned-kind extension
edited a Secret to its already-current value in the denied-user scenario; the
fixture now requests a distinct change so server authorization is genuinely
exercised. Both failed originals remain in local artifacts; no pass is claimed
for either run. The existing required assertions were retained.

The first full-suite attempt correctly refused its backend provenance receipt:
new production files had not yet been added to Git's tracked-file inventory,
while the heartbeat's disk inventory already included them. That interrupted
run recorded 1 failure and 934 passes; it is not qualification. The new files
are now staged before starting the final suite, preserving the required source
inventory checks and original failed diagnostics without weakening the gate.

A subsequent full-suite run was deliberately interrupted after 999 passes to
correct the interactive screenshot path: Textual's Screenshot action now warns
and continues, while direct SVG export remains refused. Pilot proves that no
file is written and the app remains usable; normal export works after closing
the data view. That interrupted run is not full qualification.

All resources and values are synthetic, served by owned loopback APIs or an
explicit owned disposable cluster. No maintainer context or real-cloud account
was used. Published 0.1.0 artifacts are unchanged; this is next-release source.
