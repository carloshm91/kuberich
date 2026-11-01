# Wayland clipboard

The native Wayland backend starts `wl-copy --foreground --type
text/plain;charset=utf-8` with literal arguments. Copied UTF-8 bytes travel only
on stdin. The existing 1 MiB native limit and 64 KiB terminal limit remain.
Replacement and application exit close the selection process. A normal late
helper exit is accepted; failed starts and late failures suggest checking
`wl-copy` or setting `KUBERICH_CLIPBOARD=osc52`.

Automatic detection keeps memory-only behavior for headless sessions and selects
OSC52 over SSH. Local macOS uses AppKit; other local sessions prefer
`WAYLAND_DISPLAY` before `DISPLAY`. Explicit `native` skips the SSH preference,
and explicit `osc52` selects the terminal. Automatic failure fallback retains
its terminal byte limit, while forced-native failures remain visible.

## Local verification

On Linux with CPython 3.12.12 and Textual 8.2.8:

```sh
uv run pytest tests/unit/test_clipboard.py tests/contract/test_clipboard.py \
  tests/contract/test_wayland_clipboard.py tests/ui/test_clipboard.py -n 2 \
  --cov=kuberich --cov-branch --cov-report=json --cov-report=xml
```

The focused selection passed **59 tests**, with one explicit hosted-macOS-only
clipboard skip. It measured **100% of 43 lines and 18 branches** in the critical
clipboard domain, and **100% of 50 lines and 20 branches** in the native service.
Coverage measured the full production package; this focused result does not
replace the full-package, other-critical-module or platform gates.

Temporary helper processes check exact arguments, stdin bytes, UTF-8, empty
text, inert terminal controls, PostScript/RTF-shaped plaintext and unchanged
newlines. They also check replacement, a cancelled waiter, process reaping,
repeated close, successful early/late exit, startup/late rejection, missing
helpers and rejection above the byte limit before a child starts. An inert
Textual driver checks automatic fallback, forced-native failure and oversize
fallback refusal for Wayland, X Window System and macOS. The existing Linux Xvfb test
still performs its separate synthetic X11 roundtrip.

The first hosted run exposed six macOS fixture failures: synthetic Linux sessions
had inherited the host platform. The corrected fixture scopes its platform only
to the application adapter and exercises all three native backends on every
host; Python, Textual and the native macOS control retain their actual platform.
The original failure remains in run `41280079738`; the corrected local selection
passed 59 tests with one explicit macOS-only skip in 17.32 seconds.

No developer clipboard, real Wayland compositor or Kubernetes context is used.
Fake-executable contracts establish invocation and lifetime behavior; they do
not certify a physical compositor or clipboard manager receiving the data.
Full supported-platform and package qualification remain the required PR and
release checks.

The invocation follows the upstream
[wl-clipboard manual](https://github.com/bugaevc/wl-clipboard/blob/master/data/wl-clipboard.1):
foreground mode keeps process ownership with the caller, while an explicit MIME
type avoids content guessing. KubeRich never reads clipboard contents to confirm
a copy.
