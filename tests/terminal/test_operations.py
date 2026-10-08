"""Actual terminal operation confirmation and restored modes after API writes."""

import asyncio
import sys

import pytest

from tests.support.operation_terminal import terminal_operation
from tests.support.operations import operation_api


@pytest.mark.asyncio
@pytest.mark.parametrize("alias,action", [("cj", "trigger"), ("cm", "delete")])
async def test_native_resource_operation_confirmation(tmp_path, alias, action):
    async with operation_api(alias) as (url, api):
        await asyncio.to_thread(
            terminal_operation,
            [sys.executable, "-m", "kuberich"],
            tmp_path,
            "operation-" + action,
            url,
            api,
            action,
            alias,
        )
