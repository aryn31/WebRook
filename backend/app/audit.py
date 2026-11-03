"""Audit log of important account actions. Entries are added to the caller's transaction."""

from typing import Any

from sqlalchemy.orm import Session

from app.deps import Principal
from app.models import AuditLog


def record(
    db: Session,
    principal: Principal,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=principal.user.id,
            actor_type=principal.via,
            api_key_id=principal.api_key.id if principal.api_key else None,
            actor_user_id=principal.actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=principal.ip,
        )
    )
