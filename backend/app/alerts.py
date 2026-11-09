"""Email alerts when an endpoint keeps failing, and when it recovers.

Each endpoint counts its failed attempts in a row. When the count reaches ALERT_AFTER_FAILURES, the account's
owner and admins (those who haven't turned alerts off) get one "endpoint is failing" email. Nothing more is
sent while it stays down. The next successful attempt resets the count and, if an alert went out, sends one
"back to normal" email with how long it was down and how many deliveries failed meanwhile.

Endpoints that belong to a consumer (customer portal) are skipped: a SaaS account may have thousands, and
their consumers watch them in the portal.

``on_attempt`` runs inside the transaction that records the attempt, so the decision to alert is made exactly
once even with many workers. The emails are sent by ``send`` after that transaction commits.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import email_templates, mailer
from app.config import get_settings
from app.db import SessionLocal
from app.models import AccountMember, Delivery, DeliveryAttempt, DeliveryStatus, Endpoint, User

log = logging.getLogger("hookflow.alerts")


@dataclass
class Pending:
    kind: str  # "failing" or "recovered"
    endpoint_id: str
    at: datetime
    failing_since: datetime | None = None


def on_attempt(db: Session, endpoint_id: str, success: bool, now: datetime) -> Pending | None:
    """Update the endpoint's failure count for one attempt. Returns an alert to send after commit, if any."""
    if success:
        # Cheap check first, so a healthy endpoint's row isn't locked on every delivery.
        count, sent = db.execute(
            select(Endpoint.consecutive_failures, Endpoint.alert_sent_at).where(Endpoint.id == endpoint_id)
        ).one()
        if count == 0 and sent is None:
            return None
        since, sent = db.execute(
            select(Endpoint.failing_since, Endpoint.alert_sent_at).where(Endpoint.id == endpoint_id).with_for_update()
        ).one()
        db.execute(
            update(Endpoint).where(Endpoint.id == endpoint_id)
            .values(consecutive_failures=0, failing_since=None, alert_sent_at=None)
        )
        return Pending("recovered", endpoint_id, now, since) if sent is not None else None

    count, sent = db.execute(
        update(Endpoint).where(Endpoint.id == endpoint_id)
        .values(consecutive_failures=Endpoint.consecutive_failures + 1,
                failing_since=func.coalesce(Endpoint.failing_since, now))
        .returning(Endpoint.consecutive_failures, Endpoint.alert_sent_at)
    ).one()
    threshold = get_settings().alert_after_failures
    if threshold <= 0 or count < threshold or sent is not None:
        return None
    claimed = db.execute(
        update(Endpoint).where(Endpoint.id == endpoint_id, Endpoint.alert_sent_at.is_(None)).values(alert_sent_at=now)
    ).rowcount
    return Pending("failing", endpoint_id, now) if claimed else None


def recipients(db: Session, account_id: str) -> list[User]:
    """The account owner and its admins who want alerts and have a verified email."""
    owner = db.get(User, account_id)
    admins = db.scalars(
        select(User).join(AccountMember, AccountMember.user_id == User.id)
        .where(AccountMember.account_id == account_id, AccountMember.role == "admin")
    ).all()
    return [u for u in [owner, *admins] if u is not None and u.failure_alerts and u.email_verified_at is not None]


def send(p: Pending) -> int:
    """Email an alert. Returns how many emails were sent. Never raises: alerts must not break delivery."""
    try:
        return _send(p)
    except Exception:  # noqa: BLE001
        log.exception("Failure alert not sent", extra={"endpoint_id": p.endpoint_id, "kind": p.kind})
        return 0


def _send(p: Pending) -> int:
    s = get_settings()
    app_url = s.app_url.rstrip("/")
    with SessionLocal() as db:
        ep = db.get(Endpoint, p.endpoint_id)
        if ep is None:
            return 0
        to = recipients(db, ep.user_id)
        name = ep.description or ep.url
        if p.kind == "failing":
            last = db.execute(
                select(DeliveryAttempt.response_status, DeliveryAttempt.error)
                .join(Delivery, Delivery.id == DeliveryAttempt.delivery_id)
                .where(Delivery.endpoint_id == ep.id, DeliveryAttempt.success.is_(False))
                .order_by(DeliveryAttempt.completed_at.desc()).limit(1)
            ).first()
            subject, text, html = email_templates.endpoint_failing(
                name=name, url=ep.url, failures=ep.consecutive_failures, failing_since=ep.failing_since,
                status_code=last[0] if last else None, error=last[1] if last else None,
                endpoint_link=f"{app_url}/endpoints/{ep.id}", app_url=app_url,
            )
        else:
            failed = db.scalar(
                select(func.count()).select_from(Delivery)
                .where(Delivery.endpoint_id == ep.id, Delivery.status == DeliveryStatus.FAILED,
                       Delivery.updated_at >= (p.failing_since or p.at))
            ) or 0
            subject, text, html = email_templates.endpoint_recovered(
                name=name, url=ep.url, down_for=(p.at - p.failing_since) if p.failing_since else None,
                failed_deliveries=failed, endpoint_link=f"{app_url}/endpoints/{ep.id}", app_url=app_url,
            )
        emails = [u.email for u in to]

    sent = 0
    for email in emails:
        try:
            mailer.send(email, subject, text, html)
            sent += 1
        except mailer.MailError:
            pass  # logged by the mailer
    if p.kind == "failing" and emails and sent == 0:
        # Nobody got it: allow the next failed attempt to try again.
        with SessionLocal() as db:
            db.execute(update(Endpoint).where(Endpoint.id == p.endpoint_id, Endpoint.alert_sent_at == p.at)
                       .values(alert_sent_at=None))
            db.commit()
    log.info("failure alert", extra={"endpoint_id": p.endpoint_id, "kind": p.kind, "sent": sent})
    return sent
