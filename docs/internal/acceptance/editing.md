# M02 #44 acceptance evidence

The selected-resource `:edit` / Shift+E action captures context/scope/name/UID,
defaults to Cancel and requires explicit trusted-local-editor disclosure before
creating a full-manifest draft. Editor argv is immutable, quoted and shell-free.
Owned drafts start with directory/file modes 0700/0600, use bounded no-follow
reads and are removed before form return or captured client cleanup.

Changed JSON-compatible YAML produces an immutable conditional structural patch
and a separately redacted diff; placeholders never enter request values.
Formatting-only edits, failed/cancelled editors and invalid/identity-changing
manifests cannot send a patch. Manual Validate uses strict server dry-run without
persistence. Separate Apply requires the exact validated intent and one-use
confirmation; the shared owner revalidates and retains public/uncertain outcomes.
A concurrent version or replacement UID requires a fresh edit; no overwrite,
automatic merge or replay is offered. Secret full-manifest access remains #55.

## Final Linux qualification

Production was frozen at `95286b8345ee685f4069e99aef728499acc5af5a`; its `src`
tree is `12015e1e54428cae3b6859c541300c28dfcd01b1`. The final test-only correction
is `21882704d587180e421eafc300182c4d5b059603`, with the same production tree and
tests tree `4b502d0fac79de9fc14a2ef271f0a56afd9e383d`. All complete final suites
passed on that exact production and test tree:

| Linux interpreter | Tests | Duration | Production lines | Production branches |
| --- | --- | --- | --- | --- |
| CPython 3.12.12 | 2,836 passed | 1,986.73 s | 8,297/8,351 (99.3534%) | 2,335/2,396 (97.4541%) |
| CPython 3.13.12 | 2,836 passed | 1,438.14 s | 8,295/8,351 (99.3294%) | 2,333/2,396 (97.3706%) |
| CPython 3.14.3 | 2,836 passed | 1,037.02 s | 8,147/8,202 (99.3294%) | 2,334/2,396 (97.4124%) |

Each independent gate includes all 87 production modules, with no exclusions.
All 33 designated critical modules passed 100% line and branch gates, including
all 114 executable lines and 40 branches of `domain/editing.py`. All four new
editor modules reached 100% lines and branches in each full suite. Changed-line
coverage passed at 428/431 (99.3039%) against
`a54ef97f891005acb565bc426be8b78554e0bdfd` on every interpreter.

The complete command uses the selected interpreter explicitly:

```sh
uv sync --locked --python 3.12 --group dev
uv run --locked --python 3.12 pytest --cov=kubetrol --cov-branch --cov-report=xml:/tmp/kubetrol-44-evidence/py312-final.xml --cov-report=json:/tmp/kubetrol-44-evidence/py312-final.json
uv run --locked --python 3.12 python scripts/check_coverage.py /tmp/kubetrol-44-evidence/py312-final.json
uv run --locked --python 3.12 diff-cover /tmp/kubetrol-44-evidence/py312-final.xml --compare-branch a54ef97f891005acb565bc426be8b78554e0bdfd --fail-under 90 --ignore-staged --ignore-unstaged --total-percent-float --format json:/tmp/kubetrol-44-evidence/py312-final-diff.json
```

The corresponding 3.13/3.14 commands use `py313`/`py314` evidence filenames.
Ruff passed, formatting checked 341 Python files, strict mypy checked 103 files,
and plan, whitespace and actionlint checks passed. Actionlint's optional external
ShellCheck/Pyflakes integrations were disabled; their execution is not claimed.
The frozen wheel/sdist passed build and Twine validation. Separate locked and
fresh installed-runtime supply-chain audits each inventoried 27 dependencies,
with no known advisories or exceptions; provenance verification passed.
Final delivery artifacts are rebuilt and audited after the documentation commit,
with their exact identity recorded in the PR.

Contracts use actual files and owned HTTP/TLS to verify dry-run versus persistence,
captured token/impersonation, exact bodies, RBAC/error responses, UID/version/scope
conflicts and proof invalidation. Held reads/file workers exercise cancellation,
repeat cleanup, creation discard and drain before SDK shutdown. Malformed YAML
and server error payloads remain absent from public status/history.

Pilot covers 40×12 and 100×30, default Cancel, local disclosure, redacted preview,
dry-run, separate Apply, read-only and held read/creation under F4/Escape/exit.
Actual foreground-editor PTYs qualify source success/no-op/failure/malformed/
Ctrl+C and fresh-wheel console/module success outside the checkout. Each verifies
native terminal/job control, restoration, 40-column resizing and file removal.

## Actual disposable Kubernetes

```sh
uv run python -m scripts.verify_editing_kind --kind /tmp/kubetrol-tools/kind --evidence /tmp/kubetrol-44-evidence/kind.json
uv run python -m scripts.verify_mutations_kind --kind /tmp/kubetrol-tools/kind --evidence /tmp/kubetrol-44-evidence/mutations-kind-regression.json
```

The M02 verifier passed 12 checks on owned Kubernetes 1.36.4: permissions,
unchanged draft/version, non-persisting dry-run, exact Apply, preservation,
proof reuse refusal, concurrent-version refusal, strict unknown-field rejection,
actual dry-run PATCH denial for a get-only user, same-name replacement refusal,
file cleanup and caller configuration invariance. Its owned cluster was deleted
and absence verified. M01 regression passed all eight actual annotation/RBAC/
atomic-precondition checks on a separate owned cluster, also deleted. Neither
trial used the maintainer's active context or a cloud provider.

## Corrected trials and limits

Native PTYs caught disclosure toggles being delivered after priority focus moves
when Space/Tab/Enter arrived in one packet. Disclosure now uses a scoped priority
binding before focus changes; rapid native input passed. Form close initially
painted the table before asynchronous unmount file cleanup. Cancel/Escape now
wait for owned cleanup before dismissing; pending annotation forms use the same
ordering. Intermediate failed trials remain in raw evidence and are not final
qualification. The original complete suites passed 2,836 cases on Python 3.12
and 3.14. Python 3.13 caught a native tmux observer race: the probe key sampled
80×25 before the actual resize arrived, leaving a stale witness even after
the display reached 100×30. The test now repaints the same key counter after
that real resize. The original failed control is retained; ten focused corrected
repetitions and all 59 handoff/transport/package cases passed on both Python
3.13 and 3.14. All three complete suites passed on that final test tree;
the correction does not change production code or relax restoration assertions.

Native macOS and hosted release qualification remain unavailable under the
account Actions block. Arbitrary external editor backups/history, secure erasure,
SIGKILL, older server/admission versions and cloud certification are outside this
measured scope. See [editor behavior](../editing.md). No tag, public repository,
release or package is published.

Raw evidence: `/tmp/kubetrol-44-evidence` (local, rather than durable hosted artifacts).
