"""Native keyboard confirmation, monitoring cancellation and terminal restoration."""

import asyncio
import sys

import pytest

from tests.support.workload_terminal import terminal_workload
from tests.support.workloads import workload_api


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["scale 3", "restart", "rollback 1"])
async def test_native_workload_confirmation(tmp_path, action):
    async with workload_api() as (url, api):
        await asyncio.to_thread(
            terminal_workload,
            [sys.executable, "-m", "kubetrol"],
            tmp_path,
            "workload-" + action.replace(" ", "-"),
            url,
            api,
            action,
        )
