# D02 #36 immutable release pipeline qualification

The maintainer-dispatched workflow validates main, owner identity, milestone
readiness, version, DCO, real hosted checks, protected main and required environment
review. It consumes the successful quality run's tested packages without rebuilding.
Publication permissions and OIDC are confined to the approved publisher job.
No package, production tag, GitHub Release or attestation was published here.

## Executed behavior

- Owned HTTP qualification checks enforce the actual API responses, source PR
  tree, DCO App identity, latest run attempt, every Linux/macOS job, retained
  artifact, repository visibility and protected environment.
- Actual bare Git annotated-tag creation refuses a different or lightweight tag;
  a concurrent creation race cannot replace the existing ref.
- Actual HTTP asset uploads fail after a partial upload and retry only the missing
  original bytes. Wrong digests keep the release draft; completed releases reject
  changed assets. Redirects/error bodies cannot disclose a synthetic bearer token.
- Actual wheel/sdist metadata, archives, fresh audits, notices and bundle digests
  are verified. Missing, extra, altered, symlinked and rehashed-invalid evidence fails.
- An owned source copy builds `0.0.1rc1`, audits it, prepares/verifies its canonical
  bundle and installs its actual wheel outside the checkout. The installed CLI
  reports that version. Source changes fail subsequent qualification.
- Development candidates cannot enter tag/publication commands. A read-only check
  against the real private repository refuses qualification, with zero writes.
- The dispatch commit must equal `GITHUB_SHA`, preserving the source identity of
  the default signed provenance. An older requested ancestor is rejected.

## Measured Linux evidence, 2026-10-07

The complete first-pass matrix froze `4b2fcc2434a6a8c6f318f70af7ea56d4261c9095`
against base `48a267b6b7de7f65146dbaf2ff1a10a0d9c95d46`.

| CPython | Complete passing tests | Production lines | Production branches |
| --- | --- | --- | --- |
| 3.12.12 | 2,217 | 6419/6451 (99.50%) | 1891/1936 (97.68%) |
| 3.13.12 | 2,217 | 6419/6451 (99.50%) | 1891/1936 (97.68%) |
| 3.14.3 | 2,217 | 6312/6344 (99.50%) | 1891/1936 (97.68%) |

Each passed all 29 critical modules at 100% lines/branches, lint/format, strict
application/release/gate/provider types, plan validation, package build/Twine and
security verification. Each retained 59 UI SVGs and 140 terminal summaries.
Changed executable application lines: N/A (0); the application source tree is
unchanged throughout this issue.

A later release-only fix froze `629570573bacbb1fd6481383f355530eaf913a99`:
commit/event equality and complete clean policy-input checking. The relevant
release checks were repeated per minor after that fix; the original full matrix
is not relabeled as a full run on the final scripts. No application code changed.
All 103 final policy/owned-transport/source tests pass per minor, with strict
80-file mypy, Ruff and plan checks. An offline build from cached pinned Hatchling
1.32.4 and explicit-minor Twine pass on all three; the wheel/sdist hashes equal
the corresponding first-pass audited bytes. Repeating the additional 17 packaging
checks on the release-only fix encountered a real PyPI timeout after 101 passing
policy/transport tests. That attempt is not successful packaging evidence; original
canonical-RC/bundle/install evidence belongs to the completed first-pass matrix.
The final evidence-document commit preserves executable/test/workflow trees and
package inputs.

## Commands and limitations

The full matrix used the commands in [dependency qualification](dependency-security.md),
adding strict mypy over `scripts/release.py scripts/release_policy.py`.
The focused final check is:

```sh
uv run --locked --python 3.12 pytest -x tests/quality/test_release_policy.py tests/quality/test_release_transport.py tests/packaging/test_release_candidate.py
uv build --offline --python 3.12
uv run --locked --python 3.12 twine check dist/*
uv run --locked --python 3.12 python -m scripts.check_supply_chain --verify
```

Repeat for 3.13 and 3.14. Raw commands, logs, coverage, security sidecars, artifacts,
local canonical RC, private-repository refusal and hosted annotations are retained
in `/tmp/kubetrol-36-evidence`. Failed network attempts remain separate evidence,
never counted as successful checks.

macOS/arm64, hosted dispatch, TestPyPI, live OIDC attestation, PyPI ownership and
public channel qualification remain D04 #40. Current private-plan main protection
returns 403 and required environment reviewers are unavailable; these gates must
be configured and actually pass before publication. The temporary local merge
workflow does not bypass any release gate. See [release pipeline](../release-pipeline.md)
for setup, exact-source retry and patch/yank recovery.
