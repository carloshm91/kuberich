"""Captured kubeconfig/environment proxy selection without ambient identity."""

import ssl
from collections.abc import Mapping
from ipaddress import ip_address, ip_network
from urllib.parse import unquote, urlsplit

from kuberich.errors import AppError


def tls_failure(error: BaseException) -> bool:
    """Some proxy connectors wrap TLS failures as generic connection errors."""
    visited: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in visited:
        if isinstance(current, ssl.SSLError):
            return True
        visited.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def proxy_url(value: object) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 4096:
        raise AppError("Proxy must be a bounded HTTP(S) or SOCKS5 URL.")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise AppError("Proxy URL has an invalid host or port.") from None
    if (
        parsed.scheme not in {"http", "https", "socks5"}
        or not parsed.hostname
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or port == 0
        or any(ord(character) <= 32 or ord(character) == 127 for character in unquote(value))
    ):
        raise AppError("Proxy must be an HTTP(S) or SOCKS5 URL without path/query/controls.")
    return value.rstrip("/")


def _bypass(host: str, port: int, value: str) -> bool:
    # client-go never proxies localhost/loopback through environment settings.
    try:
        address = ip_address(host)
    except ValueError:
        address = None
    if host.lower() == "localhost" or (address is not None and address.is_loopback):
        return True
    for raw in value.split(","):
        entry = raw.strip().lower()
        if entry == "*":
            return True
        if not entry:
            continue
        if "/" in entry:
            try:
                if address is not None and address in ip_network(entry, strict=False):
                    return True
            except ValueError:
                pass
            continue
        try:
            if address is not None and address == ip_address(entry):
                return True
        except ValueError:
            pass
        try:
            parsed = urlsplit("//" + entry)
            entry_port = parsed.port
        except ValueError:
            continue
        if entry_port is not None and entry_port != port:
            continue
        name = (parsed.hostname or "").removeprefix("*")
        if not name:
            continue
        if name.startswith("."):
            if host.lower().endswith(name):
                return True
        elif host.lower() == name or host.lower().endswith("." + name):
            return True
    return False


def effective_proxy(server: str, declared: object, environment: Mapping[str, str]) -> str | None:
    if declared is not None and declared != "":
        return proxy_url(declared)
    endpoint = urlsplit(server)
    host = endpoint.hostname or ""
    port = endpoint.port or (443 if endpoint.scheme == "https" else 80)
    if _bypass(host, port, environment.get("NO_PROXY") or environment.get("no_proxy", "")):
        return None
    name = "HTTPS_PROXY" if endpoint.scheme == "https" else "HTTP_PROXY"
    value = environment.get(name) or environment.get(name.lower())
    if not value:
        return None
    if name == "HTTP_PROXY" and environment.get("REQUEST_METHOD"):
        raise AppError("HTTP proxy environment is unsafe in CGI; use an explicit proxy-url.")
    return proxy_url(value if "://" in value else "http://" + value)
