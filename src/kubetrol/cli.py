"""Local configuration/diagnostics CLI; Kubernetes connections arrive separately."""

import argparse
import json
import os
import platform
import sys
from collections.abc import Sequence
from importlib.metadata import version
from typing import NoReturn

from kubetrol.config.paths import config_location, log_location
from kubetrol.config.schema import ConfigDocument, resolve_settings
from kubetrol.config.store import read_config, write_config
from kubetrol.diagnostics.logging import diagnostic_logging
from kubetrol.diagnostics.redaction import sanitize_text
from kubetrol.errors import AppError, ExitCode
from kubetrol.ui.launch import run_terminal


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # argparse normally echoes arbitrary arguments, which may contain credentials.
        self.print_usage(sys.stderr)
        self.exit(2, "kubetrol: invalid command line; run kubetrol --help.\n")


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="kubetrol",
        description="A Kubernetes terminal UI built with Python and Textual.",
        epilog="Terminal window preview: Kubernetes connections are not available yet.",
        allow_abbrev=False,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('kubetrol')}")
    parser.add_argument("--config", help="Kubetrol preferences YAML (separate from kubeconfig)")
    parser.add_argument(
        "--log-file", "--logFile", dest="log_file", help="local diagnostic log path"
    )
    parser.add_argument(
        "--log-level",
        "--logLevel",
        "-l",
        dest="log_level",
        help="DEBUG, INFO, WARNING, ERROR, or CRITICAL",
    )
    commands = parser.add_subparsers(dest="command")
    commands.add_parser(
        "info", help="show safe local paths, preferences and installed versions", allow_abbrev=False
    )
    config = commands.add_parser(
        "config", help="initialize or validate local preferences", allow_abbrev=False
    )
    operations = config.add_subparsers(dest="operation", required=True)
    operations.add_parser(
        "init", help="create defaults without overwriting existing files", allow_abbrev=False
    )
    operations.add_parser(
        "check", help="validate effective preferences without writing files", allow_abbrev=False
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Keep filesystem/debug details away from terminal output and return stable codes."""
    arguments = _parser().parse_args(argv)
    try:
        location = config_location(arguments.config, os.environ)
        if arguments.command == "config" and arguments.operation == "init":
            if arguments.log_file is not None or arguments.log_level is not None:
                raise AppError("Log flags are runtime overrides; omit them for config init.")
            write_config(location.path, ConfigDocument())
            print("Created default Kubetrol preferences. Run kubetrol info to see local paths.")
            return 0
        document = read_config(location.path, missing_ok=not location.explicit)
        overrides = {
            key: value
            for key, value in {
                "log_file": arguments.log_file,
                "log_level": arguments.log_level,
            }.items()
            if value is not None
        }
        settings = resolve_settings(document, os.environ, overrides)
        log_file = log_location(
            settings,
            location.path,
            from_file="log_file" not in overrides and "KUBETROL_LOG_FILE" not in os.environ,
        )
        if arguments.command == "info":
            print(
                json.dumps(
                    {
                        "version": version("kubetrol"),
                        "python": platform.python_version(),
                        "platform": sys.platform,
                        "dependencies": {
                            name: version(name)
                            for name in ("textual", "kubernetes-asyncio", "platformdirs", "pyyaml")
                        },
                        "config_file": sanitize_text(str(location.path)),
                        "log_file": sanitize_text(str(log_file)),
                        "config_exists": location.path.exists(),
                        "migration_pending": document.migrated,
                        "unknown_fields": len(document.unknown),
                        "preferences": {
                            key: value
                            for key, value in settings.to_mapping().items()
                            if key != "log_file"
                        },
                        "terminal_ui_available": True,
                        "cluster_connected": False,
                    },
                    indent=2,
                )
            )
        elif arguments.command == "config":
            print("Kubetrol preferences are valid. No files were changed.")
        else:
            with diagnostic_logging(log_file, settings.log_level) as logger:
                try:
                    logger.debug("Launching terminal interface; no cluster connection.")
                    run_terminal(settings, logger)
                except Exception:
                    logger.debug("Terminal launch failed.", exc_info=True)
                    raise
        return 0
    except KeyboardInterrupt:
        print("kubetrol: interrupted.", file=sys.stderr)
        return ExitCode.INTERRUPTED
    except AppError as error:
        print(f"kubetrol: {sanitize_text(str(error))}", file=sys.stderr)
        return error.code
    except Exception:
        print(
            "kubetrol: unexpected local failure; run kubetrol info and report the problem.",
            file=sys.stderr,
        )
        return ExitCode.FAILURE
