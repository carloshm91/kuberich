"""Local configuration/diagnostics CLI; Kubernetes connections arrive separately."""

import argparse
import json
import os
import platform
import sys
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path
from typing import NoReturn

from platformdirs import user_data_path

from kuberich.config.launch import CONNECTION_OPTIONS, PENDING_OPTIONS, require_available
from kuberich.config.paths import config_location, log_location
from kuberich.config.schema import ConfigDocument, resolve_settings
from kuberich.config.store import migrate_config, read_config, write_config
from kuberich.diagnostics.logging import diagnostic_logging
from kuberich.diagnostics.redaction import sanitize_text
from kuberich.domain.connection_overrides import ConnectionOverrides
from kuberich.domain.connections import ConnectionRequest, request_duration
from kuberich.errors import AppError, ExitCode
from kuberich.security.arguments import validate_argument
from kuberich.services.access import AccessPolicy
from kuberich.services.commands import Command, CommandService, ScopedCommand
from kuberich.ui.launch import run_terminal
from kuberich.ui.presentation import Presentation


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # argparse normally echoes arbitrary arguments, which may contain credentials.
        self.print_usage(sys.stderr)
        self.exit(2, "kuberich: invalid command line; run kuberich --help.\n")


def _argument(value: str) -> str:
    try:
        return validate_argument(value)
    except AppError:
        raise argparse.ArgumentTypeError("Invalid option value.") from None


def _boolean(value: str) -> bool:
    if value.casefold() not in {"true", "false"}:
        raise argparse.ArgumentTypeError("Expected true or false.")
    return value.casefold() == "true"


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="kuberich",
        description="A Kubernetes terminal UI built with Python and Textual.",
        epilog="Live pod table preview: commands, completion, filters, logs and embedded container shells.",
        allow_abbrev=False,
        formatter_class=lambda prog: argparse.HelpFormatter(prog, width=100),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('kuberich')}")
    parser.add_argument("--config", help="KubeRich preferences YAML (separate from kubeconfig)")
    parser.add_argument(
        "--kubeconfig",
        type=_argument,
        help="single kubeconfig file (otherwise KUBECONFIG or ~/.kube/config)",
    )
    parser.add_argument(
        "--context", type=_argument, help="context to connect (otherwise current-context)"
    )
    parser.add_argument(
        "--namespace",
        "-n",
        type=_argument,
        help="initial namespace (otherwise the context namespace)",
    )
    parser.add_argument(
        "--all-namespaces",
        "-A",
        action="store_true",
        default=None,
        help="select all namespaces for this session",
    )
    parser.add_argument(
        "--request-timeout",
        type=_argument,
        help="API/helper timeout: 0.1-3600 seconds, or ms/s/m/h (default 10s)",
    )
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
    parser.add_argument(
        "--refresh",
        "-r",
        dest="refresh_seconds",
        type=float,
        help="periodic table refresh seconds (0.1-3600); watch changes remain live",
    )
    parser.add_argument(
        "--readonly",
        dest="read_only",
        action="store_true",
        default=None,
        help="block mutations, shell, attach and plugins",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        default=None,
        help="override the configured read-only preference for this session",
    )
    parser.add_argument(
        "--command",
        "-c",
        dest="initial_command",
        type=_argument,
        help="initial terminal command: po, ctx, ns, status, retry, back, forward, help or quit",
    )
    for flag in ("headless", "logoless", "crumbsless"):
        parser.add_argument(
            f"--{flag}",
            action="store_true",
            default=None,
            help={
                "headless": "hide the application header",
                "logoless": "hide the brand in the header",
                "crumbsless": "hide the context/namespace scope bar",
            }[flag],
        )
    pending = parser.add_argument_group("Recognized options awaiting their owning feature (exit 4)")
    for option in PENDING_OPTIONS:
        if option.boolean:
            pending.add_argument(
                *option.flags,
                dest=option.destination,
                action="store_true",
                default=None,
                help=f"unavailable: {option.owner}",
            )
        else:
            pending.add_argument(
                *option.flags,
                dest=option.destination,
                type=_argument,
                action="store",
                help=f"unavailable: {option.owner}",
            )
    transport = parser.add_argument_group("Session connection overrides")
    for option in CONNECTION_OPTIONS:
        transport.add_argument(
            *option.flags,
            dest=option.destination,
            **(
                {"nargs": "?", "const": True, "default": None, "type": _boolean}
                if option.boolean
                else {"type": _argument, "action": "append" if option.repeated else "store"}
            ),
            help={
                "cluster": "kubeconfig cluster alias for this invocation",
                "user": "kubeconfig auth-info alias for this invocation",
                "as_user": "user/service account to impersonate; server permission required",
                "as_group": "impersonation group; repeat to retain multiple groups",
                "insecure": "skip TLS verification explicitly; accepts =true or =false",
                "certificate_authority": "CA certificate file; enables TLS verification",
                "client_key": "client private key file; requires --client-certificate",
                "client_certificate": "client certificate file; requires --client-key",
                "token": "bearer token override; never included in diagnostics",
            }[option.destination],
        )
    commands = parser.add_subparsers(dest="subcommand")
    commands.add_parser(
        "help", help="show launch help without loading configuration", allow_abbrev=False
    )
    release = commands.add_parser(
        "version", help="show installed version without loading configuration", allow_abbrev=False
    )
    release.add_argument("--short", "-s", action="store_true", help="print only the version number")
    commands.add_parser(
        "info", help="show safe local paths, preferences and installed versions", allow_abbrev=False
    )
    config = commands.add_parser(
        "config", help="initialize, validate or migrate local preferences", allow_abbrev=False
    )
    operations = config.add_subparsers(dest="operation", required=True)
    operations.add_parser(
        "init", help="create defaults without overwriting existing files", allow_abbrev=False
    )
    operations.add_parser(
        "check", help="validate effective preferences without writing files", allow_abbrev=False
    )
    operations.add_parser(
        "migrate",
        help="copy legacy defaults without deleting or overwriting files",
        allow_abbrev=False,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Keep filesystem/debug details away from terminal output and return stable codes."""
    parser = _parser()
    # Bare bool flags must not consume an inspection subcommand. Explicit bool
    # values use =true/=false; leave the process argument list untouched.
    launch_arguments = argv if argv is not None else sys.argv[1:]
    arguments = parser.parse_args(
        [
            "--insecure-skip-tls-verify=true" if value == "--insecure-skip-tls-verify" else value
            for value in launch_arguments
        ]
    )
    try:
        values = vars(arguments)
        require_available(values)
        runtime = {
            key: values[key]
            for key in (
                *(
                    "log_file",
                    "log_level",
                    "refresh_seconds",
                    "read_only",
                    "write",
                    "initial_command",
                    "headless",
                    "logoless",
                    "crumbsless",
                    "kubeconfig",
                    "context",
                    "namespace",
                    "all_namespaces",
                    "request_timeout",
                ),
                *(option.destination for option in CONNECTION_OPTIONS),
            )
            if values[key] is not None
        }
        if arguments.subcommand in {"help", "version"}:
            if runtime or arguments.config is not None:
                raise AppError("help/version do not accept runtime overrides or --config.")
            if arguments.subcommand == "help":
                parser.print_help()
            else:
                print(version("kuberich") if arguments.short else f"kuberich {version('kuberich')}")
            return 0
        if arguments.subcommand is not None and any(
            key in runtime for key in ("initial_command", "headless", "logoless", "crumbsless")
        ):
            raise AppError("Command and presentation flags apply only to terminal launch.")
        if arguments.subcommand is not None and any(
            key in runtime
            for key in (
                "kubeconfig",
                "context",
                "namespace",
                "all_namespaces",
                "request_timeout",
                *(option.destination for option in CONNECTION_OPTIONS),
            )
        ):
            raise AppError(
                "Connection flags apply only to terminal launch; diagnostics never load credentials."
            )
        connection = ConnectionRequest(
            arguments.kubeconfig,
            arguments.context,
            arguments.namespace,
            bool(arguments.all_namespaces),
            request_duration(arguments.request_timeout)
            if arguments.request_timeout is not None
            else 10.0,
            ConnectionOverrides(
                cluster=arguments.cluster,
                user=arguments.user,
                token=arguments.token,
                certificate_authority=arguments.certificate_authority,
                client_certificate=arguments.client_certificate,
                client_key=arguments.client_key,
                insecure=arguments.insecure,
                as_user=arguments.as_user,
                as_groups=tuple(arguments.as_group or ()),
            ).capture_paths(Path.cwd()),
        )
        location = config_location(arguments.config, os.environ)
        if arguments.subcommand == "config" and arguments.operation == "init":
            if runtime:
                raise AppError("Flags are runtime overrides; omit them for config init.")
            write_config(location.path, ConfigDocument())
            print("Created default KubeRich preferences. Run kuberich info to see local paths.")
            return 0
        if arguments.subcommand == "config" and arguments.operation == "migrate":
            if runtime or location.explicit:
                raise AppError(
                    "config migrate uses default preferences without overrides or --config."
                )
            if location.migration_target is None:
                read_config(location.path, missing_ok=False)
                print("KubeRich preferences already exist. No files were changed.")
            else:
                migrate_config(location.path, location.migration_target)
                print(
                    "Migrated preferences to KubeRich. Original Kubetrol preferences were retained."
                )
            return 0
        document = read_config(location.path, missing_ok=not location.explicit)
        overrides = {
            key: value
            for key, value in {
                "log_file": arguments.log_file,
                "log_level": arguments.log_level,
                "refresh_seconds": arguments.refresh_seconds,
                "read_only": False if arguments.write else arguments.read_only,
            }.items()
            if value is not None
        }
        settings = resolve_settings(document, os.environ, overrides)
        if (
            arguments.initial_command is not None
            and not arguments.initial_command.strip().removeprefix(":").strip()
        ):
            raise AppError("--command must name an initial command; use help or quit.")
        initial = CommandService(AccessPolicy(settings.read_only)).resolve(
            arguments.initial_command or ""
        )
        action = initial.command if isinstance(initial, ScopedCommand) else initial
        if action in {
            Command.UNAVAILABLE,
            Command.SHELL,
            Command.ATTACH,
            Command.UPLOAD,
            Command.DOWNLOAD,
            Command.ANNOTATE,
            Command.EDIT,
            Command.SCALE,
            Command.RESTART,
            Command.ROLLBACK,
            Command.ROLLOUT,
        }:
            raise AppError(
                "--command requires an available startup view; resource actions need an interactive resource selection. Available: po, ctx, ns, deploy, rs, sts, ds, job, cj, svc, ep, ing, cm, sec, no, pvc, pv, sc, status, retry, help, quit.",
                ExitCode.UNAVAILABLE,
            )
        log_file = log_location(
            settings,
            location.path,
            from_file="log_file" not in overrides
            and "KUBERICH_LOG_FILE" not in os.environ
            and "KUBETROL_LOG_FILE" not in os.environ,
        )
        if arguments.subcommand == "info":
            print(
                json.dumps(
                    {
                        "version": version("kuberich"),
                        "python": platform.python_version(),
                        "platform": sys.platform,
                        "dependencies": {
                            name: version(name)
                            for name in ("textual", "kubernetes-asyncio", "platformdirs", "pyyaml")
                        },
                        "config_file": sanitize_text(str(location.path)),
                        "data_dir": sanitize_text(str(user_data_path("kuberich", appauthor=False))),
                        "log_file": sanitize_text(str(log_file)),
                        "config_exists": location.path.exists(),
                        "migration_pending": document.migrated
                        or location.migration_target is not None,
                        "config_migration_target": sanitize_text(str(location.migration_target))
                        if location.migration_target is not None
                        else None,
                        "unknown_fields": len(document.unknown),
                        "preferences": {
                            key: value
                            for key, value in settings.to_mapping().items()
                            if key in {"theme", "refresh_seconds", "read_only", "log_level"}
                        },
                        "terminal_ui_available": True,
                        "cluster_connected": False,
                    },
                    indent=2,
                )
            )
        elif arguments.subcommand == "config":
            print("KubeRich preferences are valid. No files were changed.")
        else:
            with diagnostic_logging(log_file, settings.log_level) as logger:
                try:
                    logger.debug("Launching terminal interface.")
                    run_terminal(
                        settings,
                        logger,
                        presentation=Presentation(
                            bool(arguments.headless),
                            bool(arguments.logoless),
                            bool(arguments.crumbsless),
                        ),
                        initial_command=initial,
                        connection=connection,
                    )
                except Exception:
                    logger.debug("Terminal launch failed.", exc_info=True)
                    raise
        return 0
    except KeyboardInterrupt:
        print("kuberich: interrupted.", file=sys.stderr)
        return ExitCode.INTERRUPTED
    except AppError as error:
        if error.code != ExitCode.HANGUP:
            print(f"kuberich: {sanitize_text(str(error))}", file=sys.stderr)
        return error.code
    except Exception:
        print(
            "kuberich: unexpected local failure; run kuberich info and report the problem.",
            file=sys.stderr,
        )
        return ExitCode.FAILURE
