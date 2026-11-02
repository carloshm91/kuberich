"""Site images come from the real local application and preserve redaction."""

import hashlib
import json
import subprocess

import pytest

from scripts.capture_site import capture, historical_svg, source_snapshot


@pytest.mark.asyncio
async def test_reproduces_both_actual_views_without_a_cluster_or_historical_image(tmp_path):
    output = tmp_path / "new-media"
    await capture(output)
    inventory = json.loads((output / "media.json").read_text())
    assert inventory["private_data_used"] is False
    assert inventory["source_clean"] is True
    assert inventory["imported_application_matches_source"] is True
    assert inventory["redaction_verified"] is True
    assert inventory["cleanup"] == {
        "application_client_released": True,
        "client_api_released": True,
        "client_pool_closed": True,
        "log_stream_handler_closed": True,
        "resource_handlers_active": 0,
        "loopback_api_context_closed": True,
        "temporary_directory_removed": True,
    }
    assert inventory["owned_log_requests"] >= 1 and inventory["owned_requests"] >= 3
    assert inventory["images"]["workspace.svg"]["terminal_cells"] == [120, 30]
    assert inventory["images"]["logs.svg"]["terminal_cells"] == [100, 30]
    for name, image in inventory["images"].items():
        content = (output / name).read_bytes()
        assert hashlib.sha256(content).hexdigest() == image["sha256"]
        assert b"KubeRich" in content and b"demo-apps" in content
        assert b"127.0.0.1" not in content and b"synthetic" not in content
        assert b"@font-face" not in content
    logs = (output / "logs.svg").read_text()
    assert "request-finished" in logs and "redacted" in logs.lower()
    assert "Actual Textual log viewer" in inventory["images"]["logs.svg"]["source"]
    assert "--logs-source" not in inventory["capture_command"]


@pytest.mark.asyncio
async def test_existing_destination_is_not_overwritten(tmp_path):
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "keep").write_text("previous image")
    with pytest.raises(ValueError, match="must be new"):
        await capture(existing)
    assert (existing / "keep").read_text() == "previous image"


@pytest.mark.asyncio
async def test_imported_image_is_explicitly_not_regenerated_or_privacy_certified(tmp_path):
    previous = tmp_path / "previous.svg"
    previous.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><text>KubeRich older demo</text></svg>'
    )
    output = tmp_path / "new-media"
    await capture(output, previous)
    inventory = json.loads((output / "media.json").read_text())
    assert inventory["private_data_used"] is None
    assert inventory["images"]["logs.svg"]["terminal_cells"] is None
    assert "not regenerated" in inventory["images"]["logs.svg"]["source"]
    assert (output / "logs.svg").read_text() == previous.read_text()


@pytest.mark.parametrize(
    "body",
    [
        '<svg xmlns="http://www.w3.org/2000/svg"><script>KubeRich</script></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><text>KubeRich</text></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><use href="https://private.invalid/a"/><text>KubeRich</text></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><style>@import "https://private.invalid/a";</style><text>KubeRich</text></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="url(https://private.invalid/a)"/><text>KubeRich</text></svg>',
        r'<svg xmlns="http://www.w3.org/2000/svg"><style>rect {fill:u\72l(https://private.invalid/a)}</style><text>KubeRich</text></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><text>Other tool</text></svg>',
        "<svg>KubeRich</svg>",
        "not SVG",
    ],
)
def test_import_refuses_active_remote_and_unidentified_svg_before_capture(tmp_path, body):
    source = tmp_path / "source.svg"
    source.write_text(body)
    with pytest.raises(ValueError):
        historical_svg(source)


def test_import_removes_rich_remote_font_declarations_but_keeps_local_vector(tmp_path):
    source = tmp_path / "source.svg"
    source.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><style>@font-face {src:url(https://fonts.invalid/font)} rect {fill:url(#local)}</style><text>KubeRich</text></svg>'
    )
    result = historical_svg(source)
    assert "@font-face" not in result and "fonts.invalid" not in result
    assert "url(#local)" in result


@pytest.mark.parametrize("fault", ["tracked", "untracked"])
def test_source_snapshot_refuses_dirty_runtime_bytes_in_a_real_git_checkout(tmp_path, fault):
    package = tmp_path / "src/kuberich"
    package.mkdir(parents=True)
    runtime = package / "__init__.py"
    runtime.write_text('"""Owned source fixture."""\n')
    (tmp_path / "pyproject.toml").write_text('[project]\nname="kuberich"\nversion="0.2.0"\n')
    for argv in [
        ["init", "--quiet"],
        ["add", "."],
        [
            "-c",
            "user.name=Owned Capture Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "-m",
            "Record capture source",
        ],
    ]:
        subprocess.run(["git", "-C", str(tmp_path), *argv], check=True, capture_output=True)
    commit, tree, version = source_snapshot(tmp_path)
    assert len(commit) == len(tree) == 40 and version == "0.2.0"
    (runtime if fault == "tracked" else package / "extra.py").write_text("changed = True\n")
    with pytest.raises(ValueError, match="clean and committed"):
        source_snapshot(tmp_path)
