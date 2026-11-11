"""Conservative immutable HTTP load settings and literal Vegeta commands."""

import base64
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlsplit

from kuberich.errors import AppError
from kuberich.security.controls import escape_controls

VEGETA_VERSION = "12.13.0"
VEGETA_PARSER_ID = "vegeta-12.13.0-json-v1"
METHODS = frozenset({"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"})
_HEADER = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
_FORBIDDEN = frozenset(
    {
        "host",
        "connection",
        "content-length",
        "transfer-encoding",
        "te",
        "trailer",
        "upgrade",
        "proxy-authorization",
        "proxy-authenticate",
        "keep-alive",
        "expect",
    }
)


@dataclass(frozen=True, slots=True)
class LoadOptions:
    rate: int = 1
    concurrency: int = 1
    duration_seconds: int = 5
    timeout_seconds: int = 2

    def __post_init__(self) -> None:
        for value, maximum in (
            (self.rate, 50),
            (self.concurrency, 8),
            (self.duration_seconds, 30),
            (self.timeout_seconds, 5),
        ):
            if type(value) is not int or not 1 <= value <= maximum:
                raise AppError("Benchmark load exceeds the supported positive integer limits.")

    @property
    def nominal_requests(self) -> int:
        return self.rate * self.duration_seconds


@dataclass(frozen=True, slots=True)
class RequestOptions:
    method: str = "GET"
    target: str = field(default="/", repr=False)
    headers: tuple[tuple[str, str], ...] = field(default=(), repr=False)
    body: bytes = field(default=b"", repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.method, str) or self.method not in METHODS:
            raise AppError("Choose a supported uppercase HTTP method.")
        if (
            not isinstance(self.target, str)
            or not self.target.startswith("/")
            or self.target.startswith("//")
            or "\\" in self.target
            or len(self.target.encode("utf-8", errors="surrogatepass")) > 2048
            or escape_controls(self.target) != self.target
        ):
            raise AppError("Benchmark target must be a bounded relative HTTP request target.")
        parsed = urlsplit(self.target)
        decoded = unquote(self.target)
        if (
            parsed.scheme
            or parsed.netloc
            or parsed.fragment
            or "#" in self.target
            or escape_controls(decoded) != decoded
            or "\\" in decoded
        ):
            raise AppError("Benchmark target cannot contain an authority, fragment or controls.")
        if not isinstance(self.headers, tuple) or len(self.headers) > 16:
            raise AppError("Benchmark headers require at most 16 immutable entries.")
        seen: set[str] = set()
        size = 0
        for item in self.headers:
            if (
                not isinstance(item, tuple)
                or len(item) != 2
                or not all(isinstance(part, str) for part in item)
            ):
                raise AppError("Benchmark headers require name/value text pairs.")
            name, value = item
            lower = name.lower()
            if (
                _HEADER.fullmatch(name) is None
                or lower in seen
                or lower in _FORBIDDEN
                or escape_controls(value) != value
            ):
                raise AppError("Benchmark header is duplicated, unsafe or overrides HTTP routing.")
            seen.add(lower)
            size += len(name.encode()) + len(value.encode("utf-8", errors="surrogatepass"))
        if size > 8192 or not isinstance(self.body, bytes) or len(self.body) > 16384:
            raise AppError("Benchmark headers exceed 8 KiB or request body exceeds 16 KiB.")


@dataclass(frozen=True, slots=True)
class RequestReview:
    method: str
    route: str
    query_present: bool
    header_names: tuple[str, ...]
    body_bytes: int
    auth_present: bool


def review_request(request: RequestOptions) -> RequestReview:
    names = tuple(name for name, _ in request.headers)
    return RequestReview(
        request.method,
        request.target.partition("?")[0],
        "?" in request.target,
        names,
        len(request.body),
        any(name.lower() in {"authorization", "cookie"} for name in names),
    )


def targets_json(request: RequestOptions, port: int) -> bytes:
    if type(port) is not int or not 1 <= port <= 65535:
        raise AppError("Benchmark requires the owned forward's bound TCP port.")
    data = (
        json.dumps(
            {
                "method": request.method,
                "url": f"http://127.0.0.1:{port}{request.target}",
                "header": {name: [value] for name, value in request.headers},
                "body": base64.b64encode(request.body).decode("ascii"),
            },
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    return data


def _path(value: Path) -> str:
    if (
        not isinstance(value, Path)
        or not value.is_absolute()
        or ".." in value.parts
        or len(str(value)) > 4096
        or escape_controls(str(value)) != str(value)
    ):
        raise AppError("Benchmark program and private files require absolute physical paths.")
    return str(value)


def attack_argv(executable: Path, targets: Path, load: LoadOptions) -> tuple[str, ...]:
    return (
        _path(executable),
        "-cpus=1",
        "attack",
        "-format=json",
        f"-targets={_path(targets)}",
        f"-rate={load.rate}/1s",
        f"-duration={load.duration_seconds}s",
        f"-timeout={load.timeout_seconds}s",
        f"-workers={load.concurrency}",
        f"-max-workers={load.concurrency}",
        f"-connections={load.concurrency}",
        f"-max-connections={load.concurrency}",
        "-redirects=-1",
        "-max-body=0",
        "-keepalive=false",
        "-http2=false",
        "-h2c=false",
        "-prometheus-addr=",
    )


def report_argv(executable: Path, result: Path) -> tuple[str, ...]:
    return (_path(executable), "-cpus=1", "report", "-type=json", _path(result))


def minimal_environment() -> dict[str, str]:
    """An absolute executable needs neither the user's PATH nor inherited secrets."""
    return {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}


def parse_vegeta_version(data: bytes) -> str:
    if not data or len(data) > 16384:
        raise AppError("Vegeta version output is empty or exceeds 16 KiB.")
    try:
        text = data.decode("utf-8")
    except UnicodeError:
        raise AppError("Vegeta version output is not UTF-8.") from None
    lines = text.splitlines()
    labels = ("Version", "Commit", "Runtime", "Date")
    if (
        len(lines) != 4
        or escape_controls(text, allow_newlines=True) != text
        or any(
            not line.startswith(label + ": ") or not line[len(label) + 2 :]
            for line, label in zip(lines, labels, strict=False)
        )
        or lines[0].removeprefix("Version: ").removeprefix("v") != VEGETA_VERSION
    ):
        raise AppError("Unsupported Vegeta version; configure the pinned v12.13.0 executable.")
    return VEGETA_VERSION
