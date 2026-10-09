"""Compare terminal settings while retaining raw kernel observations."""

import sys

# Darwin tty.c sets this bit when returning to canonical mode and preserves it
# across tcsetattr. It describes queued input awaiting kernel processing.
DARWIN_PENDIN = 0x20000000


def restored_modes(before: object, after: object, *, system: str = sys.platform) -> bool:
    if (
        not isinstance(before, list)
        or not isinstance(after, list)
        or len(before) != 7
        or len(after) != 7
        or not isinstance(before[6], list)
        or not isinstance(after[6], list)
        or any(not isinstance(value, int) or isinstance(value, bool) for value in before[:6])
        or any(not isinstance(value, int) or isinstance(value, bool) for value in after[:6])
    ):
        return False
    first, second = list(before), list(after)
    if system == "darwin":
        first[3] &= ~DARWIN_PENDIN
        second[3] &= ~DARWIN_PENDIN
    return first == second
