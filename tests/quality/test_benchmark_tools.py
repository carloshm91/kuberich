"""Official platform provenance, bounded acquisition and explicit authenticated execution."""

import hashlib
import io
import json
import os
import stat
import sys
import tarfile
from dataclasses import replace

import pytest

from kuberich.errors import AppError
from scripts import benchmark_tools as tools

BINARY = b"synthetic Vegeta bytes; provisioning must never execute this file"


def archive_bytes(*, fault="", binary=BINARY):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        names = [] if fault == "empty" else ["elsewhere" if fault == "wrong" else "vegeta"]
        if fault in {"duplicate", "traversal"}:
            names.append("vegeta" if fault == "duplicate" else "../../escaped")
        for name in names:
            member = tarfile.TarInfo(name)
            if fault in {"symlink", "hardlink"}:
                member.type = tarfile.SYMTYPE if fault == "symlink" else tarfile.LNKTYPE
                member.linkname = "../../escaped"
                archive.addfile(member)
            else:
                member.size = len(binary) + (1 if fault == "size" else 0)
                archive.addfile(member, io.BytesIO(binary + (b"x" if fault == "size" else b"")))
    return stream.getvalue()


@pytest.fixture
def synthetic(monkeypatch):
    payload = archive_bytes()
    pin = tools.BenchmarkPin(
        "linux",
        "amd64",
        hashlib.sha256(payload).hexdigest(),
        hashlib.sha256(BINARY).hexdigest(),
        len(BINARY),
    )
    state = {"pin": pin, "archive": payload, "requests": [], "probes": []}
    monkeypatch.setattr(tools, "BENCHMARK_PINS", (pin,))
    monkeypatch.setattr(tools.platform, "system", lambda: "Linux")
    monkeypatch.setattr(tools.platform, "machine", lambda: "x86_64")

    def response(url, timeout):
        state["requests"].append((url, timeout))
        return io.BytesIO(state["archive"])

    async def probe(path):
        state["probes"].append(path)
        return "12.13.0"

    monkeypatch.setattr(tools, "urlopen", response)
    monkeypatch.setattr(tools, "probe_version", probe)
    return state


def test_reviewed_official_platform_pins_are_complete_and_linux_digest_independent():
    assert {(pin.system, pin.machine) for pin in tools.BENCHMARK_PINS} == {
        ("linux", "amd64"),
        ("linux", "arm64"),
        ("darwin", "amd64"),
        ("darwin", "arm64"),
    }
    assert tools.VEGETA_COMMIT == "507c4f028fbad80168f3b734dab9530d3aabfefa"
    assert (
        tools.CHECKSUM_SHA256 == "384239c939594c6a4e3b1da4b336728a0d70ed8e77636af92984cdf036a816e7"
    )
    pin = tools.benchmark_pin(system="Linux", machine="x86_64")
    assert pin.binary_sha256 == "c54d905541485153542dfcb850f9ab8ef801e7ab1a652d2cfc69cafdd4a5363f"
    assert pin.binary_bytes == 10940568
    for candidate in tools.BENCHMARK_PINS:
        assert len(candidate.archive_sha256) == len(candidate.binary_sha256) == 64
        assert bytes.fromhex(candidate.archive_sha256) and bytes.fromhex(candidate.binary_sha256)
        assert candidate.binary_bytes <= tools.MAX_BINARY_BYTES
    assert tools.benchmark_pin(system="Darwin", machine="aarch64").machine == "arm64"
    assert tools.benchmark_pin(system="linux", machine="AMD64").machine == "amd64"
    for system, machine in (("Windows", "amd64"), ("linux", "arm"), ("darwin", "arm64e")):
        with pytest.raises(ValueError):
            tools.benchmark_pin(system=system, machine=machine)


def test_provisioning_does_not_execute_and_reuses_exact_original_bytes(tmp_path, synthetic):
    root = tmp_path / "tools"
    path = tools.prepare_benchmark_tool(root)
    assert path == root / "vegeta" and path.read_bytes() == BINARY
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o500
    provenance = json.loads((root / "prepared-provenance.json").read_bytes())
    assert provenance["binary_sha256"] == synthetic["pin"].binary_sha256
    assert provenance["host_executed"] is False and provenance["license"] == "MIT"
    assert "signatures not verified" in provenance["verification"]
    assert tools.prepare_benchmark_tool(root) == path and len(synthetic["requests"]) == 1
    assert not synthetic["probes"]
    assert tools.verify_benchmark_binary(path) == synthetic["pin"].binary_sha256
    assert synthetic["probes"] == [path]


@pytest.mark.parametrize(
    "fault", ["empty", "wrong", "duplicate", "traversal", "symlink", "hardlink", "size", "binary"]
)
def test_authenticated_archive_rejects_unexpected_members_and_binary_bytes(
    tmp_path, monkeypatch, synthetic, fault
):
    payload = archive_bytes(fault=fault, binary=b"bad bytes" if fault == "binary" else BINARY)
    synthetic["archive"] = payload
    pin = replace(synthetic["pin"], archive_sha256=hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(tools, "BENCHMARK_PINS", (pin,))
    root = tmp_path / "tools"
    with pytest.raises(ValueError):
        tools.prepare_benchmark_tool(root)
    assert not (root / "vegeta").exists() and not (tmp_path / "escaped").exists()
    assert not synthetic["probes"]


def test_bad_archive_checksum_prevents_tar_open_or_binary_publication(
    tmp_path, monkeypatch, synthetic
):
    synthetic["archive"] = b"unreviewed bytes"
    monkeypatch.setattr(
        tools.tarfile, "open", lambda **kwargs: pytest.fail("unauthenticated archive opened")
    )
    with pytest.raises(ValueError, match="checksum"):
        tools.prepare_benchmark_tool(tmp_path / "tools")
    assert not (tmp_path / "tools/vegeta").exists()


@pytest.mark.parametrize("name", ["archive", "vegeta", "prepared-provenance.json"])
@pytest.mark.parametrize("fault", ["corrupt", "symlink", "hardlink", "directory"])
def test_cached_inputs_never_overwrite_or_follow_links(tmp_path, synthetic, name, fault):
    root = tmp_path / "tools"
    path = tools.prepare_benchmark_tool(root)
    target = root / (synthetic["pin"].archive if name == "archive" else name)
    original = target.read_bytes()
    target.unlink()
    outside = tmp_path / "outside"
    outside.write_bytes(original)
    if fault == "corrupt":
        target.write_bytes(b"original corrupt input")
    elif fault == "symlink":
        target.symlink_to(outside)
    elif fault == "hardlink":
        os.link(outside, target)
    else:
        target.mkdir()
    requests = list(synthetic["requests"])
    with pytest.raises((ValueError, OSError)):
        tools.prepare_benchmark_tool(root)
    assert outside.read_bytes() == original and synthetic["requests"] == requests
    assert not synthetic["probes"] and path.parent == root


def test_physical_paths_block_symlink_ancestors_relative_and_unsafe_permissions(
    tmp_path, synthetic
):
    physical = tmp_path / "physical"
    physical.mkdir(mode=0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(physical, target_is_directory=True)
    for path in (alias / "child", tmp_path / "bad\n", tmp_path / "a/../b"):
        with pytest.raises((ValueError, OSError)):
            tools.prepare_benchmark_tool(path)
    with pytest.raises(ValueError):
        tools.prepare_benchmark_tool(type(tmp_path)("relative"))
    assert not (physical / "child").exists() and not synthetic["requests"]
    physical.chmod(0o777)
    with pytest.raises(ValueError):
        tools.prepare_benchmark_tool(physical)


@pytest.mark.parametrize("fault", ["mode", "bytes", "foreign", "name", "missing", "relative"])
def test_explicit_verifier_refuses_unknown_host_bytes_before_execution(
    tmp_path, monkeypatch, synthetic, fault
):
    path = tools.prepare_benchmark_tool(tmp_path / "tools")
    if fault == "mode":
        path.chmod(0o600)
    elif fault == "bytes":
        path.chmod(0o600)
        path.write_bytes(b"changed")
    elif fault == "foreign":
        monkeypatch.setattr(tools.platform, "machine", lambda: "arm64")
    elif fault == "name":
        path = path.with_name("renamed")
    elif fault == "missing":
        path.unlink()
    else:
        path = type(path)("relative/vegeta")
    with pytest.raises((ValueError, OSError)):
        tools.verify_benchmark_binary(path)
    assert not synthetic["probes"]


def test_failed_download_is_retained_and_not_repaired_on_retry(tmp_path, monkeypatch, synthetic):
    class Interrupted(io.BytesIO):
        def read(self, size=-1):
            if self.tell():
                raise OSError("synthetic interruption")
            return super().read(size)

    monkeypatch.setattr(tools, "urlopen", lambda *args, **kwargs: Interrupted(b"partial input"))
    root = tmp_path / "tools"
    with pytest.raises(OSError, match="interruption"):
        tools.prepare_benchmark_tool(root)
    archive = root / synthetic["pin"].archive
    assert archive.read_bytes() == b"partial input"
    monkeypatch.setattr(
        tools, "urlopen", lambda *args, **kwargs: pytest.fail("partial download was replaced")
    )
    with pytest.raises(ValueError, match="checksum"):
        tools.prepare_benchmark_tool(root)
    assert archive.read_bytes() == b"partial input"


def test_download_bound_keeps_only_written_prefix(tmp_path, monkeypatch, synthetic):
    monkeypatch.setattr(tools, "MAX_ARCHIVE_BYTES", 65536)
    synthetic["archive"] = b"x" * 65537
    with pytest.raises(ValueError, match="download bound"):
        tools.prepare_benchmark_tool(tmp_path / "tools")
    assert (tmp_path / "tools" / synthetic["pin"].archive).stat().st_size == 65536


def test_cli_has_exact_path_and_provenance_contract_without_execution(
    tmp_path, monkeypatch, synthetic, capsys
):
    root = tmp_path / "tools"
    monkeypatch.setattr(
        "sys.argv",
        ["benchmark_tools", "--directory", str(root), "--system", "linux", "--machine", "amd64"],
    )
    tools.main()
    assert json.loads(capsys.readouterr().out) == {
        "vegeta": str(root / "vegeta"),
        "host_executed": False,
    }
    assert (root / "prepared-provenance.json").is_file() and not synthetic["probes"]


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["", "exit", "overflow", "version", "timeout"])
async def test_explicit_real_version_probe_is_bounded_and_discards_errors(tmp_path, fault):
    path = tmp_path / "vegeta"
    output = "Version: v12.13.0\\nCommit: abc\\nRuntime: go1 linux/amd64\\nDate: today\\n"
    body = f"print('{output}',end='')"
    if fault == "exit":
        body = "import sys;sys.stderr.write('credential=private');sys.exit(2)"
    elif fault == "overflow":
        body = "print('x'*20000)"
    elif fault == "version":
        body = "print('unsupported credential=private')"
    elif fault == "timeout":
        body = "import time;time.sleep(60)"
    path.write_text(f"#!{sys.executable}\n{body}\n")
    path.chmod(0o500)
    if fault:
        with pytest.raises((ValueError, AppError)) as error:
            await tools.probe_version(path)
        assert "private" not in str(error.value)
    else:
        assert await tools.probe_version(path) == "12.13.0"
