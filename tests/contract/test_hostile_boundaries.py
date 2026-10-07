"""Hostile selected text stays literal in real child argv and exclusive exports."""

import json
import os
import sys

import pytest

from kubetrol.domain.processes import ProcessMode, ProcessPurpose, capture_command
from kubetrol.errors import AppError
from kubetrol.security.presentation import safe_text
from kubetrol.services.access import AccessPolicy
from kubetrol.services.log_export import save_logs
from kubetrol.services.processes import ProcessRunner


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "selected",
    [
        "$(touch sentinel)",
        "`touch sentinel`",
        "; touch sentinel #",
        "${HOME}",
        "' ; touch sentinel ; '",
        '" ; touch sentinel ; "',
        "--context=other",
        "../../outside",
        "[link=https://attacker.invalid]pod[/link]",
        "pod with spaces 你好",
    ],
)
async def test_selected_substitution_values_are_literal_in_actual_process(tmp_path, selected):
    command = capture_command(
        [sys.executable, "-I", "-c", "import json,sys; print(json.dumps(sys.argv[1:]))", selected],
        environment={"PATH": os.environ.get("PATH", "")},
        directory=tmp_path,
        mode=ProcessMode.CAPTURE,
        purpose=ProcessPurpose.PLUGIN,
    )
    async with ProcessRunner(AccessPolicy(False)) as runner:
        result = await runner.capture(command, timeout=5)
        assert result.returncode == 0 and json.loads(result.stdout) == [selected]
        assert runner.active_count == 0
    assert not (tmp_path / "sentinel").exists()
    text = safe_text(selected)
    assert not text.spans and text.plain == selected


@pytest.mark.asyncio
async def test_export_does_not_replace_raced_files_hardlinks_dangling_links_or_directories(
    tmp_path, monkeypatch
):
    original = tmp_path / "original"
    original.write_text("preserve original")
    hardlink = tmp_path / "hardlink"
    os.link(original, hardlink)
    dangling = tmp_path / "dangling"
    dangling.symlink_to(tmp_path / "absent")
    directory = tmp_path / "directory"
    directory.mkdir()
    for path in (original, hardlink, dangling, directory):
        with pytest.raises(AppError):
            await save_logs(str(path), "overwrite attempted")
    assert original.read_text() == hardlink.read_text() == "preserve original"
    assert dangling.is_symlink() and not (tmp_path / "absent").exists()
    assert directory.is_dir() and not list(directory.iterdir())
    destination = tmp_path / "raced"
    link = os.link

    def raced_link(source, target):
        destination.write_text("created by another writer")
        link(source, target)

    monkeypatch.setattr(os, "link", raced_link)
    with pytest.raises(AppError):
        await save_logs(str(destination), "overwrite attempted")
    assert destination.read_text() == "created by another writer"
    assert not list(tmp_path.glob(".kubetrol-log-*"))
