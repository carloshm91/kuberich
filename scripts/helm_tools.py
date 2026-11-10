"""Acquire exact official Helm fixtures; the application never downloads tools."""

import argparse
import hashlib
import json
import os
import stat
import tarfile
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.request import urlopen


@dataclass(frozen=True)
class HelmPin:
    version: str
    source_commit: str
    checksum_sha256: str
    archive_sha256: str
    binary_sha256: str
    binary_bytes: int

    @property
    def archive(self) -> str:
        return f"helm-{self.version}-linux-amd64.tar.gz"


HELM_PINS = (
    HelmPin(
        "v3.22.1",
        "d6c1a0e4027caa6abc7892e7ea9f0cda7447baa3",
        "0df8a92d94a9dbbdf0f6c691b54cf8464e50f707ff83c1eb1771a0ac156798d0",
        "896cf63684a42a723d61c980369d6e588330927deb13676ca0d85006dd6da0ea",
        "46aeab5e043f62d01f7c168823b392cabc1cea3807b67906296290483791be43",
        61702306,
    ),
    HelmPin(
        "v4.3.1",
        "c0d08d0d6d9424d4a14febb5e8a3e51b0dd00dff",
        "393ac15e3c44a699030eced5d450f9e84ab5c09e310c766c0dcee8c53c0a2233",
        "0403a88ae20913d11b10a2467b50087721fea7581736da6b9d3992f5357fe54b",
        "b66cb19f2b31f9d427632ea6c4b4a1ff89b74ecaeaee323cd166da41a7af53bd",
        66314400,
    ),
)
BASE_URL = "https://get.helm.sh/"


def sha256_file(path: Path) -> str:
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("Helm fixtures require regular files, never links or devices.")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_helm_binary(path: Path, pin: HelmPin) -> str:
    if pin not in HELM_PINS or not path.is_absolute():
        raise ValueError("Use an absolute binary path and a reviewed Helm fixture pin.")
    if (
        sha256_file(path) != pin.binary_sha256
        or path.stat().st_size != pin.binary_bytes
        or not path.stat().st_mode & 0o111
    ):
        raise ValueError("Helm binary differs from its pinned official Linux amd64 release.")
    return pin.binary_sha256


def download_asset(pin: HelmPin, name: str, destination: Path) -> None:
    if pin not in HELM_PINS or name not in {pin.archive, pin.archive + ".sha256sum"}:
        raise ValueError("Only the reviewed fixed official Helm assets may be acquired.")
    limit = 40 * 1024 * 1024 if name == pin.archive else 1024
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output, urlopen(BASE_URL + name, timeout=30) as response:
        total = 0
        while chunk := response.read(1024 * 1024):
            total += len(chunk)
            if total > limit:
                raise ValueError("Helm asset exceeds its fixed download bound.")
            output.write(chunk)


def prepare_helm_tools(directory: Path) -> tuple[Path, ...]:
    """Retain corrupt or partial downloads; never repair them silently in place."""
    if not directory.is_absolute() or directory.is_symlink():
        raise ValueError("Use an explicit absolute owned Helm fixture directory.")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    binaries = []
    for pin in HELM_PINS:
        target = directory / pin.version.removeprefix("v")
        if target.is_symlink():
            raise ValueError("Helm fixture directories cannot be symbolic links.")
        target.mkdir(mode=0o700, exist_ok=True)
        checksum, archive, binary = (
            target / (pin.archive + ".sha256sum"),
            target / pin.archive,
            target / "helm",
        )
        if not any(path.exists() for path in (checksum, archive, binary)):
            download_asset(pin, checksum.name, checksum)
            download_asset(pin, archive.name, archive)
        if sha256_file(checksum) != pin.checksum_sha256:
            raise ValueError("Official Helm checksum document differs from its reviewed pin.")
        if (
            checksum.read_text().split() != [pin.archive_sha256, pin.archive]
            or sha256_file(archive) != pin.archive_sha256
        ):
            raise ValueError("Helm archive does not match its official pinned checksum.")
        if not binary.exists():
            with tarfile.open(archive) as contents:
                members = [member for member in contents if member.name == "linux-amd64/helm"]
                if (
                    len(members) != 1
                    or not members[0].isfile()
                    or members[0].size != pin.binary_bytes
                ):
                    raise ValueError("Pinned Helm archive has an unexpected binary member.")
                source = contents.extractfile(members[0])
                assert source is not None
                data = source.read(pin.binary_bytes + 1)
            if hashlib.sha256(data).hexdigest() != pin.binary_sha256:
                raise ValueError("Extracted Helm binary differs from the reviewed pin.")
            descriptor = os.open(binary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o500)
            with os.fdopen(descriptor, "wb") as output:
                output.write(data)
        verify_helm_binary(binary, pin)
        provenance = {
            **asdict(pin),
            "archive_url": BASE_URL + pin.archive,
            "checksum_url": BASE_URL + pin.archive + ".sha256sum",
            "host_executed": False,
            "verification": "Pinned official checksums and binary bytes; no signature claim.",
        }
        encoded = json.dumps(provenance, indent=2) + "\n"
        receipt = target / "prepared-provenance.json"
        if receipt.is_symlink() or (receipt.exists() and not stat.S_ISREG(receipt.lstat().st_mode)):
            raise ValueError("Helm provenance requires a regular file, never a link or device.")
        if receipt.exists() and receipt.read_text() != encoded:
            raise ValueError("Earlier Helm provenance differs; use a fresh owned directory.")
        if not receipt.exists():
            descriptor = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as output:
                output.write(encoded)
        binaries.append(binary)
    return tuple(binaries)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps({"binaries": [str(path) for path in prepare_helm_tools(args.directory)]}))


if __name__ == "__main__":
    main()
