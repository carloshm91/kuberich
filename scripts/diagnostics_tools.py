"""Acquire the pinned official Popeye fixture tool; production never downloads tools."""

import argparse
import hashlib
import json
import os
import stat
import tarfile
from pathlib import Path
from urllib.request import urlopen

POPEYE_VERSION = "0.22.1"
POPEYE_COMMIT = "35b554961dcdabfa7aba6bd070673c6c24c70884"
POPEYE_TAG_OBJECT = "eedda1e7b6014ff773678c6c83421220a9aead1d"
POPEYE_ARCHIVE = "popeye_linux_amd64.tar.gz"
POPEYE_ARCHIVE_SHA256 = "d58a3c0ba45805d452c32628320eecdcb5172fd5f42c82e12aeecc7a17eb930b"
POPEYE_BINARY_SHA256 = "a9af3fd43bffbf3b4099e68a18e9b1c6a8c1ec735d33390d5fe61ddbb0ffab11"
POPEYE_CHECKSUM_SHA256 = "ace23b878722c6457849c10c8d35b2f66d54cca1ea59d8d527cd0b8b5ed46fe8"
POPEYE_BINARY_BYTES = 71192728
POPEYE_RELEASE_URL = "https://github.com/derailed/popeye/releases/download/v0.22.1/"
KIND_SHA256 = "aee6151561422756b764a4ae28e7f44cda5af5a9eead3cc9985112b1de8d8e0d"
RUNTIME_IMAGE = (
    "python:3.12-slim@sha256:090ba77e2958f6af52a5341f788b50b032dd4ca28377d2893dcf1ecbdfdfe203"
)


def sha256_file(path: Path) -> str:
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("Qualification tools require regular files, never links or devices.")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_popeye_binary(path: Path) -> str:
    if not path.is_absolute() or sha256_file(path) != POPEYE_BINARY_SHA256:
        raise ValueError(
            "Qualification requires the checksum-verified official Linux amd64 Popeye v0.22.1."
        )
    if path.stat().st_size != POPEYE_BINARY_BYTES or not path.stat().st_mode & 0o111:
        raise ValueError(
            "The verified Popeye fixture must have its original size and executable permission."
        )
    return POPEYE_BINARY_SHA256


def download_asset(name: str, destination: Path, limit: int) -> None:
    if name not in ("checksums.sha256", POPEYE_ARCHIVE):
        raise ValueError("Only the fixed official Popeye release assets may be acquired.")
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with (
        os.fdopen(descriptor, "wb") as output,
        urlopen(POPEYE_RELEASE_URL + name, timeout=30) as response,
    ):
        count = 0
        while chunk := response.read(1024 * 1024):
            count += len(chunk)
            if count > limit:
                raise ValueError("Official Popeye release asset exceeds its fixed download bound.")
            output.write(chunk)


def tool_provenance() -> dict[str, object]:
    return {
        "producer_version": POPEYE_VERSION,
        "parser_id": "popeye-json/0.22.1",
        "source_commit": POPEYE_COMMIT,
        "annotated_tag_object": POPEYE_TAG_OBJECT,
        "tag_signature": "unsigned; no artifact signature attestation is claimed",
        "release_url": "https://github.com/derailed/popeye/releases/tag/v0.22.1",
        "checksum_url": POPEYE_RELEASE_URL + "checksums.sha256",
        "archive_url": POPEYE_RELEASE_URL + POPEYE_ARCHIVE,
        "checksum_file_sha256": POPEYE_CHECKSUM_SHA256,
        "archive_sha256": POPEYE_ARCHIVE_SHA256,
        "binary_sha256": POPEYE_BINARY_SHA256,
        "binary_bytes": POPEYE_BINARY_BYTES,
        "host_executed": False,
    }


def prepare_diagnostics_tool(directory: Path) -> Path:
    """Return an absolute verified binary; retain bad/partial inputs without overwriting."""
    if not directory.is_absolute() or directory.is_symlink():
        raise ValueError("Use an explicit absolute owned tool directory.")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    checksum = directory / "checksums.sha256"
    archive = directory / POPEYE_ARCHIVE
    binary = directory / "popeye"
    if not any(path.exists() for path in (checksum, archive, binary)):
        download_asset("checksums.sha256", checksum, 16384)
        download_asset(POPEYE_ARCHIVE, archive, 32 * 1024 * 1024)
    if sha256_file(checksum) != POPEYE_CHECKSUM_SHA256:
        raise ValueError("Official Popeye checksum file does not match the pinned release.")
    listed = [
        line.split()[0]
        for line in checksum.read_text().splitlines()
        if len(line.split()) == 2 and line.split()[1] == POPEYE_ARCHIVE
    ]
    if listed != [POPEYE_ARCHIVE_SHA256] or sha256_file(archive) != POPEYE_ARCHIVE_SHA256:
        raise ValueError("Popeye archive does not match its official pinned checksum.")
    if not binary.exists():
        with tarfile.open(archive) as contents:
            member = contents.getmember("popeye")
            if not member.isfile() or member.size != POPEYE_BINARY_BYTES:
                raise ValueError("Official Popeye archive has an unexpected binary member.")
            source = contents.extractfile(member)
            assert source is not None
            data = source.read(POPEYE_BINARY_BYTES + 1)
        if hashlib.sha256(data).hexdigest() != POPEYE_BINARY_SHA256:
            raise ValueError("Extracted Popeye binary differs from the verified release.")
        descriptor = os.open(binary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o500)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
    verify_popeye_binary(binary)
    provenance = directory / "prepared-provenance.json"
    encoded = json.dumps(tool_provenance(), indent=2) + "\n"
    if provenance.exists() and provenance.read_text() != encoded:
        raise ValueError("Earlier tool provenance differs; use a fresh owned directory.")
    if not provenance.exists():
        provenance.write_text(encoded)
    return binary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    arguments = parser.parse_args()
    path = prepare_diagnostics_tool(arguments.directory)
    print(json.dumps({"popeye": str(path), "binary_sha256": POPEYE_BINARY_SHA256}))


if __name__ == "__main__":
    main()
