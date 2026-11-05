"""Explicit Popeye execution using captured connections and owned bounded processes."""

import asyncio
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from kuberich.adapters.kubernetes import KubernetesSession
from kuberich.config.popeye import PopeyeSettings
from kuberich.domain.cluster_diagnostics import (
    MAX_DIAGNOSTIC_FINDINGS,
    MAX_DIAGNOSTIC_TEXT_BYTES,
    SOURCE_TEXT_RESERVE,
    DiagnosticFinding,
    DiagnosticRequest,
    DiagnosticSource,
    DiagnosticSourceKind,
    DiagnosticStatus,
    diagnostic_text_bytes,
)
from kuberich.domain.popeye import (
    MAX_POPEYE_INPUT_BYTES,
    MAX_POPEYE_SOURCE_BYTES,
    POPEYE_PARSER_ID,
    parse_popeye_report,
    parse_popeye_version,
    popeye_limits,
)
from kuberich.domain.processes import (
    ProcessMode,
    ProcessPurpose,
    ProcessResult,
    ProcessStatus,
    capture_command,
)
from kuberich.domain.resources import Discovery
from kuberich.errors import AppError, ExecutableUnavailable
from kuberich.services.access import AccessPolicy, Action
from kuberich.services.delegation import capture_delegation, stage_connection
from kuberich.services.ownership import finish_owned
from kuberich.services.processes import ProcessRunner
from kuberich.services.resources import parse_owned


@dataclass(frozen=True, slots=True)
class PopeyeResult:
    status: ProcessStatus | None
    returncode: int | None
    findings: tuple[DiagnosticFinding, ...]
    sources: tuple[DiagnosticSource, ...]
    producer_version: str | None = None
    parser_id: str | None = None
    report_time: datetime | None = None


class _Refused(AppError):
    def __init__(self, status: DiagnosticStatus, detail: str) -> None:
        super().__init__(detail)
        self.status = status


class PopeyeService:
    """One explicit run at a time; close drains processes/parsers before client teardown."""

    def __init__(
        self,
        client: KubernetesSession,
        policy: AccessPolicy,
        settings: PopeyeSettings,
        environment: Mapping[str, str],
        directory: Path,
        current: Callable[[DiagnosticRequest], bool],
        *,
        discovery: Discovery,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.client, self.policy, self.settings = client, policy, settings
        self.environment, self.directory = tuple(environment.items()), directory.absolute()
        self.current, self.discovery, self.now = current, discovery, now
        self._task: asyncio.Task[object] | None = None
        self._closed = False

    def _require(self, request: DiagnosticRequest) -> None:
        if (
            self._closed
            or not self.current(request)
            or self.client.context.name != request.scope.session.context
        ):
            raise _Refused(
                DiagnosticStatus.CANCELLED, "Popeye captured scope is no longer current."
            )
        try:
            self.policy.require(Action.READ if self.settings.trusted_read_only else Action.PLUGIN)
        except AppError:
            raise _Refused(
                DiagnosticStatus.FORBIDDEN,
                "Read-only policy requires an explicitly trusted read-only Popeye executable.",
            ) from None

    async def run(
        self,
        request: DiagnosticRequest,
        *,
        max_findings: int = MAX_DIAGNOSTIC_FINDINGS,
        max_text_bytes: int = MAX_DIAGNOSTIC_TEXT_BYTES - SOURCE_TEXT_RESERVE,
        max_source_text_bytes: int = MAX_POPEYE_SOURCE_BYTES,
    ) -> PopeyeResult:
        popeye_limits(max_findings, max_text_bytes, max_source_text_bytes)
        if self._task is not None:
            raise AppError("A Popeye run is already owned; drain it before starting another.")
        task = asyncio.current_task()
        assert task is not None
        self._task = task
        result: ProcessResult | None = None
        producer_version: str | None = None

        def outcome(status: DiagnosticStatus, detail: str) -> PopeyeResult:
            source = DiagnosticSource(
                "popeye:process",
                DiagnosticSourceKind.POPEYE,
                None,
                request.scope.namespace,
                status,
                None,
                None,
                self.now(),
                detail,
            )
            return PopeyeResult(
                result.status if result is not None else None,
                result.returncode if result is not None else None,
                (),
                (source,) if diagnostic_text_bytes(source) <= max_source_text_bytes else (),
                producer_version,
            )

        try:
            self._require(request)  # Before path lookup, version probing or credential staging.
            settings, client, discovery = self.settings, self.client, self.discovery
            directory, environment = self.directory, dict(self.environment)
            version_command = capture_command(
                (str(settings.executable), "version"),
                environment=environment,
                directory=directory,
                mode=ProcessMode.CAPTURE,
                purpose=ProcessPurpose.PLUGIN,
                trusted_read_only=settings.trusted_read_only,
            )
            guard = partial(self._require, request)
            async with ProcessRunner(self.policy, output_limit=16384) as probe:
                result = await probe.capture(version_command, timeout=5, guard=guard)
            self._require(request)
            if result.status is not ProcessStatus.SUCCEEDED:
                return outcome(
                    _process_status(result), "Popeye version probe did not complete successfully."
                )
            try:
                producer_version = parse_popeye_version(result.stdout)
            except AppError:
                return outcome(
                    DiagnosticStatus.UNSUPPORTED, "Popeye requires one valid v0.22.1 Version tuple."
                )
            self._require(request)
            material = capture_delegation(client, environment, directory, prefix="plugin")
            variables = dict(material.environment)
            variables["KUBECONFIG"] = str(material.path)
            namespace = request.scope.namespace
            scope_flag = "--all-namespaces" if namespace is None else f"--namespace={namespace}"
            command = capture_command(
                (
                    str(settings.executable),
                    f"--kubeconfig={material.path}",
                    f"--context={request.scope.session.context}",
                    scope_flag,
                    "--out=json",
                    "--sections=" + ",".join(settings.sections),
                    "--lint=ok",
                    "--logs=none",
                    "--log-level=0",
                    "--request-timeout=10s",
                ),
                environment=variables,
                directory=material.directory,
                mode=ProcessMode.CAPTURE,
                purpose=ProcessPurpose.PLUGIN,
                trusted_read_only=settings.trusted_read_only,
            )
            self._require(request)
            async with stage_connection(material.path, material.configuration):
                self._require(request)
                # This nesting drains the process and parser before private-file removal.
                async with ProcessRunner(
                    self.policy, output_limit=MAX_POPEYE_INPUT_BYTES
                ) as runner:
                    result = await runner.capture(
                        command, timeout=settings.timeout_seconds, guard=guard
                    )
                    self._require(request)
                    if result.status not in (
                        ProcessStatus.SUCCEEDED,
                        ProcessStatus.FAILED,
                    ) or result.returncode not in (0, 1):
                        return outcome(
                            _process_status(result),
                            "Popeye scan did not produce an accepted complete process outcome.",
                        )
                    if not result.stdout:
                        return outcome(
                            DiagnosticStatus.FORBIDDEN
                            if _denied(result)
                            else DiagnosticStatus.UNAVAILABLE,
                            "Popeye produced no report; no successful scan is established.",
                        )
                    try:
                        report = await parse_owned(
                            partial(
                                parse_popeye_report,
                                result.stdout,
                                producer_version=producer_version,
                                request=request,
                                discovery=discovery,
                                observed_at=self.now(),
                                max_findings=max_findings,
                                max_text_bytes=max_text_bytes,
                                max_source_text_bytes=max(0, max_source_text_bytes - 1024),
                            )
                        )
                    except AppError:
                        return outcome(
                            DiagnosticStatus.FORBIDDEN
                            if _denied(result)
                            else DiagnosticStatus.FAILED,
                            "Popeye report was rejected as malformed, unsupported or inconsistent with the captured scope.",
                        )
                    self._require(request)
                    process = outcome(
                        DiagnosticStatus.PARTIAL
                        if report.omitted_findings or report.omitted_source_notices
                        else DiagnosticStatus.READY,
                        f"Popeye {producer_version}; exit={result.returncode}; deadline={settings.timeout_seconds}s; "
                        f"sections={','.join(settings.sections)}; scan={namespace or 'all namespaces'}; "
                        f"combined output limit={MAX_POPEYE_INPUT_BYTES} bytes. External API read count is unknown.",
                    )
                    return PopeyeResult(
                        result.status,
                        result.returncode,
                        report.findings,
                        (*report.sources, *process.sources),
                        producer_version,
                        POPEYE_PARSER_ID,
                        report.report_time,
                    )
        except _Refused as error:
            return outcome(error.status, str(error))
        except ExecutableUnavailable:
            return outcome(
                DiagnosticStatus.UNAVAILABLE,
                "Popeye dependency is missing or not executable; configure an installed absolute path.",
            )
        except AppError:
            return outcome(
                DiagnosticStatus.FAILED,
                "Popeye execution or private connection preparation failed.",
            )
        finally:
            self._task = None

    async def close(self) -> None:
        self._closed = True
        task = self._task
        if task is not None:
            task.cancel()
            await finish_owned(asyncio.gather(task, return_exceptions=True))


def _denied(result: ProcessResult) -> bool:
    return re.search(rb"\b(?:403|forbidden)\b", result.stderr, re.I) is not None


def _process_status(result: ProcessResult) -> DiagnosticStatus:
    if result.status is ProcessStatus.CANCELLED:
        return DiagnosticStatus.CANCELLED
    if result.status in (ProcessStatus.TIMED_OUT, ProcessStatus.OUTPUT_LIMIT):
        return DiagnosticStatus.PARTIAL
    return DiagnosticStatus.FORBIDDEN if _denied(result) else DiagnosticStatus.FAILED
