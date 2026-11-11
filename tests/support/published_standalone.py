"""Reviewed original 0.4 standalone inputs for owned replacement trials."""

import base64
import json
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from packaging.version import Version

from scripts.standalone import archive_inventory, asset_name
from scripts.supply_chain import digest

VERSION = "0.4.0"
SOURCE = "78ff8f720d4ffde34ea91193593823685433515f"
BASE_URL = "https://github.com/carloshm91/kuberich/releases/download/v0.4.0/"
CHECKSUM_NAME = "DOWNLOAD-SHA256SUMS"
CHECKSUM_SHA256 = "f96b56fc8c369ce3c2a2f18c8cf1aded66a5d3e42aab17460b52d368f8bf099b"
PINS = {
    "linux-x86_64": {
        "archive": "0b051726d07273fb9a347dac680e9095075d15cfc41611a124f5afc098011f01",
        "provenance": "fc416bdb5180976b71228821277b6dcb04fb91d7d22ab23a54764f4ba61c8f7e",
    },
    "linux-arm64": {
        "archive": "d8a8dc9dca1e0497690699442c9b188fee3c11bee24cc59e3c0a7106e485e3ee",
        "provenance": "ae8450c01440cdce92b3347cd039119db473b2ec8fd1cfb4def70d39352c8d94",
    },
    "macos-x86_64": {
        "archive": "9cc694af40efd59e0d87d7087c21bcafe198025a558fe81781d4cc61e2a232c5",
        "provenance": "8d9946ba6ee6b9fdd007183ffa117d1d27c054755407f7b4bbe3f5437c3ec591",
    },
    "macos-arm64": {
        "archive": "847125d9af8e44c9d82f4d8747a676a47c99cb8efe22c72fa463a5f6891875a6",
        "provenance": "2ad7db885d4575063f9c8be882fdc838a5c6253035cf0e529e002af8e8f71a9c",
    },
}


def download_original(directory: Path, name: str, expected: str, limit: int) -> Path:
    path = directory / name
    with urlopen(BASE_URL + name, timeout=30) as response, path.open("xb") as output:
        output.write(response.read(limit + 1))
    if path.stat().st_size > limit or digest(path) != expected:
        raise ValueError("Published native bytes differ from the reviewed immutable pin")
    return path


def predecessor(directory: Path, candidate: str, target: str) -> tuple[Path, dict[str, Any]]:
    """Retain original checksum/provenance/archive bytes before executing anything."""
    from tests.support.source_candidate import published_baseline

    baseline = published_baseline(candidate)
    if (
        baseline["version"] != VERSION
        or baseline["source_commit"] != SOURCE
        or Version(candidate) <= Version(VERSION)
        or target not in PINS
    ):
        raise ValueError("Selected native predecessor needs its own reviewed immutable pins")
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    checksums = download_original(directory, CHECKSUM_NAME, CHECKSUM_SHA256, 65536)
    pin = PINS[target]
    name = asset_name(VERSION, target)
    provenance_name = name.removesuffix(".tar.gz") + ".provenance.json"
    lines = checksums.read_text().splitlines()
    for filename, expected in ((name, pin["archive"]), (provenance_name, pin["provenance"])):
        if lines.count(expected + "  " + filename) != 1:
            raise ValueError("Published checksum record differs from the reviewed native pin")
    provenance = download_original(directory, provenance_name, pin["provenance"], 1024 * 1024)
    sidecar = json.loads(provenance.read_bytes())
    manifest = json.loads(
        base64.b64decode(sidecar["records"]["candidate/build-manifest.json"], validate=True)
    )
    if (
        sidecar.get("schema_version") != 1
        or sidecar.get("target") != target
        or manifest.get("schema_version") != 1
        or manifest.get("version") != VERSION
        or manifest.get("source_commit") != SOURCE
        or manifest.get("source_clean") is not True
        or manifest.get("diagnostic_only") is not False
        or manifest.get("target") != target
        or manifest["archive"]["name"] != name
        or manifest["archive"]["sha256"] != pin["archive"]
    ):
        raise ValueError("Published native provenance differs from its original release identity")
    archive = download_original(directory, name, pin["archive"], 64 * 1024 * 1024)
    if archive_inventory(archive, target) != manifest["archive"]["members"]:
        raise ValueError("Published native archive differs from its original member inventory")
    return archive, manifest
