# Terminal compatibility

KubeRich runs in a local terminal, over SSH, or inside tmux. Its default container
shell stays inside the Textual interface. Explicit native tools, including Azure
login, temporarily receive the terminal and return to the workspace.

The minimum qualified workspace size is 40 columns by 12 rows. Use a UTF-8 locale
and a terminal advertising its actual capabilities. The automated tmux fixture
uses `-u` and `screen-256color`; its configuration is isolated from user settings.
Standard 16-color rendering and `NO_COLOR` input/navigation receive terminal
checks. This does not establish compatibility with every terminal emulator,
locale, Unicode font, or custom tmux configuration.

## Shutdown and reconnection

Normal exits, Ctrl+C, Ctrl+Q, external SIGTERM and external SIGHUP unwind owned
processes and streams. SIGTERM returns 143; SIGHUP returns 129. Native handoffs
restore foreground ownership and terminal attributes before returning. Embedded
shells own a separate PTY and reap their child when closed, including cancellation
while the pod preflight is still pending.

Losing SSH without a multiplexer revokes the remote terminal. KubeRich closes its
tasks and child processes, then exits 129; the SSH client normally returns 255.
The local SSH terminal can be restored, but a revoked remote TTY cannot receive
escape sequences or have its attributes read or restored. Evidence records this
as unavailable, rather than claiming remote restoration. Only captured output
descriptors still identifying that revoked TTY are redirected to `/dev/null`
during hangup. Live terminals, replaced descriptors and file/pipe output remain
untouched. This prevents failed buffered shutdown writes from changing the
process exit code to 120.

Inside tmux, losing SSH detaches the client and keeps the application and an open
embedded shell running. Reattaching to the same session restores the workspace;
normal shell return and application shutdown still close owned resources.

## Repeatable qualification

Development tests require `ssh`, `ssh-keygen`, `sshd` and `tmux`, in addition to
the locked Python development environment. These are test prerequisites, not
dependencies for an ordinary local KubeRich installation. Missing tools fail the
required suite explicitly. Hosted runners install them before testing.

```sh
uv sync --locked --group dev
uv run pytest tests/terminal/test_transports.py tests/terminal/test_shutdown.py tests/terminal/test_container_shell.py tests/terminal/test_handoff.py tests/unit/test_terminal_lease.py tests/unit/test_terminal_model.py
uv run pytest tests/packaging/test_distribution.py
```

Each transport fixture owns a loopback high-port SSH daemon, generated host/client
keys, pinned known-host file, private configuration directory and explicit tmux
socket. It disables password/PAM authentication, forwarding, ambient SSH agents,
user startup files and user SSH/tmux configuration. `StrictModes no` applies only
to this generated-key daemon because temporary-directory parents are writable;
the fixture directory is mode 0700 and private keys are mode 0600. It never
reconfigures a system SSH service or contacts a cluster outside its owned fixture.
tmux uses its own short mode-0700 temporary socket directory, so long macOS-style
test paths do not exceed Unix socket limits. Actual long-path trials exercise
this independently of unavailable macOS execution.
Loss tests terminate only a connection whose ancestry reaches that owned daemon.
An observing session owner forwards terminal signals to the actual application;
it does not immunize the application by inheriting ignored SIGHUP handlers.

Actual PTY output and separate inner/outer termios observations are retained in
`artifacts/terminal/*.ansi` and `*.json`. Fresh-wheel trials run the installed
entry point outside the checkout. Product fixes have regression witnesses for
external shutdown, private cursor queries, malformed CSI recovery and retained
normal/alternate buffer text after shrinking a rendered terminal.
Additional failing witnesses cover deferred header callbacks after view removal
and a stale queued resize event overriding the actual native TTY dimensions.

Linux results and tool versions are recorded in the issue-linked acceptance
report. macOS jobs and physical terminal-emulator/manual clipboard checks remain
unavailable or unperformed unless that report supplies actual results. Linux
evidence does not certify macOS. The complete hosted matrix remains a public
release gate in #40; broader environment/provider certification remains #87.

## References

- [Textual suspension](https://textual.textualize.io/guide/app/#suspending-your-app)
- [OpenSSH server configuration](https://man.openbsd.org/sshd_config)
- [tmux documentation](https://github.com/tmux/tmux/wiki/Getting-Started)
- [xterm control sequences](https://invisible-island.net/xterm/ctlseqs/ctlseqs.html)
- [Python exit cleanup behavior](https://docs.python.org/3.12/library/sys.html#sys.exit)
