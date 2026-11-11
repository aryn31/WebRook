#!/usr/bin/env python3
"""Fill HookFlow with demo accounts and 30 days of realistic activity, for demos and screenshots.

    docker compose exec api python scripts/seed_demo.py           # add the demo accounts (skips if they exist)
    docker compose exec api python scripts/seed_demo.py --reset   # delete and recreate them

On a public server, choose the password: DEMO_PASSWORD=… python scripts/seed_demo.py

Only touches the demo accounts listed below (all on example.com / example.org / example.net, which can't belong
to real people). Every account's password is DEMO_PASSWORD. Deliveries are written as finished history, so the
worker never tries to send to the made-up URLs.

Accounts:
- maya.demo@example.com: "Northwind", a busy store platform. Team, API keys, 5 endpoints in different states,
  6 merchants using the customer portal, alerts, signature checks, replays and an audit trail.
- jordan.demo@example.org: "Acme Analytics", a smaller account. Maya is a developer in it (shows the account
  switcher).
- new.demo@example.net: a brand-new account with nothing in it (shows the getting-started checklist).
"""

import argparse
import os
import random
import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from sqlalchemy import delete, insert, select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.ids import _encode  # noqa: E402
from app.models import (  # noqa: E402
    AccountMember, ApiKey, AuditLog, Consumer, Delivery, DeliveryAttempt, DeliveryReplay, Endpoint,
    EndpointSubscription, Event, User,
)
from app.security import encrypt_secret, hash_password, new_api_key, new_signing_secret  # noqa: E402

# Set DEMO_PASSWORD when seeding a public server: the default below is in a public repository.
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD") or "demo123456"
DAYS = 29  # stays inside the 30-day retention window
rng = random.Random(20261107)
NOW = datetime.now(UTC).replace(microsecond=0)


def id_at(prefix: str, when: datetime) -> str:
    """An ID that sorts as if it was created at ``when`` (IDs are time-ordered)."""
    return f"{prefix}_{_encode(int(when.timestamp() * 1000), 10)}{_encode(rng.getrandbits(80), 16)}"


def ago(**kw) -> datetime:
    return NOW - timedelta(**kw)


# --- What each endpoint does over time ------------------------------------------------------------------------
# Returns the list of attempt outcomes for a delivery created at ``t``: [(status_code or None, error, ms), ...]

OK_BODIES = ['{"ok":true}', '{"received":true}', '{"status":"accepted"}', "OK", ""]


def _ok(lo, hi):
    return (rng.choice([200, 200, 200, 204, 202]), None, rng.randint(lo, hi))


def healthy(lo=40, hi=220, flaky=0.004):
    def run(t):
        if rng.random() < flaky:
            return [(None, "Destination did not respond within 10 seconds.", 10000), _ok(lo, hi)]
        return [_ok(lo, hi)]
    return run


def billing(t):
    # A 2-hour outage two days ago, and more 503s than usual in the last day (shows as "degraded").
    outage_start, outage_end = ago(days=2, hours=5), ago(days=2, hours=3)
    if outage_start <= t <= outage_end:
        return [(503, "Destination returned HTTP 503.", rng.randint(900, 1600)) for _ in range(5)]
    rate = 0.16 if t > ago(hours=24) else 0.06
    out = []
    while rng.random() < rate and len(out) < 3:
        out.append((503, "Destination returned HTTP 503.", rng.randint(800, 1500)))
    return out + [_ok(80, 400)]


def legacy_crm(t):
    if t > ago(hours=20):  # someone removed the route yesterday
        return [(404, "Destination returned HTTP 404.", rng.randint(30, 90))]
    return healthy(120, 700, 0.02)(t)


def broken_since(days):
    def run(t):
        if t > ago(days=days):
            return [(500, "Destination returned HTTP 500.", rng.randint(50, 300)) for _ in range(5)]
        return healthy()(t)
    return run


# --- Payloads ---------------------------------------------------------------------------------------------------

FIRST = ["olivia", "liam", "emma", "noah", "ava", "mateo", "sofia", "arjun", "mia", "kenji", "lucia", "omar"]
PRODUCTS = ["Linen shirt", "Trail shoes", "Ceramic mug", "Wool scarf", "Desk lamp", "Notebook set", "Coffee beans"]


def payload(event_type: str, n: int) -> dict:
    who = rng.choice(FIRST)
    amount = rng.choice([1299, 2499, 4999, 7450, 12900, 3600, 890, 15800])
    base = {"customer": {"id": f"cus_{1000 + n % 4000}", "email": f"{who}.{n % 97}@example.com"}}
    if event_type.startswith("order"):
        return {"order_id": f"ord_{20000 + n}", "total": amount, "currency": "USD",
                "items": [{"name": rng.choice(PRODUCTS), "qty": rng.randint(1, 3)}], **base}
    if event_type.startswith("invoice"):
        return {"invoice_id": f"in_{50000 + n}", "amount_due": amount, "currency": "USD", **base}
    if event_type.startswith("refund"):
        return {"refund_id": f"re_{7000 + n}", "order_id": f"ord_{20000 + n - 40}", "amount": amount // 2, **base}
    if event_type.startswith("subscription"):
        return {"subscription_id": f"sub_{3000 + n % 500}", "plan": rng.choice(["starter", "growth"]), **base}
    return base


def matches(subs: list[str], event_type: str) -> bool:
    return any(s == "*" or s == event_type or (s.endswith(".*") and event_type.startswith(s[:-1])) for s in subs)


def weighted(pairs):
    total = sum(w for _, w in pairs)
    r = rng.random() * total
    for item, w in pairs:
        r -= w
        if r <= 0:
            return item
    return pairs[-1][0]


def times(days: int, per_day: float, growth: float = 0.5) -> list[datetime]:
    """Event times: more on weekdays and in the daytime, growing over the period."""
    out = []
    for d in range(days, -1, -1):
        day = (NOW - timedelta(days=d)).replace(hour=0, minute=0, second=0)
        weekday = day.weekday() < 5
        n = per_day * (1 + growth * (days - d) / days) * (1 if weekday else 0.55) * rng.uniform(0.85, 1.15)
        for _ in range(int(n)):
            hour = min(23, max(0, int(rng.gauss(14, 4.5))))
            t = day + timedelta(hours=hour, minutes=rng.randint(0, 59), seconds=rng.randint(0, 59))
            if t < NOW - timedelta(minutes=2):
                out.append(t)
    return sorted(out)


# --- Writing ---------------------------------------------------------------------------------------------------

class Writer:
    def __init__(self, db):
        self.db = db
        self.events, self.deliveries, self.attempts, self.audit, self.replays = [], [], [], [], []

    def flush(self):
        for model, rows in ((Event, self.events), (Delivery, self.deliveries), (DeliveryAttempt, self.attempts),
                            (DeliveryReplay, self.replays), (AuditLog, self.audit)):
            for i in range(0, len(rows), 2000):
                self.db.execute(insert(model), rows[i:i + 2000])
            rows.clear()

    def log(self, account, actor, action, when, rtype=None, rid=None, details=None, via="session", key=None):
        self.audit.append({
            "id": id_at("aud", when), "user_id": account.id, "actor_type": via, "api_key_id": key,
            "actor_user_id": actor.id if actor else None, "action": action, "resource_type": rtype,
            "resource_id": rid, "details": details, "ip_address": rng.choice(["203.0.113.24", "198.51.100.7",
                                                                              "192.0.2.61"]), "created_at": when,
        })

    def event(self, account, event_type, t, n, endpoints, consumer_id=None, replay_actor=None):
        eid = id_at("evt", t)
        self.events.append({"id": eid, "user_id": account.id, "event_type": event_type, "payload": payload(event_type, n),
                            "idempotency_key": f"{event_type}-{n}" if n % 3 == 0 else None,
                            "consumer_id": consumer_id, "created_at": t})
        for ep, behaviour in endpoints:
            if ep.created_at > t or not matches(ep.event_types_cache, event_type):
                continue
            if not ep.enabled and t > ep.disabled_at:
                continue
            self._delivery(account, eid, t, ep, behaviour(t), replay_actor, behaviour)

    def _delivery(self, account, eid, t, ep, outcomes, replay_actor, behaviour):
        did = id_at("dlv", t)
        max_attempts = ep.max_attempts
        outcomes = outcomes[:max_attempts]
        clock = t + timedelta(milliseconds=rng.randint(150, 1400))
        backoff = [30, 120, 480, 1920, 7680]
        last = None
        for i, (code, error, ms) in enumerate(outcomes, start=1):
            success = code is not None and 200 <= code < 300
            self.attempts.append({
                "id": id_at("att", clock), "delivery_id": did, "attempt_number": i, "started_at": clock,
                "completed_at": clock + timedelta(milliseconds=ms), "duration_ms": ms, "response_status": code,
                "response_body": rng.choice(OK_BODIES) if success else ("Service Unavailable" if code == 503 else
                                                                         "Not Found" if code == 404 else
                                                                         "Internal Server Error" if code else None),
                "error": None if success else error, "success": success,
            })
            last = (code, error, success, clock + timedelta(milliseconds=ms))
            if success:
                break
            clock = clock + timedelta(seconds=backoff[i - 1] * rng.uniform(0.8, 1.2))
        code, error, success, done = last
        failed_for_good = not success
        status = "delivered" if success else "failed"
        message = None
        if failed_for_good:
            retryable = code is None or code >= 500
            message = error + (f" Gave up after {len(outcomes)} attempts." if retryable else "")
        # Some failures were replayed later, once the endpoint was working again.
        replayed = failed_for_good and replay_actor is not None and rng.random() < 0.35 and done < ago(hours=3)
        replay_count, replayed_at, base = 0, None, 0
        if replayed:
            replayed_at = done + timedelta(minutes=rng.randint(20, 300))
            first = behaviour(replayed_at)[0][0] if replayed_at < NOW else None
            if first is not None and 200 <= first < 300:
                base = len(outcomes)
                self.attempts.append({
                    "id": id_at("att", replayed_at), "delivery_id": did, "attempt_number": base + 1,
                    "started_at": replayed_at, "completed_at": replayed_at + timedelta(milliseconds=95),
                    "duration_ms": 95, "response_status": 200, "response_body": '{"ok":true}', "error": None,
                    "success": True,
                })
                self.replays.append({"id": id_at("rpl", replayed_at), "delivery_id": did, "user_id": account.id,
                                     "actor_type": "session", "api_key_id": None, "previous_status": "failed",
                                     "first_attempt_number": base + 1, "created_at": replayed_at})
                self.log(account, replay_actor, "delivery.replayed", replayed_at, "delivery", did,
                         {"event_id": eid, "endpoint_id": ep.id, "previous_status": "failed"})
                status, code, message, done, replay_count = "delivered", 200, None, replayed_at, 1
                max_attempts += base
        self.deliveries.append({
            "id": did, "user_id": account.id, "event_id": eid, "endpoint_id": ep.id, "status": status,
            "attempt_count": base + 1 if replay_count else len(outcomes), "max_attempts": max_attempts, "next_attempt_at": None, "locked_until": None,
            "enqueued_at": done, "last_status_code": code, "last_error": message,
            "delivered_at": done if status == "delivered" else None, "retry_base_attempt": base,
            "replay_count": replay_count, "last_replayed_at": replayed_at if replay_count else None,
            "created_at": t, "updated_at": done,
        })


def make_user(db, email, created):
    u = User(id=id_at("usr", created), email=email, password_hash=hash_password(DEMO_PASSWORD), created_at=created,
             email_verified_at=created + timedelta(minutes=3))
    db.add(u)
    return u


def make_endpoint(db, account, *, url, description, types, created, consumer=None, enabled=True,
                  disabled_at=None, max_attempts=5, security=None):
    ep = Endpoint(id=id_at("ep", created), user_id=account.id, consumer_id=consumer.id if consumer else None, url=url,
                  description=description, enabled=enabled, secret_encrypted=encrypt_secret(new_signing_secret()),
                  max_attempts=max_attempts, created_at=created, updated_at=disabled_at or created,
                  security_check=security, subscriptions=[EndpointSubscription(event_type=t) for t in types])
    db.add(ep)
    ep.event_types_cache = types
    ep.disabled_at = disabled_at or NOW
    return ep


def security(verdict: str, when: datetime) -> dict:
    accept = {"pass": [], "partial": ["old_timestamp"],
              "fail": ["wrong_signature", "tampered_body", "old_timestamp", "missing_signature"]}[verdict]
    labels = [("valid", "Correctly signed request"), ("wrong_signature", "Signed with the wrong secret"),
              ("tampered_body", "Body changed after signing"), ("old_timestamp", "Correct signature, but an hour old"),
              ("missing_signature", "No signature header")]
    summary = {"pass": "Your endpoint accepted the genuine request and rejected every forged one.",
               "partial": "Your endpoint checks signatures, but it accepted an hour-old request. Someone who captures a "
                          "real request could send it again later. Also reject requests whose HookFlow-Timestamp is "
                          "more than 5 minutes from now.",
               "fail": "Your endpoint accepted requests that weren't signed by HookFlow, so anyone who finds its URL "
                       "can send it fake events. Verify the HookFlow-Signature header before trusting a request."}[verdict]
    probes = []
    for name, label in labels:
        accepted = name == "valid" or name in accept
        probes.append({"name": name, "label": label, "expected": "accept" if name == "valid" else "reject",
                       "status_code": 200 if accepted else 401, "error": None, "accepted": accepted,
                       "ok": accepted == (name == "valid"), "server_error": False})
    return {"verdict": verdict, "summary": summary, "checked_at": when.isoformat(), "probes": probes}


def make_key(db, account, creator, name, scopes, created, last_used=None, revoked=None):
    _, prefix, key_hash = new_api_key()
    k = ApiKey(id=id_at("key", created), user_id=account.id, name=name, prefix=prefix, key_hash=key_hash,
               scopes=scopes, created_by_user_id=creator.id, created_at=created, last_used_at=last_used,
               revoked_at=revoked)
    db.add(k)
    return k


# --- The accounts ----------------------------------------------------------------------------------------------

NORTHWIND_TYPES = [("order.created", 30), ("order.paid", 25), ("order.shipped", 15), ("invoice.created", 8),
                   ("invoice.paid", 7), ("invoice.payment_failed", 1.5), ("customer.created", 6),
                   ("customer.updated", 4), ("order.refunded", 1.5), ("refund.issued", 1.5),
                   ("subscription.renewed", 3)]
MERCHANTS = [("bloom-florist", "Bloom & Co. Florist", "bloomandco"), ("urban-threads", "Urban Threads", "urbanthreads"),
             ("peak-outdoor", "Peak Outdoor Supply", "peakoutdoor"), ("corner-bakery", "Corner Bakery", "cornerbakery"),
             ("lumen-books", "Lumen Books", "lumenbooks"), ("harbor-coffee", "Harbor Coffee Roasters", "harborcoffee")]


def northwind(db, w: Writer) -> dict:
    start = ago(days=DAYS + 1, hours=3)
    maya = make_user(db, "maya.demo@example.com", start)
    team = {email: make_user(db, email, start + timedelta(days=d))
            for email, d in [("alex.demo@example.com", 1), ("priya.demo@example.com", 2), ("sam.demo@example.com", 6)]}
    db.flush()
    for (email, role), d in zip([("alex.demo@example.com", "admin"), ("priya.demo@example.com", "developer"),
                                 ("sam.demo@example.com", "viewer")], [1, 2, 6]):
        db.add(AccountMember(account_id=maya.id, user_id=team[email].id, role=role, invited_by_user_id=maya.id,
                             created_at=start + timedelta(days=d, hours=1)))
    alex, priya = team["alex.demo@example.com"], team["priya.demo@example.com"]
    w.log(maya, maya, "auth.registered", start, "user", maya.id)

    keys = [
        make_key(db, maya, maya, "Production server", None, start + timedelta(hours=2), last_used=ago(minutes=4)),
        make_key(db, maya, priya, "Billing worker", ["events:write"], start + timedelta(days=3), last_used=ago(minutes=11)),
        make_key(db, maya, alex, "Grafana dashboard", ["events:read", "deliveries:read", "endpoints:read"],
                 start + timedelta(days=9), last_used=ago(hours=1)),
        make_key(db, maya, priya, "Old staging key", None, start + timedelta(days=1), last_used=ago(days=12),
                 revoked=ago(days=11)),
    ]
    db.flush()
    for k in keys:
        actor = db.get(User, k.created_by_user_id)
        w.log(maya, actor, "api_key.created", k.created_at, "api_key", k.id,
              {"name": k.name, "prefix": k.prefix, "scopes": k.scopes})
        if k.revoked_at:
            w.log(maya, alex, "api_key.revoked", k.revoked_at, "api_key", k.id, {"name": k.name})

    eps = [
        (make_endpoint(db, maya, url="https://api.northwind.example.com/webhooks/orders", description="Order service",
                       types=["order.*"], created=start + timedelta(hours=3), security=security("pass", ago(days=4))),
         healthy()),
        (make_endpoint(db, maya, url="https://billing.northwind.example.com/hooks/hookflow", description="Billing",
                       types=["invoice.*", "order.paid", "refund.*"], created=start + timedelta(hours=4),
                       security=security("partial", ago(days=6))), billing),
        (make_endpoint(db, maya, url="https://ingest.warehouse.example.net/v2/hookflow", description="Data warehouse",
                       types=["*"], created=ago(days=12, hours=5), max_attempts=8,
                       security=security("pass", ago(days=12))), healthy(220, 650, 0.01)),
        (make_endpoint(db, maya, url="https://crm-legacy.northwind.example.com/api/hooks", description="Legacy CRM",
                       types=["customer.*"], created=start + timedelta(days=2), max_attempts=4,
                       security=security("fail", ago(days=20))), legacy_crm),
        (make_endpoint(db, maya, url="https://relay.chatops.example.org/T0451/alerts", description="Team chat alerts",
                       types=["order.refunded", "invoice.payment_failed"], created=start + timedelta(days=5),
                       enabled=False, disabled_at=ago(days=8)), healthy()),
    ]
    db.flush()
    for ep, _ in eps:
        w.log(maya, rng.choice([maya, priya]), "endpoint.created", ep.created_at, "endpoint", ep.id,
              {"url": ep.url, "event_types": ep.event_types_cache, "max_attempts": ep.max_attempts})
    billing_ep, crm_ep, chat_ep = eps[1][0], eps[3][0], eps[4][0]
    w.log(maya, alex, "endpoint.secret_rotated", ago(days=9, hours=2), "endpoint", billing_ep.id,
          {"grace_period_seconds": 86400})
    w.log(maya, priya, "endpoint.updated", chat_ep.disabled_at, "endpoint", chat_ep.id,
          {"changes": {"enabled": {"from": True, "to": False}}})
    for ep, _ in eps[:4]:
        w.log(maya, priya, "endpoint.security_checked", datetime.fromisoformat(ep.security_check["checked_at"]),
              "endpoint", ep.id, {"verdict": ep.security_check["verdict"]})
    crm_ep.consecutive_failures = 40
    crm_ep.failing_since = ago(hours=20)
    crm_ep.alert_sent_at = ago(hours=19, minutes=40)

    # Merchants using the customer portal.
    consumers = []
    for i, (uid, name, domain) in enumerate(MERCHANTS):
        created = start + timedelta(days=4 + i * 3)
        c = Consumer(id=id_at("cns", created), user_id=maya.id, uid=uid, name=name, created_at=created,
                     updated_at=created)
        db.add(c)
        db.flush()
        w.log(maya, priya, "consumer.created", created, "consumer", c.id, {"uid": uid, "name": name})
        behaviour = broken_since(3) if uid == "urban-threads" else healthy(60, 400, 0.01)
        cep = [(make_endpoint(db, maya, url=f"https://{domain}.example.com/webhooks/orders",
                              description="Store orders", types=["order.*"], consumer=c,
                              created=created + timedelta(hours=2),
                              security=security("pass" if i % 3 != 1 else "fail", created + timedelta(hours=3))),
                behaviour)]
        if i % 2 == 0:
            cep.append((make_endpoint(db, maya, url=f"https://hooks.{domain}.example.com/accounting",
                                      description="Accounting", types=["order.paid", "order.refunded"], consumer=c,
                                      created=created + timedelta(days=1)), healthy(100, 500)))
        consumers.append((c, cep))
        w.log(maya, maya, "consumer.portal_opened", created + timedelta(hours=1), "consumer", c.id,
              {"uid": uid, "expires_in_minutes": 60})
    db.flush()

    for d in range(DAYS, -1, -1):
        for actor in (maya, alex, priya):
            if rng.random() < 0.7:
                w.log(maya, actor, "auth.login", ago(days=d, hours=rng.randint(1, 10)), "user", actor.id)

    endpoints = [(ep, b) for ep, b in eps]
    n = 0
    for t in times(DAYS, 120):
        n += 1
        w.event(maya, weighted(NORTHWIND_TYPES), t, n, endpoints, replay_actor=rng.choice([maya, priya, alex]))
    for c, cep in consumers:
        for t in times(DAYS, rng.uniform(6, 18)):
            if t < c.created_at:
                continue
            n += 1
            w.event(maya, weighted([("order.created", 5), ("order.paid", 4), ("order.shipped", 3),
                                    ("order.refunded", 0.3)]), t, n, cep, consumer_id=c.id, replay_actor=None)
    return {"owner": maya}


def acme(db, w: Writer, maya: User):
    start = ago(days=15, hours=6)
    jordan = make_user(db, "jordan.demo@example.org", start)
    db.flush()
    db.add(AccountMember(account_id=jordan.id, user_id=maya.id, role="developer", invited_by_user_id=jordan.id,
                         created_at=start + timedelta(days=2)))
    w.log(jordan, jordan, "auth.registered", start, "user", jordan.id)
    k = make_key(db, jordan, jordan, "Production", None, start + timedelta(hours=1), last_used=ago(minutes=30))
    eps = [
        (make_endpoint(db, jordan, url="https://events.acme-analytics.example.org/collect", description="Collector",
                       types=["*"], created=start + timedelta(hours=1)), healthy(30, 150)),
        (make_endpoint(db, jordan, url="https://reports.acme-analytics.example.org/hooks", description="Reports",
                       types=["report.*"], created=start + timedelta(days=3)), healthy(300, 900, 0.03)),
    ]
    db.flush()
    w.log(jordan, jordan, "api_key.created", k.created_at, "api_key", k.id, {"name": k.name, "prefix": k.prefix})
    types = [("pageview.batch", 10), ("signup.completed", 3), ("report.generated", 2), ("report.failed", 0.3)]
    for i, t in enumerate(times(14, 45, growth=1.2)):
        w.event(jordan, weighted(types), t, 90000 + i, eps, replay_actor=jordan)


def fresh(db, w: Writer):
    u = make_user(db, "new.demo@example.net", ago(hours=2))
    db.flush()
    w.log(u, u, "auth.registered", ago(hours=2), "user", u.id)


EMAILS = ["maya.demo@example.com", "alex.demo@example.com", "priya.demo@example.com", "sam.demo@example.com",
          "jordan.demo@example.org", "new.demo@example.net"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reset", action="store_true", help="delete the demo accounts first, then recreate them")
    args = ap.parse_args()
    with SessionLocal() as db:
        existing = db.scalars(select(User).where(User.email.in_(EMAILS))).all()
        if existing and not args.reset:
            sys.exit("Demo accounts already exist. Run with --reset to delete and recreate them.")
        if existing:
            db.execute(delete(User).where(User.email.in_(EMAILS)))
            db.commit()
            print(f"Deleted {len(existing)} demo users and all their data.")
        w = Writer(db)
        owners = northwind(db, w)
        db.flush()
        acme(db, w, owners["owner"])
        fresh(db, w)
        db.flush()
        counts = (len(w.events), len(w.deliveries), len(w.attempts))
        w.flush()
        db.commit()
    print(f"Created {counts[0]} events, {counts[1]} deliveries and {counts[2]} attempts.\n")
    print(f"Log in with any of these (password: {DEMO_PASSWORD}):")
    print("  maya.demo@example.com     Northwind owner: the full demo (also a developer in Acme Analytics)")
    print("  alex.demo@example.com     Northwind admin")
    print("  priya.demo@example.com    Northwind developer")
    print("  sam.demo@example.com      Northwind viewer (read-only)")
    print("  jordan.demo@example.org   Acme Analytics owner")
    print("  new.demo@example.net      a brand-new, empty account")


if __name__ == "__main__":
    main()
