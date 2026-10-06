# Native shell screen transition evidence

Qualified on Linux on 2026-10-06 for maintainer feedback #119 / PR #120.
Complete locked CPython matrices and actual Kubernetes trials tested frozen
commit `7c9549a34e7a1afe6e6c90283c464f386d168493`. Final documentation preserves these trees:

- `src`: `64c2d308ba08dffcc9a362ad98a8d4e073799b20`
- `tests`: `dcba88b8fa6bbf371f9f11811baa72349bb851da`
- `scripts`: `f1db7f7f01d6fcd67731ff7fc1c712ff5d5d0b2f`

## Measured gates

| Actual CPython | Tests | Production lines | Production branches | Changed lines |
| --- | ---: | ---: | ---: | ---: |
| 3.12.12 | 1,467 passed | 4,977 / 4,998 (99.58%) | 1,390 / 1,418 (98.03%) | 25 / 25 (100%) |
| 3.13.12 | 1,467 passed | 4,977 / 4,998 (99.58%) | 1,390 / 1,418 (98.03%) | 25 / 25 (100%) |
| 3.14.3 | 1,467 passed | 4,890 / 4,911 (99.57%) | 1,390 / 1,418 (98.03%) | 25 / 25 (100%) |

Each environment uses an explicit interpreter on every uv invocation. Coverage
includes every production module, with independent line/branch floors and no
exclusions. All **24 critical modules** reach 100% lines and branches, including
the new shell heading rules. Ruff/formatting, strict mypy, plan validation,
coverage/diff gates, wheel/sdist builds and Twine pass on each interpreter.
Packaging tests rebuild the sdist and exercise fresh installations.

Each interpreter retains **35 UI SVGs and 58 real-PTY restoration summaries**.
All summaries verify exact original terminal attributes, alternate-screen closure,
cursor restoration and disabled reporting modes. The owned kind trial adds four
actual shell/terminal summaries on CPython 3.12.

## Resulting experience

Before this correction, suspending Textual exposed the original launch terminal,
so the image's `$` prompt appeared below `uv run kubetrol`. Selected-container
shells now clear the visible screen and begin with:

```text
Kubetrol shell | exit to return
Context: selected-context
Pod: namespace/pod
Container: selected-container

```

The image's actual prompt follows. Target lines are literal, redacted and clipped
to current terminal cell width (at most 160 cells). The heading appears once;
the remote program owns the whole terminal and can overwrite it. It is not a
reserved header or a replacement prompt. Kubetrol sends no scrollback-erasure
control; already stored scrollback is separate from the visible screen it clears.

Existing read-only/current-target checks precede suspension. The terminal lease
presents the heading before child startup and drains partial writes. A failed
write yields safe feedback after normal lease restoration and Textual resumption.
Generic handoffs keep their existing behavior. Explicit argv/credentials/scoping,
private staged-file cleanup and retained container/pod return remain qualified.

## Behavioral and real-terminal checks

Six heading cases cover zero/narrow/ordinary/large widths, long Unicode names,
literal markup and credential-looking context names. Terminal write checks cover
partial delivery, no-progress writes and OSError without exposing raw messages.
Three handoff cases cover selected-target presentation before child startup,
presentation failure with lease/driver restoration, and generic exec without a
selected target. The existing failure/cancellation/signal cases still pass.

The 18 source console/module shell scenarios and the fresh-wheel trial now assert
the clear-plus-heading sequence occurs before the child's first output, carries
the captured context/namespace/pod/container and emits no scrollback erasure.
Read-only and deleted-target cases assert no shell heading or child is launched.
Keyboard input, resize, Ctrl+C, fullscreen operation, repeated return, failures
and SIGTERM/exit 143 continue to pass.

Four actual Kubernetes CLI trials create/delete only their owned random kind
cluster and fixture namespace/pod/service account. Each verifies the clean entry
and correct captured heading, then exercises default/configured/missing image
shells and real pods/exec RBAC denial. The success case uses two containers,
source-configuration pinning, BusyBox vi with resize, remote input/stty,
interruption and repeated return. The pinned images and SHA-256-verified matching
kubectl are described in [the shell guide](../container-shell.md). Every terminal
is restored, and the owned cluster is deleted before the command exits.

## Reproduce and scope

Use the [quality commands](../quality.md) in isolated CPython 3.12.12, 3.13.12
and 3.14.3 environments with explicit `--python`. After merge, compare changed
lines against base `1966b2f7e65d542bc6a50d39cd1f607655100fd7`. The real trial is:

```sh
uv run --locked --python 3.12 python -m scripts.verify_shell_kind --kind /path/to/kind --kubectl /path/to/kubectl
```

[Current maintainer trial](../first-preview.md#selected-container-shell-s04-32--current-trial)
uses the same pod → container → `s` → `exit` flow. Verify the launch command no
longer appears above the remote prompt and the heading identifies your selection.

Evidence is retained at `/tmp/kubetrol-119-evidence`: per-interpreter logs,
coverage/diff reports, candidate packages, SVGs and PTY transcripts/summaries,
plus kind records and source/final-head hosted metadata. The focused pre-matrix
19-case terminal/install run is retained separately. Temporary evidence can be
regenerated.

Hosted Actions cannot execute steps under the account payment/spending-limit
restriction. Current-head DCO and final hosted job/annotation evidence are
verified before the authorized local-workflow merge; true hosted failure status
is preserved. Linux evidence does not establish macOS or SSH/tmux qualification,
which remains required before public release. Complete K9s parity is not claimed.
No release, version bump, package publication or visibility change occurs.
