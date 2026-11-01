"""The caller's IP address, for audit logs and per-IP rate limits.

Behind a load balancer, the connection comes from the proxy, and the real client is in X-Forwarded-For. Each proxy
appends the address it received the request from, so with N trusted proxies the client is the Nth entry from the
right. Entries further left were supplied by the client and can be forged, so they are never used.
"""

from fastapi import Request

from app.config import get_settings


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    hops = get_settings().trusted_proxy_count
    if hops <= 0:
        return peer
    forwarded = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if not forwarded:
        return peer
    # Fewer entries than proxies means the request skipped a proxy; the leftmost is the best we have.
    return forwarded[-hops] if len(forwarded) >= hops else forwarded[0]
