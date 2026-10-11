"""Isolated stdlib-only launcher: acquire the child PTY, then replace this process."""

import fcntl
import os
import sys
import termios
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None, *, environment: dict[str, str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        os.tcsetpgrp(0, os.getpgrp())
        if environment is None:
            os.execv(arguments[0], arguments)
        else:
            os.execve(arguments[0], arguments, environment)
    except (OSError, IndexError):
        os.write(2, b"Cannot start the interactive executable.\n")
        return 126


if __name__ == "__main__":
    sys.exit(main())
