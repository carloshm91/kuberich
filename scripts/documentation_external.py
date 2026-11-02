"""Bounded advisory HEAD probes for public HTTPS documentation pages only."""

import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit, urlunsplit

Runner = Callable[[list[str], float], subprocess.CompletedProcess[str]]
LOOKUP = (
    "import json,socket,sys; print(json.dumps(sorted({item[4][0] for item in "
    "socket.getaddrinfo(sys.argv[1],443,socket.AF_INET,socket.SOCK_STREAM)})))"
)
RESERVED = (
    "localhost",
    "local",
    "localdomain",
    "internal",
    "invalid",
    "test",
    "example",
    "example.com",
    "example.org",
    "example.net",
    "home.arpa",
    "svc",
    "cluster.local",
)


def run(command: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
        timeout=timeout,
    )


def display_url(value: str) -> str:
    """Reports do not echo URL credentials, queries or fragments."""
    try:
        parsed = urlsplit(value)
        return urlunsplit((parsed.scheme, parsed.hostname or "", parsed.path, "", ""))
    except ValueError:
        return "Invalid URL"


def public_address(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address.version == 4 and address.is_global and not address.is_multicast


def probe_https(
    url: str,
    deadline: float,
    *,
    execute: Runner = run,
    curl: str | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {"url": display_url(url), "status": "excluded"}
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
            or len(url) > 4096
            or any(ord(char) < 32 for char in url)
            or re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?", host) is None
            or "." not in host
            or any(host.lower() == name or host.lower().endswith("." + name) for name in RESERVED)
        ):
            result["reason"] = "Only public HTTPS documentation hosts are probed"
            return result
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            result["reason"] = "Literal and fixture endpoints are not documentation probes"
            return result
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {**result, "status": "not checked", "reason": "Report time budget reached"}
        lookup = execute([sys.executable, "-I", "-S", "-c", LOOKUP, host], min(2.0, remaining))
        addresses = json.loads(lookup.stdout) if lookup.returncode == 0 else None
        if not isinstance(addresses, list) or not addresses:
            return {**result, "status": "unavailable", "reason": "DNS lookup unavailable"}
        if any(not public_address(address) for address in addresses):
            result["reason"] = "Private, reserved or mixed DNS destinations are excluded"
            return result
        executable = curl or shutil.which("curl")
        remaining = deadline - time.monotonic()
        if executable is None or remaining <= 0:
            return {
                **result,
                "status": "not checked",
                "reason": "curl unavailable or report time budget reached",
            }
        maximum = min(3.0, remaining)
        # Pin the checked public address. Do not follow redirects or read ~/.curlrc,
        # proxy credentials, cookies or response bodies.
        command = [
            executable,
            "--disable",
            "--silent",
            "--show-error",
            "--head",
            "--globoff",
            "--proto",
            "=https",
            "--noproxy",
            "*",
            "--resolve",
            f"{host}:443:{addresses[0]}",
            "--max-time",
            str(maximum),
            "--connect-timeout",
            str(min(2.0, maximum)),
            "--output",
            os.devnull,
            "--write-out",
            "%{http_code}",
            "--",
            url,
        ]
        response = execute(command, maximum + 1)
        status = response.stdout.strip()
        if response.returncode or re.fullmatch(r"[1-5][0-9]{2}", status) is None:
            return {**result, "status": "unavailable", "reason": "HTTPS HEAD unavailable"}
        code = int(status)
        return {
            **result,
            "status": "reachable" if 200 <= code < 300 else "review",
            "http_status": code,
            "reason": "HEAD only; redirects and fragments are not followed",
        }
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {**result, "status": "unavailable", "reason": "Probe failed or reached its deadline"}


def probe_links(urls: Iterable[str], *, seconds: float = 20) -> list[dict[str, object]]:
    deadline = time.monotonic() + seconds
    results: list[dict[str, object]] = []
    for index, url in enumerate(sorted(set(urls))):
        if index >= 64:
            results.append(
                {
                    "url": display_url(url),
                    "status": "not checked",
                    "reason": "Report URL limit reached",
                }
            )
        else:
            results.append(probe_https(url, deadline))
    return results
