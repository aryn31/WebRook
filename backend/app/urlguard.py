"""Destination URL checks (SSRF protection).

- At registration: only http/https, a hostname, no embedded credentials, and no literal private IPs.
- At delivery: the HTTP client connects through ``GuardedBackend``. It resolves the host itself, refuses if any
  address is private, loopback, link-local or reserved, and then connects to one of the addresses it just checked.
  Checking and connecting use the same lookup, so DNS can't change in between (DNS rebinding). TLS still uses the
  hostname for SNI and certificate checks.

Network-level egress rules (a firewall in front of the workers) are a deployment concern; see docs/operations.md.
"""

import ipaddress
import socket
from collections.abc import Iterable
from urllib.parse import urlsplit

import httpcore
import httpx

from app.config import get_settings


class UnsafeDestination(Exception):
    """The destination is internal. Retrying won't help."""


class UnresolvableHost(Exception):
    """DNS lookup failed. Often temporary, so deliveries retry."""


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not ip.is_global or ip.is_multicast


def validate_url_format(url: str) -> str:
    """Raise ValueError with a user-facing message if ``url`` can never be a valid destination."""
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ValueError("URL must start with http:// or https://.")
    if not parts.hostname:
        raise ValueError("URL must include a host name.")
    if parts.username or parts.password:
        raise ValueError("URL must not contain a username or password.")
    try:
        _ = parts.port
    except ValueError as exc:
        raise ValueError("URL has an invalid port.") from exc
    if get_settings().block_private_destinations:
        host = parts.hostname
        if host == "localhost" or host.endswith(".localhost") or host.endswith(".internal"):
            raise ValueError("URL must point to a public host.")
        try:
            literal_ip = ipaddress.ip_address(host)
        except ValueError:
            literal_ip = None  # a hostname; checked again after DNS resolution at delivery time
        if literal_ip is not None and _is_blocked_ip(literal_ip):
            raise ValueError("URL must point to a public IP address.")
    return url


def resolve_public(host: str, port: int) -> list[str]:
    """Return the host's addresses, or raise if the lookup fails or any address is internal.

    One bad address rejects the host: otherwise a hostile DNS server could mix a public and a private address and
    hope the connection picks the private one.
    """
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        raise UnresolvableHost(f"Could not resolve host '{host}'.") from exc
    ips: list[str] = []
    for info in infos:
        addr = str(info[4][0]).split("%")[0]
        if _is_blocked_ip(ipaddress.ip_address(addr)):
            raise UnsafeDestination("Destination resolves to a private or reserved address, which is not allowed.")
        if addr not in ips:
            ips.append(addr)
    if not ips:
        raise UnresolvableHost(f"Could not resolve host '{host}'.")
    return ips


def check_destination(url: str) -> None:
    """Raise UnsafeDestination (or UnresolvableHost) if the URL's host points somewhere internal."""
    if not get_settings().block_private_destinations:
        return
    parts = urlsplit(url)
    resolve_public(parts.hostname or "", parts.port or (443 if parts.scheme == "https" else 80))


class GuardedBackend(httpcore.NetworkBackend):
    """Network backend that only opens TCP connections to addresses that passed ``resolve_public``."""

    def __init__(self) -> None:
        self._inner = httpcore.SyncBackend()

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable | None = None,
    ) -> httpcore.NetworkStream:
        if not get_settings().block_private_destinations:
            return self._inner.connect_tcp(host, port, timeout, local_address, socket_options)
        last_error: Exception | None = None
        for ip in resolve_public(host, port):
            try:
                return self._inner.connect_tcp(ip, port, timeout, local_address, socket_options)
            except httpcore.ConnectError as exc:  # try the next address, like a normal client would
                last_error = exc
        assert last_error is not None
        raise last_error

    def connect_unix_socket(self, *args, **kwargs) -> httpcore.NetworkStream:
        raise UnsafeDestination("Unix sockets are not allowed.")

    def sleep(self, seconds: float) -> None:
        self._inner.sleep(seconds)


class GuardedTransport(httpx.HTTPTransport):
    """httpx transport using ``GuardedBackend``. No proxies, no environment settings."""

    def __init__(self) -> None:
        super().__init__(trust_env=False)
        # httpx doesn't take a network backend directly, so swap in a pool built with ours.
        self._pool = httpcore.ConnectionPool(
            ssl_context=httpx.create_ssl_context(trust_env=False),
            max_connections=10,
            max_keepalive_connections=0,
            network_backend=GuardedBackend(),
        )
