# D01 #34 distribution qualification

This task prepares local wheel/source artifacts and verifies actual installations.
It publishes no package, tag, release, Homebrew tap or website and changes no
repository visibility. Installed version remains `0.0.1.dev0`.

| Acceptance behavior | Verification |
| --- | --- |
| Complete runtime assets and metadata/license/version | `tests/packaging/test_artifacts.py`, whole archive payload and metadata assertions |
| No tests, development scripts, caches or undeclared private files | Same suite; actual synthetic file traps in a copied build tree |
| Rebuild from sdist | Same suite; identical wheel member payloads |
| Real uv tool and pipx install of wheel and sdist | `tests/packaging/test_installers.py`, independent pip backend for pipx |
| Exposed PATH command and module origin outside checkout | Same suite, actual installed CLI plus isolated `python -I` probe |
| Actual installed UI navigation/shell and terminal restoration | Same suite plus existing `tests/packaging/test_distribution.py` |
| Uninstall and installer timeout cleanup | Actual managed uninstall, process-group timeout and child reaping |

Exact commands and local content policy are in
[distribution](../distribution.md). All installers use owned temporary tool,
binary, cache/configuration directories and an explicit matrix interpreter.
Synthetic APIs and fake kubectl fixtures qualify local behavior, not a real
cloud-provider environment.

## Qualification status

Full frozen-candidate Linux 3.12/3.13/3.14 results and measured tool/dependency
versions are recorded before merge. Hosted/macOS execution remains unavailable
under the billing block and is required before public release in #40.
No unexecuted platform or public installation result is claimed.
