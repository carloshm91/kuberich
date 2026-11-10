"""Explicit development-only acquisition of pinned official Vegeta fixture tools."""

import argparse
import asyncio
import hashlib
import io
import json
import os
import platform
import stat
import tarfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.request import urlopen

from kuberich.domain.benchmarks import VEGETA_VERSION, minimal_environment, parse_vegeta_version
from kuberich.domain.processes import ProcessMode, ProcessPurpose, ProcessStatus, capture_command
from kuberich.services.access import AccessPolicy
from kuberich.services.processes import ProcessRunner

VEGETA_COMMIT = "507c4f028fbad80168f3b734dab9530d3aabfefa"
CHECKSUM_SHA256 = "384239c939594c6a4e3b1da4b336728a0d70ed8e77636af92984cdf036a816e7"
BASE_URL = "https://github.com/tsenart/vegeta/releases/download/v12.13.0/"
MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
MAX_BINARY_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class BenchmarkPin:
    system: str
    machine: str
    archive_sha256: str
    binary_sha256: str
    binary_bytes: int

    @property
    def archive(self) -> str:
        return f"vegeta_{VEGETA_VERSION}_{self.system}_{self.machine}.tar.gz"


BENCHMARK_PINS = (
    BenchmarkPin(
        "linux",
        "amd64",
        "e8759ce45c14e18374bdccd3ba6068197bc3a9f9b7e484db3837f701b9d12e61",
        "c54d905541485153542dfcb850f9ab8ef801e7ab1a652d2cfc69cafdd4a5363f",
        10940568,
    ),
    BenchmarkPin(
        "linux",
        "arm64",
        "950381173a5575e25e8e086f36fc03bf65d61a2433329b48e41e1cb5e4133bba",
        "2355df87f054ddbee28bee0b31c741836fa35619f329f664af29fa80910420c4",
        10616984,
    ),
    BenchmarkPin(
        "darwin",
        "amd64",
        "4e912c83ce07db4e1e394e1cbb657f2396dff2f7ed90f03869a184cc17d0f994",
        "dae9dfe4b1b84745764d96248b7285c90200d9f92d6e9095b23b10286208a5c0",
        11222688,
    ),
    BenchmarkPin(
        "darwin",
        "arm64",
        "fc408e242c4f4839e6fe536dbf1130bb02f430134827f6d831bf367a0929a799",
        "15d6cd01fc412e70a11243006de4e5fd68d505a13848ae3312d83d49b64fd087",
        10868626,
    ),
)


def benchmark_pin(*, system: str | None = None, machine: str | None = None) -> BenchmarkPin:
    selected_system = (platform.system() if system is None else system).lower()
    architecture = (platform.machine() if machine is None else machine).lower()
    selected_machine = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(architecture)
    for pin in BENCHMARK_PINS:
        if (pin.system, pin.machine) == (selected_system, selected_machine):
            return pin
    raise ValueError("Vegeta fixtures support only Linux/macOS amd64 and arm64.")


@contextmanager
def physical_directory(path: Path, *, create: bool) -> Iterator[int]:
    """Walk every component without following links; retain the physical anchor."""
    if (
        not path.is_absolute()
        or ".." in path.parts
        or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in str(path))
    ):
        raise ValueError("Use an explicit absolute physical tool directory without traversal.")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in path.parts[1:]:
            try:
                child = os.open(
                    name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                )
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(name, 0o700, dir_fd=descriptor)
                child = os.open(
                    name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                )
            os.close(descriptor)
            descriptor = child
        info = os.fstat(descriptor)
        if info.st_uid != os.geteuid() or info.st_mode & 0o022:
            raise ValueError("Tool directories require owner-controlled permissions.")
        yield descriptor
    finally:
        os.close(descriptor)


def asset_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def read_asset(parent: int, name: str, maximum: int) -> bytes | None:
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW, dir_fd=parent)
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, "rb") as source:
        before = os.fstat(source.fileno())
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or before.st_mode & 0o022
            or before.st_size > maximum
        ):
            raise ValueError("Tool assets require bounded owned regular files, never links.")
        data = source.read(maximum + 1)
        after = os.fstat(source.fileno())
        named = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (
            len(data) > maximum
            or asset_identity(before) != asset_identity(after)
            or asset_identity(after) != asset_identity(named)
        ):
            raise ValueError("Tool asset changed while being verified.")
    return data


def write_asset(parent: int, name: str, data: bytes, *, executable: bool = False) -> None:
    descriptor = os.open(
        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent
    )
    with os.fdopen(descriptor, "wb") as output:
        output.write(data)
        os.fchmod(output.fileno(), 0o500 if executable else 0o600)
        os.fsync(output.fileno())


def download_archive(parent: int, pin: BenchmarkPin) -> bytes:
    if pin not in BENCHMARK_PINS:
        raise ValueError("Only reviewed official Vegeta archives may be acquired.")
    descriptor = os.open(
        pin.archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent
    )
    with (
        os.fdopen(descriptor, "wb") as output,
        urlopen(BASE_URL + pin.archive, timeout=30) as response,
    ):
        total = 0
        while chunk := response.read(64 * 1024):
            total += len(chunk)
            if total > MAX_ARCHIVE_BYTES:
                raise ValueError("Official Vegeta archive exceeds the fixed download bound.")
            output.write(chunk)
    data = read_asset(parent, pin.archive, MAX_ARCHIVE_BYTES)
    assert data is not None
    return data


def binary_matches(parent: int, pin: BenchmarkPin, data: bytes) -> None:
    info = os.stat("vegeta", dir_fd=parent, follow_symlinks=False)
    if (
        len(data) != pin.binary_bytes
        or hashlib.sha256(data).hexdigest() != pin.binary_sha256
        or not info.st_mode & 0o111
        or info.st_mode & 0o022
    ):
        raise ValueError("Vegeta binary differs from the reviewed official platform release.")


def prepare_benchmark_tool(
    directory: Path, *, system: str | None = None, machine: str | None = None
) -> Path:
    """Provision a selected platform without execution or in-place repairs."""
    pin = benchmark_pin(system=system, machine=machine)
    with physical_directory(directory, create=True) as parent:
        archive = read_asset(parent, pin.archive, MAX_ARCHIVE_BYTES)
        if archive is None:
            archive = download_archive(parent, pin)
        if hashlib.sha256(archive).hexdigest() != pin.archive_sha256:
            raise ValueError("Vegeta archive does not match its reviewed official checksum.")
        data = read_asset(parent, "vegeta", MAX_BINARY_BYTES)
        if data is None:
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as contents:
                members = []
                for member in contents:
                    members.append(member)
                    if len(members) > 1:
                        raise ValueError("Official Vegeta archive has an unexpected extra member.")
                if (
                    len(members) != 1
                    or members[0].name != "vegeta"
                    or not members[0].isfile()
                    or members[0].size != pin.binary_bytes
                ):
                    raise ValueError("Official Vegeta archive has an unexpected binary member.")
                source = contents.extractfile(members[0])
                assert source is not None
                data = source.read(MAX_BINARY_BYTES + 1)
            if (
                len(data) != pin.binary_bytes
                or hashlib.sha256(data).hexdigest() != pin.binary_sha256
            ):
                raise ValueError("Extracted Vegeta bytes differ from the reviewed binary pin.")
            write_asset(parent, "vegeta", data, executable=True)
        binary_matches(parent, pin, data)
        provenance = {
            **asdict(pin),
            "producer_version": VEGETA_VERSION,
            "source_commit": VEGETA_COMMIT,
            "license": "MIT",
            "source_url": f"https://github.com/tsenart/vegeta/tree/{VEGETA_COMMIT}",
            "license_url": f"https://github.com/tsenart/vegeta/blob/{VEGETA_COMMIT}/LICENSE",
            "archive_url": BASE_URL + pin.archive,
            "checksum_url": BASE_URL + "vegeta_12.13.0_checksums.txt",
            "checksum_file_sha256": CHECKSUM_SHA256,
            "host_executed": False,
            "verification": "Reviewed official archive and extracted binary SHA-256; signatures not verified.",
        }
        encoded = (json.dumps(provenance, indent=2) + "\n").encode()
        previous = read_asset(parent, "prepared-provenance.json", 16384)
        if previous is not None and previous != encoded:
            raise ValueError("Earlier Vegeta provenance differs; use a fresh owned directory.")
        if previous is None:
            write_asset(parent, "prepared-provenance.json", encoded)
    return directory / "vegeta"


async def probe_version(path: Path) -> str:
    command = capture_command(
        (str(path), "-version"),
        environment=minimal_environment(),
        directory=path.parent,
        mode=ProcessMode.CAPTURE,
        purpose=ProcessPurpose.BENCHMARK,
    )
    async with ProcessRunner(AccessPolicy(False), output_limit=16384) as runner:
        result = await runner.capture(command, timeout=5)
    if result.status is not ProcessStatus.SUCCEEDED:
        raise ValueError("Pinned Vegeta version probe failed or exceeded its bounded output/time.")
    return parse_vegeta_version(result.stdout)


def verify_benchmark_binary(path: Path) -> str:
    """Explicit verifier invocation authenticates current-host bytes before executing."""
    pin = benchmark_pin()
    with physical_directory(path.parent, create=False) as parent:
        if path.name != "vegeta":
            raise ValueError("Use the explicitly provisioned Vegeta fixture path.")
        data = read_asset(parent, path.name, MAX_BINARY_BYTES)
        if data is None:
            raise ValueError("The pinned Vegeta fixture binary is missing.")
        binary_matches(parent, pin, data)
    asyncio.run(probe_version(path))
    return pin.binary_sha256


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--system", choices=("linux", "darwin"))
    parser.add_argument("--machine", choices=("amd64", "arm64"))
    args = parser.parse_args()
    path = prepare_benchmark_tool(args.directory, system=args.system, machine=args.machine)
    print(json.dumps({"vegeta": str(path), "host_executed": False}))


if __name__ == "__main__":
    main()
