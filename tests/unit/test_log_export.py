"""Actual private exports, exclusive publication and awaited filesystem ownership."""

import asyncio
import os
import threading

import pytest

from kubetrol.domain.logs import MAX_BYTES, MAX_LINES
from kubetrol.errors import AppError
from kubetrol.services.log_export import save_logs


@pytest.mark.asyncio
async def test_private_complete_export_refuses_existing_files_symlinks_and_bad_paths(tmp_path):
    destination = tmp_path / "logs.txt"
    assert await save_logs(str(destination), "literal [red] text\n你好") == destination
    assert destination.read_text() == "literal [red] text\n你好"
    assert destination.stat().st_mode & 0o777 == 0o600
    link = tmp_path / "link.txt"
    link.symlink_to(destination)
    for path in (destination, link, tmp_path / "missing" / "logs", tmp_path / "bad\0path"):
        with pytest.raises(AppError, match="new file"):
            await save_logs(str(path), "replacement")
    assert destination.read_text().startswith("literal")
    assert not list(tmp_path.glob(".kubetrol-log-*"))
    for path, text in (("", "x"), ("path", "x" * (MAX_BYTES + MAX_LINES + 1))):
        with pytest.raises(AppError, match="bounded"):
            await save_logs(path, text)


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_cancellation_drains_owned_worker_and_retrieves_late_failure(
    tmp_path, monkeypatch, failed
):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    link = os.link

    def held_link(source, target):
        started.set()
        assert release.wait(5)
        try:
            if failed:
                raise OSError("synthetic private error")
            return link(source, target)
        finally:
            finished.set()

    monkeypatch.setattr(os, "link", held_link)
    task = asyncio.create_task(save_logs(str(tmp_path / "saved"), "captured"))
    async with asyncio.timeout(5):
        while not started.is_set():
            await asyncio.sleep(0.001)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set() and not list(tmp_path.glob(".kubetrol-log-*"))
    assert (tmp_path / "saved").exists() == (not failed)
