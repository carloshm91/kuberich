"""Pinned native Helm lifecycle argv; chart and values are exact private local files."""

from pathlib import Path

from kuberich.domain.helm import HelmReleaseKey, HelmScope, HelmSettings, HelmVersion
from kuberich.domain.helm_cli import helm_scope_argv
from kuberich.domain.helm_lifecycle import HelmLifecycleKind, HelmLifecycleOptions
from kuberich.errors import AppError


def lifecycle_argv(
    settings: HelmSettings,
    version: HelmVersion,
    scope: HelmScope,
    kubeconfig: Path,
    address: HelmReleaseKey,
    operation: HelmLifecycleKind,
    options: HelmLifecycleOptions,
    chart: Path | None,
    values: Path | None,
    *,
    preview: bool,
) -> tuple[str, ...]:
    prefix = helm_scope_argv(settings, scope, kubeconfig, address)
    wait = (
        str(options.wait).lower()
        if version.major == 3
        else "legacy"
        if options.wait
        else "hookOnly"
    )
    flags: tuple[str, ...] = (
        f"--no-hooks={str(not options.run_hooks).lower()}",
        f"--timeout={options.timeout_seconds}s",
        f"--wait={wait}",
    )
    if operation is HelmLifecycleKind.UNINSTALL:
        return (
            *prefix,
            "uninstall",
            address.name,
            *flags,
            f"--keep-history={str(options.keep_history).lower()}",
            f"--cascade={options.cascade}",
            f"--dry-run={str(preview).lower()}",
        )
    if operation not in {HelmLifecycleKind.INSTALL, HelmLifecycleKind.UPGRADE}:
        raise AppError("Unsupported Helm lifecycle operation.")
    if chart is None or values is None or not chart.is_absolute() or not values.is_absolute():
        raise AppError("Helm requires exact private absolute chart and values paths.")
    flags += (
        f"--values={values}",
        "--output=json",
        "--skip-crds=true",
        "--dependency-update=false",
        "--enable-dns=false",
        "--take-ownership=false",
        f"--wait-for-jobs={str(options.wait).lower()}",
    )
    flags += ("--atomic=false",) if version.major == 3 else ("--rollback-on-failure=false",)
    if operation is HelmLifecycleKind.UPGRADE:
        flags += (
            "--reset-values=true",
            "--reuse-values=false",
            "--cleanup-on-fail=false",
            "--history-max=0",
            "--install=false",
        )
        if version.major == 4:
            flags += ("--server-side=auto",)
        else:
            flags += ("--force=false",)
    else:
        flags += ("--replace=false", "--create-namespace=false")
        if version.major == 4:
            # Cobra counts supplied false flags as set in mutually exclusive groups.
            # Both force options have false defaults in the exact pinned commands.
            flags += ("--server-side=false",)
    if preview:
        flags += ("--dry-run=server",)
    return (*prefix, operation.value, address.name, str(chart), *flags)
