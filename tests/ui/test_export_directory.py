"""The invocation export directory stays lexical until an explicit local action."""

import logging
import stat
from pathlib import Path
from uuid import uuid4

import pytest

from kuberich.adapters.artifact_files import ArtifactFiles
from kuberich.config.catalog import KubeCatalog
from kuberich.config.schema import Settings
from kuberich.domain.exports import DocumentSource, ExportCapture, ExportScope, read_artifact
from kuberich.services.commands import Command
from kuberich.services.exports import ExportLease
from kuberich.ui.app import KubeRichApp
from kuberich.ui.artifact_browser import ArtifactBrowserScreen
from kuberich.ui.export_review import ExportReviewScreen
from tests.support.workspace import wait_for


def local_capture(at):
    return (
        (
            "screen",
            ExportLease(
                id=uuid4(),
                capture=ExportCapture(
                    scope=ExportScope(
                        export_at=at,
                        source_at=at,
                        context=None,
                        header_namespace=None,
                        collection_namespace=None,
                        namespace_mode="local",
                    ),
                    source=DocumentSource(page="details", text="owned export directory\n"),
                ),
                current=lambda: True,
                session=None,
            ),
        ),
    )


def app_for(directory, root):
    return KubeRichApp(
        Settings(read_only=True),
        logging.Logger("export-directory", level=100),
        catalog=KubeCatalog(),
        initial_command=Command.EXPORTS,
        directory=directory,
        export_directory=root,
    )


async def reviewed(app):
    app.exports.open_export(local_capture)
    await wait_for(
        lambda: (
            isinstance(app.screen, ExportReviewScreen)
            and app.screen.prepared is not None
            and app.screen.operation_count == 0
        )
    )
    return app.screen


@pytest.mark.asyncio
@pytest.mark.parametrize("spelling", ["relative", "absolute", "tilde"])
async def test_explicit_default_is_lazy_cwd_anchored_and_created_privately_only_on_save(
    tmp_path, monkeypatch, spelling
):
    monkeypatch.setenv("HOME", str(tmp_path))
    selected = tmp_path / "nested" / "exports"
    root = (
        Path("nested/exports")
        if spelling == "relative"
        else Path("~/nested/exports")
        if spelling == "tilde"
        else selected
    )
    with monkeypatch.context() as construction:

        def forbidden(*args, **kwargs):
            pytest.fail("App construction accessed the export directory")

        for operation in ("directory", "scan", "publish"):
            construction.setattr(ArtifactFiles, operation, forbidden)
        app = app_for(tmp_path, root)
    assert app.exports.service.default_root == selected and app.exports.directory == selected
    assert not selected.exists()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    async with app.run_test(size=(100, 30)) as pilot:
        await wait_for(
            lambda: (
                isinstance(app.screen, ArtifactBrowserScreen)
                and app.screen.listing is not None
                and app.screen.operation_count == 0
            )
        )
        assert not app.screen.entries and "No saved exports" in str(app.screen.status.content)
        assert not selected.exists() and app.sessions.client is None
        await pilot.press("escape")
        review = await reviewed(app)
        assert review.location.value == str(selected) and not selected.exists()
        await pilot.click("#export-save")
        await wait_for(lambda: review.stopped and review not in app.screen_stack)
        destination = selected / "kuberich-screen.txt"
        prepared = read_artifact(destination.read_bytes(), artifact_id=uuid4())
        assert "owned export directory" in prepared.preview
        assert stat.S_IMODE(destination.stat().st_mode) == 0o600
        assert (
            stat.S_IMODE(selected.stat().st_mode)
            == stat.S_IMODE(selected.parent.stat().st_mode)
            == 0o700
        )
        assert not (elsewhere / "nested").exists()
        review = await reviewed(app)
        other = tmp_path / "other-missing"
        review.location.value = str(other)
        await wait_for(lambda: review.ready_to_save)
        await pilot.click("#export-save")
        await wait_for(lambda: "directory is missing" in str(review.status.content))
        assert not other.exists()
        await pilot.press("escape")
        assert app.exports.directory == selected and app.exports.operation_count == 0
        assert app.sessions.client is None and app.sessions.generation == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("problem", ["parent", "symlink", "writable"])
async def test_explicit_root_physical_refusal_is_reported_by_scan_and_save(tmp_path, problem):
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    if problem == "parent":
        root = tmp_path / "nested" / ".." / "missing"
    elif problem == "symlink":
        (tmp_path / "linked").symlink_to(outside, target_is_directory=True)
        root = tmp_path / "linked" / "missing"
    else:
        root = tmp_path / "writable"
        root.mkdir(mode=0o700)
        root.chmod(0o770)
    app = app_for(tmp_path, root)
    async with app.run_test() as pilot:
        await wait_for(
            lambda: (
                isinstance(app.screen, ArtifactBrowserScreen)
                and "Cannot access" in str(app.screen.status.content)
                and app.screen.operation_count == 0
            )
        )
        assert app.screen.listing is None and not app.screen.entries
        await pilot.press("escape")
        review = await reviewed(app)
        await pilot.click("#export-save")
        await wait_for(lambda: "Cannot access" in str(review.status.content))
        assert not list(outside.iterdir())
        if problem == "writable":
            assert stat.S_IMODE(root.stat().st_mode) == 0o770 and not list(root.iterdir())
        else:
            assert not (tmp_path / "missing").exists() and not (outside / "missing").exists()
        await pilot.press("escape")
        assert app.exports.operation_count == 0 and app.sessions.client is None
