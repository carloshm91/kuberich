"""Command-line entry point for the initial development package."""

import argparse
from collections.abc import Sequence
from importlib.metadata import version


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the supported CLI options and report the current development stage."""
    parser = argparse.ArgumentParser(
        prog="kubetrol",
        description="A Kubernetes terminal UI built with Python and Textual.",
        epilog="Development build: the terminal interface is not available yet.",
        allow_abbrev=False,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('kubetrol')}")
    parser.parse_args(argv)
    print("Kubetrol is installed. This development build supports --help and --version.")
    print("The terminal interface is not available yet.")
    return 0
