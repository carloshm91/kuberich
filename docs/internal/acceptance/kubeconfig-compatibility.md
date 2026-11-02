# Kubeconfig compatibility acceptance

This checkpoint verifies local configuration and transport contracts. It does
not certify cloud accounts, issuer exchange, Teleport routing, a live tailnet or
every supported kubectl binary against a real cluster.

## Delivered behavior

- Explicit Basic credentials work for owned reads and guarded writes. Username
  and password remain separate from bearer storage and survive private delegated
  staging with mode 600; anonymous connections receive no invented identity.
- Token/exec refresh updates the identity used by the same read/write transport.
  Explicit credential overrides replace Basic credentials without changing the
  catalogue. Existing uncertain-write and no-replay behavior remains covered.
- Empty optional context user/namespace fields and TLS inline-data/file fallback
  follow kubectl serialization defaults. Null optional impersonation collections
  do not disable validation of malformed values.
- The explicit `kubeconfig oidc-migration` command emits a real int128/kubelogin
  v1 fragment. It contacts no issuer, runs no helper, installs nothing and changes
  no source bytes or permissions. ID/refresh tokens are omitted; a client secret
  becomes a fixed manual-replacement placeholder. Issuer/client-id/CA metadata
  is validated and relative CA paths retain original user-file provenance.
- Known invalid/unsupported fields produce fixed field-specific messages. Safe
  catalogue messages survive the session boundary with unchanged state, identity
  and cleanup. Raw parser, SDK, HTTP or credential output is not surfaced.

## Matrix and loader decision

The upstream client-go API-v1 schemas inspected for release-1.35, v0.36.4 and
release-1.37 are byte-identical, SHA-256
`25a9a5915ba3e151bfd3ac419b1c90b760a840795ea64d661e2a05a45a030f94`.
The canonical context guide covers every field group across those schemas.
This is a source-backed schema matrix, not an assertion that three binary/client
platform combinations were exercised locally. Existing disposable-cluster work
uses the separately pinned kubectl 1.36.4 integration reference.

ADR 0032 evaluates the actual per-client SDK 36.1.0 loader and retains owned
preparation because its remaining shared material cache, file work and helper
lifecycle do not satisfy the application boundary. It distinguishes avoidable
global/persistence defaults from the remaining public-API gaps. Existing real
SOCKS/TLS name-verification behavior is preserved.

Nine tracked, secret-free templates cover EKS, AKS, GKE, Rancher, OpenShift, k3s,
kind, Teleport and Tailscale shapes. Tests inject newly generated owned TLS
material and harmless literal-argv helpers, require real certificate handshakes,
preserve Rancher URL prefixes and validate Teleport scalar extensions/SNI.
Tailscale's unused-token shape is represented without contacting a tailnet.

## Verification

On Linux x86_64 / CPython 3.12.12, the final affected cohort passes **1238 tests
in 30.34 seconds** with three workers. Performance/runtime-control cases are
explicitly outside this functional cohort. Ruff and formatting pass; strict
typing passes over 163 production files; phase validation passes.
Native help was generated with actual Python 3.12 and 3.13 interpreters; Python
3.14 produces the same help as the 3.13 snapshot. Fresh migration children never
import Textual or the Kubernetes SDK.

Both static site surfaces build and verify **41 pages, 1528 local links/assets
and 58 files**. The site regression cases pass; all 31 disposition controls pass
after enrolling the real added documents and the inherited startup evidence.
No site was published and no browser/provider qualification is inferred.

The exact issue diff covers **237/237 changed production lines (100%)** against
base `d9c8999`, without exclusions or threshold changes. Current coherent counts:

| Module | Lines | Branches |
| --- | --- | --- |
| CLI | 171/171 | 54/54 |
| Catalogue | 178/178 | 80/80 |
| Connection overrides | 99/99 | 54/54 |
| Session ownership | 68/68 | 14/14 |
| Basic policy | 27/27 | 14/14 |
| OIDC migration policy | 58/58 | 22/22 |
| Local migration rendering | 17/17 | 2/2 |

The two new deterministic credential modules join the 100% critical inventory.
The limited cohort covers **5860/17700 global lines (33.1073%)** and
**1260/5456 global branches (23.0938%)**, including unimported production code.
It is **not** a whole-package coverage pass. Full integrated global, runtime,
platform and package gates remain required before delivery.

Earlier evidence remains retained: an alias-producing test fixture initially
failed its extension-bound assertion; the corrected independent-object fixture
passes. A broader run exposed an accidental TLS/config state change, which was
restored, and an obsolete Basic-refusal scenario, now retained with a genuinely
invalid Basic username. The first corrected run retained a help snapshot failure;
both supported formatting snapshots were regenerated with real interpreters.
No failed observation was hidden or changed into a passing measurement.

Raw commands, original failures, final XML/JSON coverage, changed-line receipt,
source hashes and independently verified Argon reviews remain under
`artifacts/kubeconfig215/`. All production mtimes precede the final pytest start;
there were no source edits during that run. No real context, provider login,
publication, account, DNS or global configuration changed.

## Captured plugin output correction

An owned plugin reading its real staged Basic configuration reproduced an
unlabelled password leak in captured output. The pre-fix regression failed at
the password-absence assertion after successful authentication, mode-0600/0700
checks, output collection, file removal and child reaping. An earlier fixture
attempt was refused by the existing multiline-argument policy; it is retained
separately and is not counted as the reproduction.

The existing captured-value hints now include the prepared Basic password,
decoded credential pair, full header and bare base64. They come from the frozen
delegated configuration. A bare username is not added as a secret hint, including
when the password is empty. Existing bearer handling, output bounds, control
escaping and process/file ownership are unchanged. Foreground output still goes
directly to the terminal and is outside captured-output redaction.

The affected Linux / CPython 3.12.12 cohort passes **256 tests in 43.74 seconds**,
including ten real capture/background combinations covering Unicode and short
passwords, either empty credential half, and anonymous access. Each new case
checks both output streams, ordinary output, actual authentication, private-file
modes/removal and child reaping. Existing bearer, cancellation and UI plugin
contracts remain in the same passing cohort. The source and test hashes remained
unchanged throughout the run.

The plugin service covers **218/218 lines and 67/70 branches**; Basic policy
covers **27/27 lines and 14/14 branches**. All four changed executable lines are
covered. These are focused results, not whole-package or platform qualification;
real providers, native artifacts and macOS were not exercised. Original failures,
commands, input hashes and coverage remain under
`artifacts/issue215-basic-plugin/`.
