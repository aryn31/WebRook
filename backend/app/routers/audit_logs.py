from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.deps import DB, AuditRead
from app.models import AuditLog, User
from app.pagination import Cursor, Limit, paginate
from app.schemas import Actor, AuditLogOut, Page

router = APIRouter(prefix="/v1/audit-logs", tags=["audit log"])


@router.get("", response_model=Page[AuditLogOut])
def list_audit_logs(
    principal: AuditRead,
    db: DB,
    limit: Limit = 25,
    cursor: Cursor = None,
    action: Annotated[str | None, Query(max_length=64)] = None,
    resource_id: Annotated[str | None, Query(max_length=32)] = None,
) -> dict:
    stmt = select(AuditLog).where(AuditLog.user_id == principal.user.id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if resource_id:
        stmt = stmt.where(AuditLog.resource_id == resource_id)
    rows, next_cursor = paginate(db, stmt, AuditLog.id, limit, cursor)
    actor_ids = {r.actor_user_id for r in rows if r.actor_user_id}
    emails = dict(db.execute(select(User.id, User.email).where(User.id.in_(actor_ids))).all()) if actor_ids else {}
    data = [
        AuditLogOut(
            id=r.id,
            action=r.action,
            actor=Actor(type=r.actor_type, api_key_id=r.api_key_id, user_id=r.actor_user_id,
                        email=emails.get(r.actor_user_id)),
            resource_type=r.resource_type,
            resource_id=r.resource_id,
            details=r.details,
            ip_address=r.ip_address,
            created_at=r.created_at,
        )
        for r in rows
    ]
    return {"data": data, "next_cursor": next_cursor}
