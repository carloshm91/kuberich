"""Actual selected-client HTTP, captured local child, binary trees and cancellation cleanup."""

import asyncio
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest
from aiohttp import web

from kuberich.domain.connections import ConnectionProblem
from kuberich.domain.targets import ResourceTarget, SessionIdentity
from kuberich.domain.transfers import TransferDirection
from kuberich.errors import AppError
from kuberich.services import transfers
from kuberich.services.access import AccessPolicy
from kuberich.services.transfers import TransferService
from tests.support.pods import pod
from tests.support.resources import reader_fixture
from tests.support.transfers import executable
from tests.support.workspace import wait_for


def service(reader, directory, *, readonly=False, current=lambda: True, failure=""):
    return TransferService(
        reader.session,
        ResourceTarget(
            SessionIdentity(reader.session.context.name, 1), "", "pods", "team", "api", "api-uid"
        ),
        AccessPolicy(readonly),
        current,
        environment=executable(directory, failure=failure),
        directory=directory,
    )


@pytest.mark.asyncio
async def test_concurrent_reviews_cannot_overwrite_owned_state_and_cancellation_releases_slot(
    tmp_path,
):
    entered, release = asyncio.Event(), asyncio.Event()

    async def handler(request):
        entered.set()
        await release.wait()
        return web.json_response(pod("api", uid="api-uid"))

    async with reader_fixture(tmp_path, handler) as reader:
        owner = service(reader, tmp_path / "tools")
        first = asyncio.create_task(
            owner.prepare(
                TransferDirection.DOWNLOAD,
                "app",
                str(tmp_path / "first"),
                "/tmp/data",
                overwrite=False,
            )
        )
        try:
            await entered.wait()
            with pytest.raises(AppError, match="Another transfer review"):
                await owner.prepare(
                    TransferDirection.DOWNLOAD,
                    "app",
                    str(tmp_path / "second"),
                    "/tmp/data",
                    overwrite=False,
                )
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert owner.review is None
            release.set()
            review = await owner.prepare(
                TransferDirection.DOWNLOAD,
                "app",
                str(tmp_path / "third"),
                "/tmp/data",
                overwrite=False,
            )
            assert owner.review is review
        finally:
            release.set()
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
            await owner.close()
        assert not list(tmp_path.glob(".kuberich-copy-*"))


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", list(TransferDirection))
@pytest.mark.parametrize("directory", [False, True])
async def test_reviewed_literal_binary_file_or_tree_copies_exact_captured_paths(
    tmp_path, direction, directory
):
    requests = []

    async def handler(request):
        requests.append(request.path)
        return web.json_response(pod("api", uid="api-uid"))

    async with reader_fixture(tmp_path, handler) as reader:
        owner = service(
            reader, tmp_path / "tools", readonly=direction is TransferDirection.DOWNLOAD
        )
        local = tmp_path / "chosen local"
        remote = tmp_path / "tools/remote/tmp/space café;literal"
        source = local if direction is TransferDirection.UPLOAD else remote
        if directory:
            source.mkdir()
            (source / "empty").mkdir()
            (source / "data.bin").write_bytes(bytes(range(256)) * 33)
        else:
            source.write_bytes(bytes(range(256)) * 33)
        review = await owner.prepare(
            direction, "app", str(local), "/tmp/space café;literal", overwrite=False
        )
        configuration = review.connection.path
        stage = Path(review.temporary.name)
        if direction is TransferDirection.UPLOAD and not directory:
            local.write_bytes(b"changed-after-review")
        result = await owner.execute(review)
        assert "complete: 8448 bytes" in result
        destination = remote if direction is TransferDirection.UPLOAD else local
        output = destination / "data.bin" if directory else destination
        assert output.read_bytes() == bytes(range(256)) * 33
        assert directory is destination.is_dir()
        assert not configuration.exists() and not stage.exists() and owner.review is None
        assert set(requests) == {"/api/v1/namespaces/team/pods/api"}
        commands = [
            json.loads(line) for line in (tmp_path / "tools/arguments").read_text().splitlines()
        ]
        assert all(
            args[:3]
            == [f"--kubeconfig={configuration}", "--context=kuberich-test-one", "--namespace=team"]
            for args in commands
        )
        assert not list(tmp_path.glob(".kuberich-copy-*"))
        with pytest.raises(AppError, match="unused"):
            await owner.execute(review)


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", list(TransferDirection))
@pytest.mark.parametrize("overwrite", [False, True])
async def test_overwrite_requires_explicit_regular_file_intent(tmp_path, direction, overwrite):
    async def handler(request):
        return web.json_response(pod("api", uid="api-uid"))

    async with reader_fixture(tmp_path, handler) as reader:
        owner = service(reader, tmp_path / "tools")
        local = tmp_path / "chosen"
        remote = tmp_path / "tools/remote/tmp/data"
        local.write_bytes(b"local")
        remote.write_bytes(b"remote")
        if not overwrite and direction is TransferDirection.DOWNLOAD:
            with pytest.raises(AppError, match="exists"):
                await owner.prepare(direction, "app", str(local), "/tmp/data", overwrite=False)
        else:
            review = await owner.prepare(
                direction, "app", str(local), "/tmp/data", overwrite=overwrite
            )
            if not overwrite:
                with pytest.raises(AppError, match="exists"):
                    await owner.execute(review)
            else:
                assert "complete" in await owner.execute(review)
                assert (
                    remote if direction is TransferDirection.UPLOAD else local
                ).read_bytes() == (b"local" if direction is TransferDirection.UPLOAD else b"remote")
        assert not list(Path(reader.session.directory.name).glob("copy-*"))
        assert not list(tmp_path.glob(".kuberich-copy-*"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "readonly",
        "stale",
        "context",
        "replacement",
        "missing-container",
        "waiting",
        "403",
        "404",
        "401",
    ],
)
async def test_transfer_guards_refuse_before_any_executable_or_private_snapshot(tmp_path, failure):
    async def handler(request):
        if failure in ("403", "404", "401"):
            return web.Response(status=int(failure), text="synthetic-private-body")
        value = pod("api", uid="replacement" if failure == "replacement" else "api-uid")
        if failure == "missing-container":
            value["spec"]["containers"] = []
        if failure == "waiting":
            value["status"]["containerStatuses"][0]["state"] = {"waiting": {}}
        return web.json_response(value)

    async with reader_fixture(tmp_path, handler) as reader:
        owner = service(
            reader,
            tmp_path / "tools",
            readonly=failure == "readonly",
            current=lambda: failure != "stale",
        )
        if failure == "context":
            owner.target = replace(owner.target, session=SessionIdentity("other", 1))
        with pytest.raises((AppError, ConnectionProblem)) as error:
            await owner.prepare(
                TransferDirection.UPLOAD,
                "app",
                str(tmp_path / "absent"),
                "/tmp/file",
                overwrite=False,
            )
        assert "synthetic-private-body" not in str(error.value)
        assert owner.review is None and not (tmp_path / "tools/arguments").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["missing-tar", "exit-failure", "malicious", "stderr-limit", "wire-limit"]
)
async def test_download_failures_preserve_existing_local_file_and_remove_owned_partials(
    tmp_path, monkeypatch, failure
):
    async def handler(request):
        return web.json_response(pod("api", uid="api-uid"))

    async with reader_fixture(tmp_path, handler) as reader:
        owner = service(reader, tmp_path / "tools", readonly=True, failure=failure)
        target = tmp_path / "chosen"
        target.write_bytes(b"original")
        (tmp_path / "tools/remote/tmp/data").write_bytes(b"remote")
        review = await owner.prepare(
            TransferDirection.DOWNLOAD, "app", str(target), "/tmp/data", overwrite=True
        )
        if failure == "wire-limit":
            monkeypatch.setattr(transfers, "MAX_ARCHIVE_BYTES", 4096)
        try:
            message = await owner.execute(review)
            assert (
                "incomplete" in message and "127" in message
                if failure == "missing-tar"
                else "incomplete" in message
            )
        except AppError:
            assert failure in ("malicious", "wire-limit", "stderr-limit")
        assert target.read_bytes() == b"original" and not (tmp_path / "outside").exists()
        assert "synthetic-private-stderr" not in owner.last_message
        assert owner.review is None and not review.connection.path.exists()
        assert not Path(review.temporary.name).exists() and not list(
            tmp_path.glob(".kuberich-copy-*")
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("direction", list(TransferDirection))
async def test_cancelled_copy_reaps_actual_child_and_records_remote_or_local_partial_state(
    tmp_path, direction
):
    async def handler(request):
        return web.json_response(pod("api", uid="api-uid"))

    async with reader_fixture(tmp_path, handler) as reader:
        owner = service(
            reader,
            tmp_path / "tools",
            failure="cancel-upload" if direction is TransferDirection.UPLOAD else "cancel-download",
        )
        local = tmp_path / "chosen"
        local.write_bytes(b"original")
        review = await owner.prepare(
            direction,
            "app",
            str(local),
            "/tmp/data",
            overwrite=direction is TransferDirection.DOWNLOAD,
        )
        task = asyncio.create_task(owner.execute(review))
        await wait_for(lambda: (tmp_path / "tools/started").exists())
        pid = int((tmp_path / "tools/pid").read_text())
        task.cancel()
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        assert not Path(review.temporary.name).exists() and not review.connection.path.exists()
        assert "cancel" in owner.last_message.lower()
        if direction is TransferDirection.UPLOAD:
            assert "remote partial" in owner.last_message.lower()
            assert (tmp_path / "tools/remote/tmp/data").read_bytes() == b"partial"
        else:
            assert local.read_bytes() == b"original" and not list(tmp_path.glob(".kuberich-copy-*"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    ["remote-symlink", "ancestor-link", "missing-parent", "remote-directory", "missing-test"],
)
async def test_upload_destination_refusals_launch_no_cp_and_preserve_remote_values(
    tmp_path, failure
):
    async def handler(request):
        return web.json_response(pod("api", uid="api-uid"))

    async with reader_fixture(tmp_path, handler) as reader:
        owner = service(
            reader, tmp_path / "tools", failure="missing-test" if failure == "missing-test" else ""
        )
        local = tmp_path / "source"
        local.write_bytes(b"new")
        remote = tmp_path / "tools/remote/tmp/data"
        selected = "/tmp/data"
        if failure == "remote-symlink":
            remote.symlink_to(tmp_path / "outside")
        elif failure == "ancestor-link":
            (tmp_path / "tools/remote/link").symlink_to(
                tmp_path / "tools/remote/tmp", target_is_directory=True
            )
            selected = "/link/data"
        elif failure == "remote-directory":
            remote.mkdir()
        elif failure == "missing-parent":
            selected = "/missing/data"
        review = await owner.prepare(
            TransferDirection.UPLOAD, "app", str(local), selected, overwrite=True
        )
        with pytest.raises(AppError):
            await owner.execute(review)
        assert owner.review is None
        commands = [
            json.loads(line) for line in (tmp_path / "tools/arguments").read_text().splitlines()
        ]
        assert all(args[3] != "cp" for args in commands)
        assert not (tmp_path / "outside").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["snapshot", "publish-before", "publish-after"])
async def test_repeated_cancellation_drains_file_worker_and_reports_actual_commit_state(
    tmp_path, monkeypatch, phase
):
    import threading

    from kuberich.adapters.transfer_files import DownloadDestination

    entered, released, finished = threading.Event(), threading.Event(), threading.Event()

    async def handler(request):
        return web.json_response(pod("api", uid="api-uid"))

    async with reader_fixture(tmp_path, handler) as reader:
        owner = service(reader, tmp_path / "tools")
        local = tmp_path / "chosen"
        local.write_bytes(b"original")
        (tmp_path / "tools/remote/tmp/data").write_bytes(b"remote")
        original = transfers.snapshot_upload if phase == "snapshot" else DownloadDestination.publish

        def held(*arguments):
            if phase == "publish-after":
                original(*arguments)
            entered.set()
            try:
                assert released.wait(10)
                if phase != "publish-after":
                    return original(*arguments)
            finally:
                finished.set()

        if phase == "snapshot":
            monkeypatch.setattr(transfers, "snapshot_upload", held)
            task = asyncio.create_task(
                owner.prepare(
                    TransferDirection.UPLOAD, "app", str(local), "/tmp/data", overwrite=True
                )
            )
        else:
            monkeypatch.setattr(DownloadDestination, "publish", held)
            review = await owner.prepare(
                TransferDirection.DOWNLOAD, "app", str(local), "/tmp/data", overwrite=True
            )
            task = asyncio.create_task(owner.execute(review))
        await wait_for(entered.is_set)
        task.cancel()
        await asyncio.sleep(0.02)
        task.cancel()
        await asyncio.sleep(0.02)
        assert not task.done() and not finished.is_set()
        released.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set() and owner.review is None
        assert not list(Path(reader.session.directory.name).glob("copy-*"))
        assert not list(tmp_path.glob(".kuberich-copy-*"))
        if phase == "publish-after":
            assert (
                local.read_bytes() == b"remote"
                and "completed while cancellation" in owner.last_message
            )
        else:
            assert local.read_bytes() == b"original"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["stale-review", "changed-intent", "missing-tar", "directory-over-file"]
)
async def test_upload_review_refuses_changes_and_preserves_faithful_failure_result(
    tmp_path, failure
):
    current = True

    async def handler(request):
        return web.json_response(pod("api", uid="api-uid"))

    async with reader_fixture(tmp_path, handler) as reader:
        owner = service(
            reader,
            tmp_path / "tools",
            current=lambda: current,
            failure="missing-tar" if failure == "missing-tar" else "",
        )
        local = tmp_path / "source"
        if failure == "directory-over-file":
            local.mkdir()
            (local / "file").write_bytes(b"new")
            (tmp_path / "tools/remote/tmp/data").write_bytes(b"original")
        else:
            local.write_bytes(b"new")
        review = await owner.prepare(
            TransferDirection.UPLOAD, "app", str(local), "/tmp/data", overwrite=True
        )
        with pytest.raises(AppError, match="Another transfer"):
            await owner.prepare(
                TransferDirection.UPLOAD, "app", str(local), "/tmp/data", overwrite=True
            )
        if failure == "stale-review":
            current = False
        elif failure == "changed-intent":
            object.__setattr__(
                review,
                "intent",
                replace(review.intent, remote=review.intent.remote.with_name("changed")),
            )
        if failure == "missing-tar":
            result = await owner.execute(review)
            assert "Upload incomplete (exit 127" in result and "partial" in result
        else:
            with pytest.raises(AppError):
                await owner.execute(review)
        await owner.close()
        assert not review.connection.path.exists() and not Path(review.temporary.name).exists()
        assert not (tmp_path / "tools/remote/tmp/changed").exists()


@pytest.mark.asyncio
async def test_download_open_failure_drains_child_without_publishing(tmp_path, monkeypatch):
    async def handler(request):
        return web.json_response(pod("api", uid="api-uid"))

    async with reader_fixture(tmp_path, handler) as reader:
        owner = service(reader, tmp_path / "tools")
        target = tmp_path / "chosen"
        (tmp_path / "tools/remote/tmp/data").write_bytes(b"data")
        review = await owner.prepare(
            TransferDirection.DOWNLOAD, "app", str(target), "/tmp/data", overwrite=False
        )
        original = Path.open

        def refused(path, *arguments, **options):
            if path == Path(review.temporary.name) / "download.tar":
                raise OSError("synthetic-private-failure")
            return original(path, *arguments, **options)

        monkeypatch.setattr(Path, "open", refused)
        with pytest.raises(OSError):
            await owner.execute(review)
        assert (
            owner.review is None
            and not target.exists()
            and "synthetic-private" not in owner.last_message
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["short", "zero"])
async def test_download_writer_handles_short_writes_and_rejects_disk_failure_without_truncating_destination(
    tmp_path, monkeypatch, kind
):
    async def handler(request):
        return web.json_response(pod("api", uid="api-uid"))

    async with reader_fixture(tmp_path, handler) as reader:
        owner = service(reader, tmp_path / "tools")
        local = tmp_path / "chosen"
        local.write_bytes(b"original")
        expected = bytes(range(256)) * 128
        (tmp_path / "tools/remote/tmp/data").write_bytes(expected)
        review = await owner.prepare(
            TransferDirection.DOWNLOAD, "app", str(local), "/tmp/data", overwrite=True
        )
        original = Path.open

        class Writer:
            def __init__(self, stream):
                self.stream = stream

            def write(self, data):
                if kind == "zero":
                    return 0
                return self.stream.write(data[: max(1, len(data) // 2)])

            def close(self):
                return self.stream.close()

        def open_writer(path, *arguments, **options):
            stream = original(path, *arguments, **options)
            if (
                path == Path(review.temporary.name) / "download.tar"
                and arguments
                and arguments[0] == "xb"
            ):
                return Writer(stream)
            return stream

        monkeypatch.setattr(Path, "open", open_writer)
        if kind == "zero":
            with pytest.raises(OSError):
                await owner.execute(review)
            assert local.read_bytes() == b"original"
        else:
            assert "complete" in await owner.execute(review)
            assert local.read_bytes() == expected
        assert owner.review is None and not Path(review.temporary.name).exists()
