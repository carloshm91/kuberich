"""Owned runner-source fixtures preserve authentication and refuse unknown input."""

import pytest

from scripts.ci_apt_sources import (
    KEYRING,
    MAX_SOURCE_BYTES,
    MIRROR_URI,
    mirror_for_architecture,
    rewrite,
    source_bytes,
    source_changes,
)


def stanza(uri, *, suites="noble noble-updates noble-backports noble-security", extra=""):
    return (
        "# image-owned Ubuntu source\nTypes: deb deb-src\nURIs: "
        + uri
        + "\nSuites: "
        + suites
        + "\nComponents: main restricted universe multiverse\nSigned-By: "
        + KEYRING
        + "\nArchitectures: amd64 arm64\n"
        + extra
    ).encode()


@pytest.mark.parametrize("architecture", ["amd64", "arm64"])
@pytest.mark.parametrize("format", [".list", ".sources"])
def test_actual_direct_formats_preserve_suites_components_architecture_and_keyring(
    architecture, format
):
    origin = (
        "http://archive.ubuntu.com/ubuntu"
        if architecture == "amd64"
        else "http://ports.ubuntu.com/ubuntu-ports"
    )
    body = (
        f"# retained\ndeb [arch={architecture} signed-by={KEYRING}] {origin} jammy-security main universe # retained\n".encode()
        if format == ".list"
        else stanza(origin, suites="jammy jammy-security")
    )
    changed, count, indirect = rewrite(body, format, architecture)
    assert changed == body.replace(origin.encode(), mirror_for_architecture(architecture).encode())
    assert count == 1 and not indirect and KEYRING.encode() in changed
    assert rewrite(changed, format, architecture) == (changed, 1, False)


def test_mirror_indirection_is_changed_only_in_the_actual_referenced_file(tmp_path):
    sources, directory, mirrors = (
        tmp_path / "sources.list",
        tmp_path / "parts",
        tmp_path / "mirrors",
    )
    directory.mkdir()
    ubuntu = directory / "ubuntu.sources"
    original = stanza(MIRROR_URI)
    ubuntu.write_bytes(original)
    mirrors.write_text(
        "http://azure.archive.ubuntu.com/ubuntu\nhttps://archive.ubuntu.com/ubuntu\n"
    )
    changes = source_changes("amd64", sources, directory, mirrors)
    assert len(changes) == 1 and changes[0].path == mirrors
    assert changes[0].replacement == b"https://mirrors.mit.edu/ubuntu\n"
    assert ubuntu.read_bytes() == original
    assert "archive.ubuntu.com" not in repr(changes)


def test_actual_arm_one_line_source_is_changed_when_no_mirror_file_exists(tmp_path):
    source, directory, mirror = tmp_path / "sources.list", tmp_path / "parts", tmp_path / "absent"
    original = (
        b"deb http://ports.ubuntu.com/ubuntu-ports jammy main restricted universe multiverse\n"
    )
    source.write_bytes(original)
    changes = source_changes("arm64", source, directory, mirror)
    assert len(changes) == 1 and changes[0].path == source
    assert changes[0].original == original
    assert changes[0].replacement == original.replace(
        b"http://ports.ubuntu.com/ubuntu-ports", b"https://mirrors.mit.edu/ubuntu-ports"
    )
    assert not mirror.exists() and source.read_bytes() == original


def test_unrelated_sources_comments_disabled_stanzas_and_crlf_stay_byte_exact():
    microsoft = b"Types: deb\nURIs: https://packages.microsoft.com/ubuntu/24.04/prod\nSuites: noble\nComponents: main\nSigned-By: /usr/share/keyrings/microsoft-prod.gpg\n"
    disabled = stanza("http://archive.ubuntu.com/ubuntu", extra="Enabled: no\n")
    original = microsoft + b"\n" + disabled + b"\n" + stanza("https://archive.ubuntu.com/ubuntu/")
    original = original.replace(b"\n", b"\r\n")
    changed, count, indirect = rewrite(original, ".sources", "amd64")
    assert count == 1 and not indirect
    assert changed == original.replace(
        b"URIs: https://archive.ubuntu.com/ubuntu/", b"URIs: https://mirrors.mit.edu/ubuntu/"
    )
    line = b"deb https://packages.microsoft.com/ubuntu/24.04/prod noble main\n# deb http://archive.ubuntu.com/ubuntu noble main\n"
    assert rewrite(line, ".list", "amd64") == (line, 0, False)


@pytest.mark.parametrize(
    "body,format",
    [
        (b"rpm http://archive.ubuntu.com/ubuntu noble main\n", ".list"),
        (b"deb http://archive.ubuntu.com/ubuntu noble\n", ".list"),
        (b"deb [trusted=yes] http://archive.ubuntu.com/ubuntu noble main\n", ".list"),
        (b"deb [signed-by=/new/key.gpg] http://archive.ubuntu.com/ubuntu noble main\n", ".list"),
        (b"deb [arch] http://archive.ubuntu.com/ubuntu noble main\n", ".list"),
        (b"deb [arch=amd64 arch=amd64] http://archive.ubuntu.com/ubuntu noble main\n", ".list"),
        (b"deb http://archive.ubuntu.com/ubuntu unknown main\n", ".list"),
        (b"deb http://archive.ubuntu.com/ubuntu noble unknown\n", ".list"),
        (b"deb https://user:credential@archive.ubuntu.com/ubuntu noble main\n", ".list"),
        (b"deb https://archive.ubuntu.com/other noble main\n", ".list"),
        (stanza("https://archive.ubuntu.com/ubuntu", extra="Trusted: yes\n"), ".sources"),
        (stanza("https://archive.ubuntu.com/ubuntu", extra="Suites: noble\n"), ".sources"),
        (stanza("https://archive.ubuntu.com/ubuntu", extra=" Enabled: yes\n"), ".sources"),
        (stanza("https://archive.ubuntu.com/ubuntu", extra="Enabled: unknown\n"), ".sources"),
        (
            stanza("https://archive.ubuntu.com/ubuntu").replace(
                b"Types: deb deb-src", b"Types: rpm"
            ),
            ".sources",
        ),
        (
            stanza("https://archive.ubuntu.com/ubuntu").replace(b"Types: deb deb-src\n", b""),
            ".sources",
        ),
        (stanza("https://archive.ubuntu.com/ubuntu https://unreviewed.example/ubuntu"), ".sources"),
        (stanza("mirror+file:/arbitrary/file"), ".sources"),
        (b"\x00", ".list"),
        (b"\xff", ".list"),
        (b"x" * (MAX_SOURCE_BYTES + 1), ".list"),
        (b"", ".unknown"),
    ],
)
def test_unknown_or_insecure_ubuntu_formats_refuse_without_source_values(body, format):
    with pytest.raises(ValueError) as error:
        rewrite(body, format, "amd64")
    assert "credential" not in str(error.value)


@pytest.mark.parametrize("entry", ["symlink", "directory", "oversized"])
def test_unsafe_source_file_is_not_read(entry, tmp_path):
    path = tmp_path / "owned.list"
    original = tmp_path / "unrelated"
    original.write_text("retained")
    if entry == "symlink":
        path.symlink_to(original)
    elif entry == "directory":
        path.mkdir()
    else:
        path.write_bytes(b"x" * (MAX_SOURCE_BYTES + 1))
    with pytest.raises(ValueError):
        source_bytes(path)
    assert original.read_text() == "retained"


@pytest.mark.parametrize(
    "failure",
    [
        "no-source",
        "directory-link",
        "inventory",
        "too-many-changes",
        "mirror-format",
        "empty-mirror",
    ],
)
def test_complete_inventory_is_validated_before_any_source_mutation(tmp_path, failure):
    source, directory, mirror = tmp_path / "sources.list", tmp_path / "parts", tmp_path / "mirrors"
    source.write_text("deb http://archive.ubuntu.com/ubuntu noble main\n")
    directory.mkdir()
    if failure == "no-source":
        source.write_text("# no active Ubuntu source\n")
    elif failure == "directory-link":
        directory.rmdir()
        directory.symlink_to(tmp_path / "absent", target_is_directory=True)
    elif failure == "inventory":
        for index in range(65):
            (directory / str(index)).touch()
    elif failure == "too-many-changes":
        for index in range(2):
            (directory / f"{index}.list").write_bytes(source.read_bytes())
    else:
        source.write_bytes(stanza(MIRROR_URI))
        source = source.rename(tmp_path / "ubuntu.sources")
        mirror.write_text(
            "https://unreviewed.example/ubuntu\n" if failure == "mirror-format" else ""
        )
        (directory / "ubuntu.sources").write_bytes(source.read_bytes())
    original = source.read_bytes()
    with pytest.raises(ValueError):
        source_changes("amd64", source, directory, mirror)
    assert source.read_bytes() == original
