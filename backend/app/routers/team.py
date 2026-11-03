"""Team accounts: members, roles and invitations.

An account is identified by its owner's user ID. The owner can invite others by link; each member has a role
(see app/permissions.py). Members switch into the account from the dashboard and then see its data.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Response
from sqlalchemy import func, select, update

from app import audit
from app.deps import DB, Principal, SessionPrincipal, TeamManage, check, member_role
from app.errors import ApiError, not_found
from app.models import AccountInvite, AccountMember, User, UserSession
from app.permissions import ROLE_RANK
from app.schemas import (
    InviteCreated, InviteIn, InviteOut, InvitePreview, ListOf, MemberOut, MemberPatch, UserEnvelope, UserOut,
)
from app.security import new_session_token, sha256_hex

router = APIRouter(prefix="/v1/team", tags=["team"])
invites_router = APIRouter(prefix="/v1/invites", tags=["team"])

INVITE_TTL = timedelta(days=7)
MAX_MEMBERS = 50


@router.get("/members", response_model=ListOf[MemberOut])
def list_members(principal: SessionPrincipal, db: DB) -> dict:
    """Everyone with access to the current account. Any member can see this."""
    owner = principal.user
    rows = db.scalars(
        select(AccountMember).where(AccountMember.account_id == owner.id).order_by(AccountMember.created_at)
    ).all()
    data = [MemberOut(user_id=owner.id, email=owner.email, role="owner", joined_at=owner.created_at)]
    data += [MemberOut(user_id=m.user_id, email=m.user.email, role=m.role, joined_at=m.created_at) for m in rows]
    return {"data": data}


def _member(db: DB, account_id: str, user_id: str) -> AccountMember:
    m = db.scalar(select(AccountMember).where(AccountMember.account_id == account_id,
                                              AccountMember.user_id == user_id))
    if m is None:
        raise not_found("Member")
    return m


def _check_can_manage(principal: Principal, target_role: str) -> None:
    """Admins can't change or remove other admins; only the owner can."""
    if principal.role != "owner" and ROLE_RANK[target_role] >= ROLE_RANK[principal.role]:
        raise ApiError(403, "Only the account owner can change or remove admins.", code="forbidden")


@router.patch("/members/{user_id}", response_model=MemberOut)
def update_member(user_id: str, body: MemberPatch, principal: TeamManage, db: DB) -> MemberOut:
    if user_id == principal.user.id:
        raise ApiError(409, "The owner's role can't be changed.", code="owner_role_fixed")
    m = _member(db, principal.user.id, user_id)
    _check_can_manage(principal, m.role)
    _check_can_manage(principal, body.role)
    if body.role != m.role:
        audit.record(db, principal, "team.member_role_changed", "user", user_id,
                     {"email": m.user.email, "from": m.role, "to": body.role})
        m.role = body.role
        db.commit()
    return MemberOut(user_id=m.user_id, email=m.user.email, role=m.role, joined_at=m.created_at)


@router.delete("/members/{user_id}", status_code=204)
def remove_member(user_id: str, principal: SessionPrincipal, db: DB) -> Response:
    """Remove a member. Members can also remove themselves (leave the team)."""
    if user_id == principal.user.id:
        raise ApiError(409, "The owner can't be removed from their own account.", code="owner_role_fixed")
    m = _member(db, principal.user.id, user_id)
    leaving = user_id == principal.actor_id
    if not leaving:
        check(principal, "team:manage")
        _check_can_manage(principal, m.role)
    email = m.user.email
    db.delete(m)
    # Their sessions fall back to their own account on the next request (see deps._from_session); reset now too.
    db.execute(update(UserSession).where(UserSession.user_id == user_id, UserSession.account_id == principal.user.id)
               .values(account_id=None))
    audit.record(db, principal, "team.member_left" if leaving else "team.member_removed", "user", user_id,
                 {"email": email})
    db.commit()
    return Response(status_code=204)


@router.get("/invites", response_model=ListOf[InviteOut])
def list_invites(principal: TeamManage, db: DB) -> dict:
    """Open invitations (not accepted, revoked or expired)."""
    rows = db.scalars(
        select(AccountInvite).where(
            AccountInvite.account_id == principal.user.id,
            AccountInvite.accepted_at.is_(None),
            AccountInvite.revoked_at.is_(None),
            AccountInvite.expires_at > datetime.now(UTC),
        ).order_by(AccountInvite.id.desc())
    ).all()
    return {"data": rows}


@router.post("/invites", status_code=201, response_model=InviteCreated)
def create_invite(body: InviteIn, principal: TeamManage, db: DB) -> dict:
    _check_can_manage(principal, body.role)
    email = body.email.lower()
    if email == principal.user.email.lower():
        raise ApiError(409, "That's the account owner's email.", code="already_member")
    existing = db.scalar(
        select(AccountMember).join(User, User.id == AccountMember.user_id)
        .where(AccountMember.account_id == principal.user.id, func.lower(User.email) == email)
    )
    if existing is not None:
        raise ApiError(409, f"{email} is already a member.", code="already_member")
    members = db.scalar(select(func.count()).where(AccountMember.account_id == principal.user.id)) or 0
    if members >= MAX_MEMBERS:
        raise ApiError(409, f"Accounts can have at most {MAX_MEMBERS} members.", code="member_limit_reached")
    # One open invite per email: a new one replaces the old link.
    now = datetime.now(UTC)
    db.execute(
        update(AccountInvite)
        .where(AccountInvite.account_id == principal.user.id, AccountInvite.email == email,
               AccountInvite.accepted_at.is_(None), AccountInvite.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    token = f"hfinv_{new_session_token()}"
    invite = AccountInvite(account_id=principal.user.id, email=email, role=body.role, token_hash=sha256_hex(token),
                           invited_by_user_id=principal.actor_id, created_at=now, expires_at=now + INVITE_TTL)
    db.add(invite)
    db.flush()
    audit.record(db, principal, "team.invite_created", "invite", invite.id, {"email": email, "role": body.role})
    db.commit()
    return {"invite": InviteOut.model_validate(invite), "token": token, "accept_path": f"/invite/{token}"}


@router.delete("/invites/{invite_id}", response_model=InviteOut)
def revoke_invite(invite_id: str, principal: TeamManage, db: DB) -> AccountInvite:
    invite = db.scalar(select(AccountInvite).where(AccountInvite.id == invite_id,
                                                   AccountInvite.account_id == principal.user.id))
    if invite is None:
        raise not_found("Invite")
    _check_can_manage(principal, invite.role)
    if invite.revoked_at is None and invite.accepted_at is None:
        invite.revoked_at = datetime.now(UTC)
        audit.record(db, principal, "team.invite_revoked", "invite", invite.id, {"email": invite.email})
        db.commit()
    return invite


def _open_invite(db: DB, token: str) -> AccountInvite:
    invite = db.scalar(select(AccountInvite).where(AccountInvite.token_hash == sha256_hex(token)))
    if (invite is None or invite.revoked_at is not None or invite.accepted_at is not None
            or invite.expires_at <= datetime.now(UTC)):
        raise ApiError(404, "This invitation link is invalid, expired, or has already been used.",
                       code="invite_invalid")
    return invite


@invites_router.get("/{token}", response_model=InvitePreview)
def preview_invite(token: str, principal: SessionPrincipal, db: DB) -> dict:
    invite = _open_invite(db, token)
    owner = db.get(User, invite.account_id)
    return {"account_owner_email": owner.email, "email": invite.email, "role": invite.role,
            "expires_at": invite.expires_at}


@invites_router.post("/{token}/accept", response_model=UserEnvelope)
def accept_invite(token: str, principal: SessionPrincipal, db: DB) -> dict:
    """Join the account. The logged-in user's email must match the invite. Switches this session into it."""
    invite = _open_invite(db, token)
    me = principal.actor
    if me.email.lower() != invite.email.lower():
        raise ApiError(403, f"This invitation is for {invite.email}. Log in with that email to accept it.",
                       code="invite_wrong_user")
    if member_role(db, invite.account_id, me.id) is None:
        db.add(AccountMember(account_id=invite.account_id, user_id=me.id, role=invite.role,
                             invited_by_user_id=invite.invited_by_user_id))
    invite.accepted_at = datetime.now(UTC)
    db.execute(update(UserSession).where(UserSession.id == principal.session.id)
               .values(account_id=invite.account_id))
    db.flush()
    team = db.get(User, invite.account_id)
    audit.record(db, Principal(user=team, via="session", actor=me, role=invite.role, ip=principal.ip),
                 "team.member_joined", "user", me.id, {"email": me.email, "role": invite.role})
    db.commit()
    return {"user": UserOut.model_validate(me)}


