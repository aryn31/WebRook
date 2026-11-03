"""Who may do what.

Every request is checked against one permission. A dashboard user gets the permissions of their role in the
account they're working in. An API key gets only the scopes it was created with (and never more than its
creator's role allows at creation time).
"""

from typing import Literal

# Permissions an API key can be given. Order is the display order in the dashboard.
API_SCOPES: tuple[str, ...] = (
    "events:write",      # send events
    "events:read",       # list and read events, stats and usage
    "deliveries:read",   # list and read deliveries and their attempts
    "deliveries:replay", # replay deliveries (single, per event, bulk)
    "endpoints:read",    # list and read endpoints (not their secrets)
    "endpoints:write",   # create, change and delete endpoints; view and rotate signing secrets
    "audit:read",        # read the audit log
)

# Dashboard-only permissions. API keys can never have these.
SESSION_ONLY: tuple[str, ...] = (
    "api_keys:manage",   # create and revoke API keys
    "team:manage",       # invite, remove and change the role of members
)

Role = Literal["owner", "admin", "developer", "viewer"]
ROLES: tuple[Role, ...] = ("owner", "admin", "developer", "viewer")
# Roles that can be given to a member. There is exactly one owner: the user whose account it is.
MEMBER_ROLES: tuple[Role, ...] = ("admin", "developer", "viewer")

_READ = {"events:read", "deliveries:read", "endpoints:read", "audit:read"}
_DEVELOP = _READ | {"events:write", "deliveries:replay", "endpoints:write", "api_keys:manage"}

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "viewer": frozenset(_READ),
    "developer": frozenset(_DEVELOP),
    "admin": frozenset(_DEVELOP | {"team:manage"}),
    "owner": frozenset(_DEVELOP | {"team:manage"}),
}

ROLE_RANK = {"viewer": 0, "developer": 1, "admin": 2, "owner": 3}


def role_permissions(role: str) -> frozenset[str]:
    return ROLE_PERMISSIONS.get(role, frozenset())


def key_permissions(scopes: list[str] | None) -> frozenset[str]:
    """A key's permissions. NULL scopes (keys made before scopes existed) means every API scope."""
    return frozenset(API_SCOPES if scopes is None else (s for s in scopes if s in API_SCOPES))
