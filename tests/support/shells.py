"""Observe actual shell owners at the public preparation context boundary."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import wraps

from pytest import MonkeyPatch

from kuberich.domain.processes import ProcessCommand
from kuberich.services.shell import ShellRequest, ShellService
from tests.support.workers import CoroutineCalls


def observe_shells(monkeypatch: MonkeyPatch) -> CoroutineCalls:
    calls = CoroutineCalls()
    stage = ShellService.stage

    @wraps(stage)
    @asynccontextmanager
    async def observed(
        service: ShellService, request: ShellRequest
    ) -> AsyncIterator[ProcessCommand]:
        calls.capture()
        async with stage(service, request) as command:
            yield command

    monkeypatch.setattr(ShellService, "stage", observed)
    return calls
