"""Finite Ubuntu runner source formats; retain the image's archive authentication.

MIT SIPB documents both HTTPS archive families at https://mirrors.mit.edu/.
APT authenticates their actual InRelease metadata with the existing Ubuntu keys:
https://manpages.ubuntu.com/manpages/noble/man8/apt-secure.8.html
"""

import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

MIRRORS = {
    "amd64": "https://mirrors.mit.edu/ubuntu",
    "arm64": "https://mirrors.mit.edu/ubuntu-ports",
}
MIRROR_URI = "mirror+file:/etc/apt/apt-mirrors.txt"
KEYRING = "/usr/share/keyrings/ubuntu-archive-keyring.gpg"
MAX_SOURCE_BYTES = 65536
MAX_SOURCE_FILES = 64
COMPONENTS = frozenset({"main", "restricted", "universe", "multiverse"})
SUITE = re.compile(r"(?:jammy|noble)(?:-(?:updates|security|backports))?\Z")
ENTRY = re.compile(r"^(\s*deb(?:-src)?\s+(?:\[[^\]\r\n]*\]\s+)?)(\S+)(.*)$")
HINT = re.compile(r"(?:[a-z.-]*ubuntu\.com|mirrors\.mit\.edu|mirror\+file:)")


@dataclass(frozen=True)
class SourceChange:
    path: Path
    original: bytes = field(repr=False)
    replacement: bytes = field(repr=False)


def mirror_for_architecture(architecture: str) -> str:
    if architecture not in MIRRORS:
        raise ValueError("CI APT supports only the declared amd64 and arm64 Ubuntu runners.")
    mirror = MIRRORS[architecture]
    family = "ubuntu" if architecture == "amd64" else "ubuntu-ports"
    if mirror != "https://mirrors.mit.edu/" + family:
        raise ValueError("CI APT requires the bounded reviewed HTTPS mirror selection.")
    return mirror


def source_bytes(path: Path) -> bytes:
    mode = path.lstat()
    if not stat.S_ISREG(mode.st_mode) or mode.st_size > MAX_SOURCE_BYTES:
        raise ValueError("CI APT refuses a symlink or nonregular source file, or oversized data.")
    data = path.read_bytes()
    if len(data) > MAX_SOURCE_BYTES:
        raise ValueError("CI APT source file exceeded its byte limit.")
    return data


def _uri(value: str, architecture: str) -> tuple[str, bool, bool]:
    mirror = mirror_for_architecture(architecture)
    if value == MIRROR_URI:
        return value, True, True
    origins = (
        (
            "archive.ubuntu.com/ubuntu",
            "security.ubuntu.com/ubuntu",
            "azure.archive.ubuntu.com/ubuntu",
        )
        if architecture == "amd64"
        else ("ports.ubuntu.com/ubuntu-ports",)
    )
    allowed = {scheme + origin for origin in origins for scheme in ("http://", "https://")}
    if value.rstrip("/") in {*allowed, mirror}:
        return mirror + ("/" if value.endswith("/") else ""), True, False
    if HINT.search(value):
        raise ValueError("CI APT refuses an unrecognized Ubuntu source URI.")
    return value, False, False


def _scope(suites: str, components: str, signed_by: str | None) -> None:
    if (
        not suites.split()
        or any(SUITE.fullmatch(value) is None for value in suites.split())
        or not components.split()
        or not set(components.split()) <= COMPONENTS
        or (signed_by is not None and signed_by != KEYRING)
    ):
        raise ValueError("CI APT refuses an unknown Ubuntu suite, component or Signed-By format.")


def _list(text: str, architecture: str) -> tuple[str, int, bool]:
    lines, count, indirect = [], 0, False
    for line in text.splitlines(keepends=True):
        active = line.split("#", 1)[0].strip()
        if not active:
            lines.append(line)
            continue
        match = ENTRY.match(line.rstrip("\r\n"))
        if match is None:
            if HINT.search(active):
                raise ValueError("CI APT refuses an unknown Ubuntu one-line source format.")
            lines.append(line)
            continue
        prefix, uri, rest = match.groups()
        replacement, ubuntu, mirror_list = _uri(uri, architecture)
        if ubuntu:
            parts = rest.split("#", 1)[0].split()
            if len(parts) < 2:
                raise ValueError("CI APT requires explicit Ubuntu suites and components.")
            options: dict[str, str] = {}
            if "[" in prefix:
                for option in prefix.split("[", 1)[1].split("]", 1)[0].split():
                    key, separator, value = option.partition("=")
                    if not separator or key in options or key not in {"arch", "signed-by"}:
                        raise ValueError("CI APT refuses unknown Ubuntu source options.")
                    options[key] = value
            _scope(parts[0], " ".join(parts[1:]), options.get("signed-by"))
            count += 1
            indirect = indirect or mirror_list
            start, end = match.span(2)
            line = line[:start] + replacement + line[end:]
        lines.append(line)
    return "".join(lines), count, indirect


def _stanza(lines: list[str], architecture: str) -> tuple[str, int, bool]:
    active = [line for line in lines if line.strip() and not line.lstrip().startswith("#")]
    text = "".join(lines)
    if not any(HINT.search(line) for line in active):
        return text, 0, False
    fields: dict[str, tuple[int, str]] = {}
    for index, line in enumerate(lines):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition(":")
        if not separator or key != key.strip() or key.lower() in fields:
            raise ValueError("CI APT refuses an unknown Ubuntu deb822 source format.")
        fields[key.lower()] = index, value.strip()
    if fields.get("enabled", (0, "yes"))[1] == "no":
        return text, 0, False
    permitted = {"types", "uris", "suites", "components", "signed-by", "architectures", "enabled"}
    if (
        not fields.keys() <= permitted
        or not {"types", "uris", "suites", "components"} <= fields.keys()
        or not fields["types"][1].split()
        or not set(fields["types"][1].split()) <= {"deb", "deb-src"}
        or fields.get("enabled", (0, "yes"))[1] != "yes"
    ):
        raise ValueError("CI APT refuses unknown Ubuntu deb822 fields or trust options.")
    _scope(fields["suites"][1], fields["components"][1], fields.get("signed-by", (0, None))[1])
    index, value = fields["uris"]
    values = value.split()
    mapped = [_uri(uri, architecture) for uri in values]
    if not mapped or not all(item[1] for item in mapped):
        raise ValueError("CI APT refuses mixed or unknown Ubuntu source URIs.")
    line = lines[index]
    for uri, item in zip(values, mapped, strict=True):
        line = line.replace(uri, item[0], 1)
    lines[index] = line
    return "".join(lines), 1, any(item[2] for item in mapped)


def rewrite(data: bytes, suffix: str, architecture: str) -> tuple[bytes, int, bool]:
    text = data.decode("utf-8")
    if len(data) > MAX_SOURCE_BYTES or "\x00" in text:
        raise ValueError("CI APT source bytes are invalid or oversized.")
    if suffix == ".list":
        result, count, indirect = _list(text, architecture)
    elif suffix == ".sources":
        output: list[str] = []
        block: list[str] = []
        count, indirect = 0, False
        for line in [*text.splitlines(keepends=True), ""]:
            if line.strip():
                block.append(line)
                continue
            changed, matched, mirror = _stanza(block, architecture)
            output.extend((changed, line))
            count += matched
            indirect = indirect or mirror
            block = []
        result = "".join(output)
    else:
        raise ValueError("CI APT supports only explicit .list and .sources formats.")
    return result.encode("utf-8"), count, indirect


def source_changes(
    architecture: str, source_list: Path, source_directory: Path, mirror_file: Path
) -> tuple[SourceChange, ...]:
    mirror = mirror_for_architecture(architecture)
    paths = [source_list] if source_list.exists() or source_list.is_symlink() else []
    if source_directory.exists() or source_directory.is_symlink():
        if source_directory.is_symlink() or not source_directory.is_dir():
            raise ValueError("CI APT refuses an unsafe source directory.")
        entries = sorted(source_directory.iterdir())
        if len(entries) > MAX_SOURCE_FILES:
            raise ValueError("CI APT source file inventory exceeded its limit.")
        paths.extend(path for path in entries if path.suffix in {".list", ".sources"})
    changes, count, indirect = [], 0, False
    for path in paths:
        original = source_bytes(path)
        replacement, matched, referenced = rewrite(original, path.suffix, architecture)
        count += matched
        indirect = indirect or referenced
        if replacement != original:
            changes.append(SourceChange(path, original, replacement))
    if not count:
        raise ValueError("CI APT found no recognized active Ubuntu sources.")
    if indirect:
        original = source_bytes(mirror_file)
        mirrors = []
        for line in original.decode("utf-8").splitlines():
            uri = line.split("#", 1)[0].strip()
            if uri and (not _uri(uri, architecture)[1] or uri == MIRROR_URI):
                raise ValueError("CI APT refuses an unknown Ubuntu mirror-list format.")
            if uri:
                mirrors.append(uri)
        if not mirrors:
            raise ValueError("CI APT refuses an empty Ubuntu mirror list.")
        replacement = (mirror + "\n").encode("ascii")
        if replacement != original:
            changes.append(SourceChange(mirror_file, original, replacement))
    if len(changes) > 2:
        raise ValueError("CI APT refuses more than two Ubuntu source file changes.")
    return tuple(changes)
