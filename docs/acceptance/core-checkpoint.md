# Core engineering checkpoint: D04 #40

Implementation base: `754d1a610931d13151c970366a38d398f5b30981`.
Qualification is in progress. These are private local test artifacts, not a
public release or a product version change.

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
Ubuntu 24.04, macOS 14 ARM64 and macOS 15 Intel. All three real host results remain
required; the opt-in test's ordinary-suite skip is not installation evidence.
The local tap fixture uses `kuberich/tap/kuberich`. It creates no public tap.

## Platform and runtime evidence

The complete six-source/four-native manual run on the implementation base is
[38114703984](https://github.com/carloshm91/kuberich/actions/runs/38114703984).
Its original terminal status and artifacts must be retained before qualification.
The earlier heartbeat failures remain recorded in the
[standalone acceptance evidence](standalone-executables.md); unchanged retries are
not fixes. D05's scoped renderer-cache correction was delivered in
[PR #181](https://github.com/carloshm91/kuberich/pull/181).

Before closing #40, retain the complete supported platform matrix, independent
coverage and critical gates, audited exact wheel/sdist, actual installer results,
scoped performance/PTY contracts and three consecutive owned-cluster/fault
rehearsals. Publication, public-channel activation and final version qualification
remain #89/#51. Real provider certification remains opt-in #87.
