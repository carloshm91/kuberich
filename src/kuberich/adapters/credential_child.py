"""Private stdlib-only credential launcher; never print captured credentials."""

import json
import os
import stat
import sys
from collections.abc import Sequence
from pathlib import Path


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    descriptor = -1
    try:
        if len(arguments) != 1 or not Path(arguments[0]).is_absolute():
            raise ValueError
        descriptor = os.open(arguments[0], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_size > 1048576
        ):
            raise ValueError
        with os.fdopen(descriptor, encoding="utf-8", closefd=False) as stream:
            data = json.loads(stream.read(1048577))
        if not isinstance(data, dict) or set(data) != {"argv", "environment", "directory"}:
            raise ValueError
        command, environment, directory = data["argv"], data["environment"], data["directory"]
        if (
            not isinstance(command, list)
            or not 1 <= len(command) <= 257
            or any(not isinstance(value, str) or "\0" in value for value in command)
            or not Path(command[0]).is_absolute()
            or not isinstance(directory, str)
            or not Path(directory).is_absolute()
            or not isinstance(environment, dict)
            or len(environment) > 4096
            or any(
                not key or "=" in key or "\0" in key or not isinstance(value, str) or "\0" in value
                for key, value in environment.items()
            )
        ):
            raise ValueError
        # client-go owns this one dynamic field; plugin cwd/profile/PATH must
        # never retarget the original credential helper's captured identity.
        environment.pop("KUBERNETES_EXEC_INFO", None)
        if "KUBERNETES_EXEC_INFO" in os.environ:
            environment["KUBERNETES_EXEC_INFO"] = os.environ["KUBERNETES_EXEC_INFO"]
        os.chdir(directory)
        os.execve(command[0], command, environment)
        return 0
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        os.write(2, b"Cannot start the captured credential helper.\n")
        return 126
    finally:
        if descriptor >= 0:
            os.close(descriptor)


if __name__ == "__main__":
    sys.exit(main())
