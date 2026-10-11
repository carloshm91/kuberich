# Core engineering checkpoint: D04 #40

Implementation base: `754d1a610931d13151c970366a38d398f5b30981`.
Qualification completed at main `a611243a9057adf134f134682cd56d52d1a9829b`;
#40 closed on 2026-10-11. These are unpublished test artifacts, not a public
release or a product version change.

The first complete local round passed 992 contracts and all 13 current owned-kind
rehearsals. Round two retained a failure in the CoreDNS log evidence assertion:
the last ten lines did not include its startup banner. The verifier now checks
the banner after requesting all retained container logs; timestamp/tail, since,
follow cancellation and previous-log assertions remain required. Real-HTTP
positive/negative regression cases cover a truncated tail and an absent banner.
The original is `artifacts/core40/consecutive-v1/run-2-contexts.log`. The corrected
three-round sequence passed 992 contracts and nine core rehearsals per round at
`3aced7891a6c94d14d0f3360722f0eff0c5a0e23`, whose complete tree matches the
qualified main commit. This is three repetitions of the core scope; the final
phase must repeat all thirteen current rehearsals. Original results are
`artifacts/core40/consecutive-core-v2/results.json`, SHA-256
`ecceba17c315fd4e6a7bc7799b6253b54044ebcd0604c3bdd0a59294f5e0380d`.

## Actual Python manager upgrades

The local CPython 3.12 run passed both manager cases in **55.70 seconds**:

```sh
uv run pytest -q --tb=short tests/packaging/test_upgrades.py
```

Each case builds two immutable wheels with identical application payloads and
different development versions. A hashed, locked wheelhouse initially exposes
only the first wheel. The normal `uv tool upgrade` or `pipx upgrade` first retains
that version, then installs the newer version after it becomes available.
Neither case uses forced reinstallation. Both upgraded executables run the real
owned-API navigation and interactive-shell PTY trials outside the checkout.
Preferences and an owned caller-kubeconfig sentinel remain byte-identical; normal
uninstall removes the executable. Original receipts are retained as
`artifacts/packaging/{uv,pipx}-version-upgrade.json`, with PTY evidence under
`artifacts/terminal/upgraded-*`. The raw local log is
`artifacts/core40/installer-version-upgrades-v1.log`.

## Homebrew source candidates

The actual audited source-only RC/formula guard passed locally in **81.13 seconds**:

```sh
uv run pytest -q --tb=short tests/packaging/test_homebrew_formula.py::test_audited_source_only_rc_can_qualify_local_brew_but_cannot_be_public
```

The private generator accepts the exact local sdist URL of a canonical RC. It
continues to reject public generation from a source-only developer bundle and
rejects unrelated local URLs. No fabricated native report is needed for this
source-formula trial. Public release verification still requires all four actual
qualified native archives, audits and provenance.

The separate **Native installation qualification** workflow exercises actual
Homebrew source install, formula style/online audit/test, normal version upgrade,
upgraded navigation/shell, caller configuration invariance and removal on
Ubuntu 24.04, macOS 14 ARM64 and macOS 15 Intel. All three passed in
[38116976820](https://github.com/carloshm91/kuberich/actions/runs/38116976820);
the opt-in test's ordinary-suite skip is not installation evidence.
The local tap fixture uses `kuberich/tap/kuberich`. It creates no public tap.

## Platform and runtime evidence

The complete six-source/four-native manual run on exact main is
[38119231452](https://github.com/carloshm91/kuberich/actions/runs/38119231452).
All jobs passed, including all thirteen current owned rehearsals once. An
independent reader checked the original ten downloaded artifact ZIP digests,
six audit/coverage sets, original wheel/sdist and four actual native archives,
then enrolled those same native bytes into an unpublished development bundle.
Line coverage ranged from 99.0788% to 99.1101%; branch coverage from 96.8664%
to 97.0038%. All 44 designated critical modules had 100% of both. That PR changed
no executable production lines, so changed-line coverage was not applicable.
Originals and `independent-main-review.json` remain under
`artifacts/core40/run-38119231452-originals`.

The earlier [38114703984](https://github.com/carloshm91/kuberich/actions/runs/38114703984)
failed a dependency-audit timeout and an owned CrashLoop fixture observation;
its original failures remain retained. They do not qualify a platform or prove
a production bug was fixed.
The earlier heartbeat failures remain recorded in the
[standalone acceptance evidence](standalone-executables.md); unchanged retries are
not fixes. D05's scoped renderer-cache correction was delivered in
[PR #181](https://github.com/carloshm91/kuberich/pull/181).

The complete matrix, independent coverage, audited bytes, actual installer
results and scoped repetitions qualified #40. Publication, public-channel
activation and final version qualification remain #89/#51. Real provider
certification remains opt-in #87.
