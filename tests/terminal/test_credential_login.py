"""Generic native login respects declared interactiveMode and restores the TTY."""

import asyncio
import sys

import pytest

from tests.support.connections import fake_api
from tests.support.credential_handoff import credential_terminal_trial, encrypted_key_terminal_trial


@pytest.mark.parametrize(
    "scenario", ["success", "always", "never", "ctrl_c", "cancel", "parent_shutdown"]
)
def test_generic_credential_login_lifecycle(tmp_path, scenario):
    credential_terminal_trial(sys.executable, tmp_path, scenario, name=f"generic-login-{scenario}")


@pytest.mark.asyncio
async def test_native_encrypted_key_refusal_never_prompts_or_blocks_workspace(tmp_path):
    called = []

    async def handler(request):
        called.append(True)
        raise AssertionError("Refused TLS material cannot contact the API.")

    async with fake_api(handler) as server:
        await asyncio.to_thread(
            encrypted_key_terminal_trial,
            sys.executable,
            tmp_path,
            server,
            name="encrypted-key-native",
        )
    assert not called
