"""Isolated stdlib-only launcher: acquire the child PTY, then replace this process."""

import fcntl
import os
import sys
import termios


def main() -> int:
    try:
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        os.tcsetpgrp(0, os.getpgrp())
        os.execv(sys.argv[1], sys.argv[1:])
    except (OSError, IndexError):
        os.write(2, b"Cannot start the interactive executable.\n")
        return 126


if __name__ == "__main__":
    sys.exit(main())
