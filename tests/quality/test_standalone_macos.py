"""Deployment floors come from original Mach-O commands, never a manifest label."""

import struct

import pytest

from scripts.standalone import macos_minimum


def binary(*commands):
    header = bytearray(32)
    header[:4] = b"\xcf\xfa\xed\xfe"
    struct.pack_into("<II", header, 16, len(commands), sum(map(len, commands)))
    return bytes(header) + b"".join(commands)


def build_version(*, version=0x000E0302, platform=1, tools=0):
    return struct.pack("<6I", 0x32, 24, platform, version, 0x001A0000, tools)


def test_original_modern_and_legacy_commands_report_the_actual_minimum():
    assert macos_minimum(binary(build_version())) == (14, 3, 2)
    assert macos_minimum(binary(struct.pack("<4I", 0x24, 16, 0x000A0D00, 0x000E0000))) == (
        10,
        13,
        0,
    )
    assert macos_minimum(
        binary(struct.pack("<2I", 0x1D, 8), build_version(version=0x000F0000))
    ) == (15, 0, 0)


@pytest.mark.parametrize(
    "content",
    [
        b"not a native binary",
        binary(),
        binary(struct.pack("<2I", 0x1D, 8)),
        binary(build_version())[:-1],
        binary(struct.pack("<2I", 0x32, 0)),
        binary(build_version(platform=2)),
        binary(build_version(), build_version()),
        binary(build_version(tools=1)),
        binary(build_version(version=0)),
    ],
)
def test_missing_truncated_duplicate_or_non_macos_deployment_cannot_pass(content):
    with pytest.raises(ValueError):
        macos_minimum(content)


def test_complete_tool_commands_remain_valid_but_forged_total_size_fails():
    command = struct.pack("<8I", 0x32, 32, 1, 0x000E0000, 0x001A0000, 1, 3, 0x01000000)
    assert macos_minimum(binary(command)) == (14, 0, 0)
    invalid = bytearray(binary(command))
    struct.pack_into("<I", invalid, 20, 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="excessive"):
        macos_minimum(bytes(invalid))
