"""The versioned jumps preference extension."""

from kuberich.config.schema import ConfigDocument
from kuberich.domain.jumps import Jumps, parse_jumps


def jumps_from(document: ConfigDocument) -> Jumps:
    return parse_jumps(document.extensions["jumps"]) if "jumps" in document.extensions else Jumps()
