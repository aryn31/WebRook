"""Destination URL checks (SSRF protection).

Milestone 1 scope:
- At registration: only http/https, a hostname, no embedded credentials, and no literal private IPs.
- At delivery: resolve the hostname and refuse if any address is private, loopback, link-local or reserved.

Still to do for the public beta (Milestone 3): pin the connection to the checked IP so DNS can't change between
the check and the request (DNS rebinding), and add network-level egress rules.
"""

import ipaddress
import socket
from urllib.parse import urlsplit

from app.config import get_settings


class UnsafeDestination(Exception):
    pass


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


def check_destination(url: str) -> None:
    """Resolve the URL's host and raise UnsafeDestination if it points somewhere internal."""
    if not get_settings().block_private_destinations:
        return
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeDestination(f"Could not resolve host '{host}'.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if _is_blocked_ip(ip):
            raise UnsafeDestination("Destination resolves to a private or reserved address, which is not allowed.")
