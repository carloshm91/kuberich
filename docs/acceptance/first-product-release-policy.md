# First product release policy: #154

## Delivered scope

The agreed first public product is 1.0.0. Source opening #155 is already delivered;
package/tap/registry/site/DNS publication remains separate concrete owner approval
in #89. The project stays private and metadata stays `0.0.1.dev0`.

Six intermediate engineering gates retain every original dependency and actual
native/exact-artifact/install/terminal/security/coverage duty. Feature-first
execution defers their final qualification without declaring it complete.
Dedicated distribution/platform/performance qualification precedes those gates,
Q05/Q06 and #89. Expanded docs #90/#91 now follow #89; initial site qualification
and GitHub Actions → Cloudflare Pages deployment remain in #89.

Publication guards reject 0.x stable/RC versions before remote tag/asset/tap or
preflight requests. Offline canonical and explicitly local-only development
preparation still work. Release readiness checks transitive feature/gate
prerequisites and additional launch issues, excluding the open publication gate
and later expanded docs. This also fixes parsing the real plan's non-versioned
`Later: documentation website` milestone.

## Measured local evidence

- `uv run --locked --python 3.12 pytest -q tests/quality/test_release_policy.py tests/quality/test_release_transport.py tests/quality/test_homebrew.py`: **145 passed**, 12.47 seconds. Real owned loopback HTTP/Git witnesses prove no request, tag, upload or tap branch for rejected 0.x versions; existing immutable retry, downgrade and protected-dispatch contracts remain.
- The real 79-task plan passes readiness only when transitive and extra prerequisites are closed. Open #40/#47/#124/#154 each blocks it; closing only final gates cannot bypass features. The plan includes the later non-versioned documentation milestone.
- `python scripts/validate_plan.py`: 12 epics, 79 tasks, 64 capability families and 26 CLI flags. Validate publication policy against actual tooling constants, complete disjoint execution phases, dependency order and local links.
- Ruff check/format and strict application/release/Homebrew mypy pass.
- `uv run --locked --python 3.12 python -m scripts.build_site` and `uv run --locked --python 3.12 python -m scripts.check_site`: 39 pages, 1,154 local references/assets and 54 files checked. The generated version remains `0.0.1.dev0`.

The local logs and archived before/after issue payloads are under ignored
`artifacts/release-policy-154/`. Initial fixture migration failures are retained;
public-proposal fixtures now use 1.0.x while explicit offline 0.x parser tests
remain. No failures are hidden by skips or exclusions.

## Live roadmap evidence

Updated ten open issue titles/bodies (#40/#49/#51/#65/#75/#82/#86/#89/#90/#91)
and eight milestone descriptions without closing gates or changing their
milestone identity. Preserved all real feature/qualification prerequisites.
#89 adds native dependencies on #124/#149/#150/#154/#155/#157 alongside its
original #86/#87/#88. #90 replaces its superseded direct #51 dependency with #89,
which still requires #51 transitively, and retains #39.

## Delivery checks and limits

The issue-linked PR retains actual hosted Repository checks, DCO and configured
four-environment application quality, including native macOS. Its final PR/issue
records the exact candidate and complete results before autonomous merge.
No application source changes are made, so application changed-line coverage is
N/A; existing independent 90% line/branch and 100% critical gates still run.
Package tests build/install/audit an actual canonical 1.0.0rc1 in an owned
fixture, without changing development metadata or publishing it.

This policy task does not establish final release qualification, PyPI ownership,
OIDC publication, enforced release protection, actual public tap/install trials,
Cloudflare deployment/TLS/DNS or provider certification. Those remain their
explicit engineering and #89/Q05 acceptance work. No package, site, tag, release,
registry, DNS or visibility mutation is part of #154.
