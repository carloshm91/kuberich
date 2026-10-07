# Q02 #33 terminal qualification

This issue qualifies real local, SSH, tmux and SSH-to-tmux behavior on Linux.
The configured macOS matrix remains unavailable under the hosted Actions billing
block. Its actual execution is required before public release in #40; physical
terminal-emulator/clipboard and broader environment certification remain #61/#87.
No manual terminal or macOS result is claimed.

| Behavior | Actual terminal verification |
| --- | --- |
| Narrow windows, resize storms, Unicode paste, focus and keyboard return | `tests/terminal/test_transports.py` workspace cases on all three transports |
| Log pause/follow, first/last, search, copying redacted text, small-window help | Same suite, actual log transport cases; host clipboard receipt is not certified |
| Standard color and NO_COLOR keyboard/rendering | Same suite, explicit standard color system on all transports |
| Native child stdin/stderr, repeated return, Ctrl+C, missing executable, SIGHUP | Same suite and `tests/terminal/test_handoff.py` |
| Embedded stdin, fullscreen application, stdout/stderr Unicode, protocol queries | Same suite and `tests/terminal/test_container_shell.py` |
| Cancel while real pod preflight is blocked, then reopen successfully | Actual CLI early-close cases on local/SSH/tmux/SSH-tmux |
| SIGTERM/SIGHUP, process reaping, termios and control restoration | `tests/terminal/test_shutdown.py`, native/embedded signal cases |
| Actual SSH connection loss during workspace/native/embedded operation | Owned-daemon connection termination with ancestry validation |
| Preserve and reattach the same workspace and embedded child through SSH-to-tmux loss | Same suite, actual detach/reattach cases |
| Installed entry points outside the checkout | `tests/packaging/test_distribution.py`, native SSH and embedded SSH/SSH-tmux |
| Revoked output ownership and live-terminal restoration errors | `tests/unit/test_terminal_lease.py`; actual SSH loss supplies end-to-end evidence |
| Same-packet malformed recovery, origin/private cursor replies, rendered buffer shrink | `tests/unit/test_terminal_model.py` plus real embedded protocol cases |

See [terminal compatibility](../terminal-compatibility.md) for exact commands,
fixture prerequisites, supported behavior and lost-terminal limits. Remote TTY
revocation is recorded as unavailable inner termios; local termios remains
measured. Escape sequences cannot be delivered through a dead SSH connection.

## Qualification status

Full frozen-candidate Linux 3.12/3.13/3.14 qualification is recorded in the final
PR before merge. During implementation, independently failing witnesses exposed
external shutdown restoration, private cursor query/same-packet recovery and
rendered-buffer shrinking. Corrected terminal cases run against real PTYs;
synthetic API fixtures and fake kubectl programs do not claim cloud certification.

No version bump, tag, release, publication or visibility change is part of Q02.
