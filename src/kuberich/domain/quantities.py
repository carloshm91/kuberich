"""Bounded Kubernetes quantity arithmetic, independent of display units."""

import re
from decimal import Decimal, localcontext

_QUANTITY = re.compile(r"([+]?(?:\d+(?:\.\d*)?|\.\d+))([numkKMGTPE]|[KMGTPE]i|[eE][+-]?\d+)?")
_SCALES = {
    "": 0,
    "n": -9,
    "u": -6,
    "m": -3,
    "k": 3,
    "K": 3,
    "M": 6,
    "G": 9,
    "T": 12,
    "P": 15,
    "E": 18,
}


def parse_quantity(value: object) -> Decimal | None:
    """Parse nonnegative Kubernetes quantities with bounded precision and exponents."""
    if not isinstance(value, str) or len(value) > 64:
        return None
    match = _QUANTITY.fullmatch(value)
    if match is None:
        return None
    number, suffix = match.groups()
    suffix = suffix or ""
    if suffix.endswith("i"):
        scale = Decimal(1024) ** ("KMGTPE".index(suffix[0]) + 1)
    else:
        exponent = (
            int(suffix[1:])
            if suffix.startswith(("e", "E")) and len(suffix) > 1
            else _SCALES[suffix]
        )
        if abs(exponent) > 30:
            return None
        scale = Decimal(10) ** exponent
    with localcontext() as context:
        context.prec = 100
        return Decimal(number) * scale
