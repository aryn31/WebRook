"""Milestone 4: pattern subscriptions, custom retry schedules, bulk replay, scoped API keys, team accounts."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.db import SessionLocal
from app.models import AuditLog, Delivery, DeliveryStatus
from app.schemas import matching_subscriptions
from app.worker.engine import process_delivery
from app.worker.retry import retry_delay_seconds
from tests.conftest import make_user

URL = "https://hooks.example.com/in"


def _endpoint(c, h, types, **extra) -> dict:
    r = c.post("/v1/endpoints", json={"url": URL, "event_types": types, **extra}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _send(c, h, event_type: str) -> dict:
    r = c.post("/v1/events", json={"event_type": event_type, "data": {}}, headers=h)
    assert r.status_code == 202, r.text
    return r.json()


def _fail_all(user_id: str | None = None) -> None:
    with SessionLocal() as db:
        stmt = update(Delivery).values(status=DeliveryStatus.FAILED, attempt_count=1, next_attempt_at=None,
                                       last_error="boom")
        if user_id:
            stmt = stmt.where(Delivery.user_id == user_id)
        db.execute(stmt)
        db.commit()


def _me(c) -> dict:
    r = c.get("/v1/auth/me")
    assert r.status_code == 200, r.text
    return r.json()


# --- Pattern subscriptions ------------------------------------------------------------------------------------

def test_matching_subscriptions_lists_every_prefix_pattern():
    assert matching_subscriptions("order.item.added") == ["order.item.added", "*", "order.*", "order.item.*"]
    assert matching_subscriptions("ping") == ["ping", "*"]


def test_pattern_subscription_receives_matching_types_only(user_a):
    c, h = user_a
    _endpoint(c, h, ["order.*"])
    assert _send(c, h, "order.created")["delivery_count"] == 1
    assert _send(c, h, "order.item.added")["delivery_count"] == 1
    assert _send(c, h, "orders.created")["delivery_count"] == 0
    assert _send(c, h, "order")["delivery_count"] == 0
    assert _send(c, h, "user.order.created")["delivery_count"] == 0


def test_overlapping_patterns_create_one_delivery(user_a):
    c, h = user_a
    _endpoint(c, h, ["*", "order.*", "order.item.*", "order.item.added"])
    assert _send(c, h, "order.item.added")["delivery_count"] == 1


@pytest.mark.parametrize("bad", ["order*", "*.created", "order.*.added", ".*", "order..*", "**"])
def test_invalid_patterns_are_rejected(user_a, bad):
    c, h = user_a
    r = c.post("/v1/endpoints", json={"url": URL, "event_types": [bad]}, headers=h)
    assert r.status_code == 422, (bad, r.text)


def test_events_themselves_cannot_use_patterns(user_a):
    c, h = user_a
    r = c.post("/v1/events", json={"event_type": "order.*", "data": {}}, headers=h)
    assert r.status_code == 422


# --- Custom retry schedules -----------------------------------------------------------------------------------

def test_retry_delay_follows_a_custom_schedule_and_repeats_the_last_value():
    schedule = [10, 60, 600]
    for attempt, expected in [(1, 10), (2, 60), (3, 600), (4, 600), (9, 600)]:
        d = retry_delay_seconds(attempt, None, schedule)
        assert expected * 0.9 <= d <= expected * 1.1, (attempt, d)


def test_retry_after_still_wins_over_a_shorter_custom_delay():
    assert retry_delay_seconds(1, "120", [5]) >= 120


def test_retry_schedule_validation_and_update(user_a):
    c, h = user_a
    for bad in [[], [0], [86401], list(range(1, 11))]:
        r = c.post("/v1/endpoints", json={"url": URL, "event_types": ["*"], "retry_schedule": bad}, headers=h)
        assert r.status_code == 422, (bad, r.text)
    ep = _endpoint(c, h, ["*"], retry_schedule=[5, 30])
    assert ep["retry_schedule"] == [5, 30]
    r = c.patch(f"/v1/endpoints/{ep['id']}", json={"retry_schedule": [15]}, headers=h)
    assert r.json()["retry_schedule"] == [15]
    r = c.patch(f"/v1/endpoints/{ep['id']}", json={"retry_schedule": None}, headers=h)
    assert r.json()["retry_schedule"] is None
    r = c.patch(f"/v1/endpoints/{ep['id']}", json={"description": "x"}, headers=h)
    assert r.json()["retry_schedule"] is None


@respx.mock
def test_engine_schedules_the_retry_from_the_endpoint_schedule(user_a):
    c, h = user_a
    _endpoint(c, h, ["*"], retry_schedule=[7])
    evt = _send(c, h, "order.created")
    dlv = c.get(f"/v1/events/{evt['event_id']}/deliveries", headers=h).json()["data"][0]["id"]
    respx.post(URL).mock(return_value=httpx.Response(503))
    before = datetime.now(UTC)
    assert process_delivery(dlv) == "failed"  # this attempt failed; the delivery itself is retrying
    with SessionLocal() as db:
        d = db.get(Delivery, dlv)
        assert d.status == DeliveryStatus.RETRYING
        wait = (d.next_attempt_at - before).total_seconds()
    assert 7 * 0.9 - 1 <= wait <= 7 * 1.1 + 1, wait


# --- Bulk replay ----------------------------------------------------------------------------------------------

@pytest.fixture
def failed_many(user_a):
    c, h = user_a
    a = _endpoint(c, h, ["order.*"])
    b = _endpoint(c, h, ["user.*"])
    for _ in range(3):
        _send(c, h, "order.created")
    _send(c, h, "user.created")
    _fail_all()
    return c, h, a, b


def test_bulk_replay_dry_run_changes_nothing(failed_many, queued):
    c, h, a, _ = failed_many
    queued.clear()
    r = c.post("/v1/deliveries/replay", json={"dry_run": True}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["matched"] == 4 and len(body["replayed"]) == 4 and body["dry_run"] is True
    assert not queued
    statuses = {d["status"] for d in c.get("/v1/deliveries", headers=h).json()["data"]}
    assert statuses == {"failed"}


def test_bulk_replay_by_endpoint_and_in_batches(failed_many, queued):
    c, h, a, _ = failed_many
    queued.clear()
    r = c.post("/v1/deliveries/replay", json={"endpoint_id": a["id"], "limit": 2}, headers=h).json()
    assert r["matched"] == 2 and len(r["replayed"]) == 2 and r["has_more"] is True
    assert sorted(queued) == sorted(r["replayed"])
    r = c.post("/v1/deliveries/replay", json={"endpoint_id": a["id"], "limit": 2}, headers=h).json()
    assert r["matched"] == 1 and r["has_more"] is False
    r = c.post("/v1/deliveries/replay", json={"endpoint_id": a["id"]}, headers=h).json()
    assert r["matched"] == 0
    # The other endpoint's delivery is untouched.
    left = c.get("/v1/deliveries", params={"status": "failed"}, headers=h).json()["data"]
    assert len(left) == 1 and left[0]["event_type"] == "user.created"
    log = c.get("/v1/audit-logs", params={"action": "deliveries.bulk_replayed"}).json()["data"]
    assert len(log) == 2 and log[-1]["details"]["count"] == 2


def test_bulk_replay_filters_by_event_type_and_time(failed_many):
    c, h, *_ = failed_many
    r = c.post("/v1/deliveries/replay", json={"event_type": "user.created", "dry_run": True}, headers=h).json()
    assert r["matched"] == 1
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    r = c.post("/v1/deliveries/replay", json={"created_after": future, "dry_run": True}, headers=h).json()
    assert r["matched"] == 0


def test_bulk_replay_skips_disabled_endpoints(failed_many):
    c, h, a, _ = failed_many
    c.patch(f"/v1/endpoints/{a['id']}", json={"enabled": False}, headers=h)
    r = c.post("/v1/deliveries/replay", json={}, headers=h).json()
    assert r["matched"] == 1


def test_bulk_replay_is_tenant_isolated(failed_many, user_b):
    cb, hb = user_b
    r = cb.post("/v1/deliveries/replay", json={}, headers=hb).json()
    assert r["matched"] == 0


def test_bulk_replay_is_rate_limited(failed_many, monkeypatch):
    c, h, *_ = failed_many
    monkeypatch.setenv("BULK_REPLAY_RATE_LIMIT_PER_MINUTE", "1")
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        assert c.post("/v1/deliveries/replay", json={"dry_run": True}, headers=h).status_code == 200
        assert c.post("/v1/deliveries/replay", json={"dry_run": True}, headers=h).status_code == 429
    finally:
        get_settings.cache_clear()


# --- Scoped API keys ------------------------------------------------------------------------------------------

def _key(c, scopes=None, name="k") -> dict:
    body = {"name": name} | ({"scopes": scopes} if scopes is not None else {})
    r = c.post("/v1/api-keys", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_new_keys_default_to_every_scope(user_a):
    c, _ = user_a
    k = _key(c)
    assert set(k["api_key"]["scopes"]) == {"events:write", "events:read", "deliveries:read", "deliveries:replay",
                                           "endpoints:read", "endpoints:write", "audit:read"}


def test_send_only_key_can_send_but_not_read(user_a):
    c, h = user_a
    _endpoint(c, h, ["*"])
    k = _key(c, ["events:write"])
    kh = {"Authorization": f"Bearer {k['key']}"}
    assert c.post("/v1/events", json={"event_type": "a.b", "data": {}}, headers=kh).status_code == 202
    r = c.get("/v1/events", headers=kh)
    assert r.status_code == 403 and r.json()["error"]["code"] == "insufficient_scope"
    assert r.json()["error"]["details"]["required_scope"] == "events:read"
    assert c.get("/v1/endpoints", headers=kh).status_code == 403
    assert c.get("/v1/endpoints/x/secret", headers=kh).status_code == 403


def test_read_only_key_cannot_write(user_a):
    c, h = user_a
    ep = _endpoint(c, h, ["*"])
    kh = {"Authorization": f"Bearer {_key(c, ['endpoints:read', 'events:read'])['key']}"}
    assert c.get("/v1/endpoints", headers=kh).status_code == 200
    assert c.get(f"/v1/endpoints/{ep['id']}/secret", headers=kh).status_code == 403
    assert c.patch(f"/v1/endpoints/{ep['id']}", json={"enabled": False}, headers=kh).status_code == 403
    assert c.post("/v1/events", json={"event_type": "a.b", "data": {}}, headers=kh).status_code == 403
    assert c.post("/v1/deliveries/replay", json={}, headers=kh).status_code == 403


def test_unknown_or_empty_scopes_are_rejected(user_a):
    c, _ = user_a
    assert c.post("/v1/api-keys", json={"name": "k", "scopes": ["events:delete"]}).status_code == 422
    assert c.post("/v1/api-keys", json={"name": "k", "scopes": []}).status_code == 422
    assert c.post("/v1/api-keys", json={"name": "k", "scopes": ["team:manage"]}).status_code == 422


def test_keys_without_scopes_keep_full_access(user_a):
    """Keys made before scopes existed have NULL scopes and keep working for everything."""
    c, _ = user_a
    k = _key(c, ["events:read"])
    with SessionLocal() as db:
        from app.models import ApiKey

        db.execute(update(ApiKey).where(ApiKey.id == k["api_key"]["id"]).values(scopes=None))
        db.commit()
    kh = {"Authorization": f"Bearer {k['key']}"}
    assert c.post("/v1/endpoints", json={"url": URL, "event_types": ["*"]}, headers=kh).status_code == 201
    listed = next(x for x in c.get("/v1/api-keys").json()["data"] if x["id"] == k["api_key"]["id"])
    assert len(listed["scopes"]) == 7


def test_api_keys_cannot_manage_keys_or_the_team(user_a):
    _, h = user_a
    from app.main import app

    with TestClient(app) as anon:
        assert anon.get("/v1/api-keys", headers=h).status_code == 403
        assert anon.post("/v1/api-keys", json={"name": "x"}, headers=h).status_code == 403
        assert anon.post("/v1/team/invites", json={"email": "z@example.com"}, headers=h).status_code == 403


def test_scope_list_endpoint(user_a):
    c, _ = user_a
    scopes = [s["scope"] for s in c.get("/v1/api-keys/scopes").json()["data"]]
    assert scopes[0] == "events:write" and "audit:read" in scopes


# --- Team accounts --------------------------------------------------------------------------------------------

@pytest.fixture
def team():
    """Owner A plus a logged-in client for B (not yet a member). Returns (owner, owner_headers, b_client)."""
    from app.main import app

    with TestClient(app) as owner, TestClient(app) as b:
        make_user(owner, "owner@example.com")
        make_user(b, "b@example.com")
        oh = {"Authorization": f"Bearer {_key(owner)['key']}"}
        yield owner, oh, b


def _invite(owner, email="b@example.com", role="developer") -> dict:
    r = owner.post("/v1/team/invites", json={"email": email, "role": role})
    assert r.status_code == 201, r.text
    return r.json()


def _join(owner, b, role="developer", email="b@example.com") -> None:
    token = _invite(owner, email, role)["token"]
    r = b.post(f"/v1/invites/{token}/accept")
    assert r.status_code == 200, r.text


def test_invite_accept_and_work_in_the_team_account(team):
    owner, oh, b = team
    ep = _endpoint(owner, oh, ["*"])
    inv = _invite(owner)
    assert inv["accept_path"] == f"/invite/{inv['token']}"
    preview = b.get(f"/v1/invites/{inv['token']}").json()
    assert preview == {**preview, "account_owner_email": "owner@example.com", "role": "developer"}

    assert b.post(f"/v1/invites/{inv['token']}/accept").status_code == 200
    me = _me(b)
    assert me["user"]["email"] == "b@example.com"
    assert me["account"]["owner_email"] == "owner@example.com" and me["account"]["role"] == "developer"
    assert {a["personal"] for a in me["accounts"]} == {True, False}
    assert "team:manage" not in me["permissions"] and "endpoints:write" in me["permissions"]

    # B now sees and edits the owner's data.
    assert [e["id"] for e in b.get("/v1/endpoints").json()["data"]] == [ep["id"]]
    assert b.patch(f"/v1/endpoints/{ep['id']}", json={"description": "by b"}).status_code == 200

    # The invite link only works once.
    assert b.post(f"/v1/invites/{inv['token']}/accept").status_code == 404

    members = owner.get("/v1/team/members").json()["data"]
    assert [(m["email"], m["role"]) for m in members] == [("owner@example.com", "owner"),
                                                          ("b@example.com", "developer")]


def test_switching_back_to_the_personal_account(team):
    owner, oh, b = team
    _endpoint(owner, oh, ["*"])
    _join(owner, b)
    me = _me(b)
    personal = next(a for a in me["accounts"] if a["personal"])
    r = b.post("/v1/auth/switch-account", json={"account_id": personal["id"]})
    assert r.status_code == 200 and r.json()["account"]["personal"] is True
    assert b.get("/v1/endpoints").json()["data"] == []
    # Switch back into the team, and never into an account you're not part of.
    team_id = _me(owner)["user"]["id"]
    assert b.post("/v1/auth/switch-account", json={"account_id": team_id}).status_code == 200
    assert len(b.get("/v1/endpoints").json()["data"]) == 1
    assert b.post("/v1/auth/switch-account", json={"account_id": "usr_nope"}).status_code == 404
    assert owner.post("/v1/auth/switch-account", json={"account_id": personal["id"]}).status_code == 404


def test_invite_must_be_accepted_by_the_invited_email(team):
    owner, _, b = team
    token = _invite(owner, "someone-else@example.com")["token"]
    r = b.post(f"/v1/invites/{token}/accept")
    assert r.status_code == 403 and r.json()["error"]["code"] == "invite_wrong_user"


def test_viewer_is_read_only(team):
    owner, oh, b = team
    ep = _endpoint(owner, oh, ["*"])
    _join(owner, b, role="viewer")
    assert b.get("/v1/endpoints").status_code == 200
    assert b.get("/v1/events").status_code == 200
    for r in [
        b.post("/v1/endpoints", json={"url": URL, "event_types": ["*"]}),
        b.patch(f"/v1/endpoints/{ep['id']}", json={"enabled": False}),
        b.get(f"/v1/endpoints/{ep['id']}/secret"),
        b.post("/v1/events", json={"event_type": "a.b", "data": {}}),
        b.post("/v1/deliveries/replay", json={}),
        b.post("/v1/api-keys", json={"name": "x"}),
        b.post("/v1/team/invites", json={"email": "c@example.com"}),
    ]:
        assert r.status_code == 403, r.text
        assert r.json()["error"]["code"] == "forbidden"


def test_developer_cannot_manage_the_team_and_keys_are_capped_by_role(team):
    owner, _, b = team
    _join(owner, b, role="developer")
    assert b.post("/v1/team/invites", json={"email": "c@example.com"}).status_code == 403
    k = b.post("/v1/api-keys", json={"name": "dev key"})
    assert k.status_code == 201
    assert k.json()["api_key"]["created_by_user_id"] == _me(b)["user"]["id"]
    # The key belongs to the team account.
    assert any(x["id"] == k.json()["api_key"]["id"] for x in owner.get("/v1/api-keys").json()["data"])


def test_admins_manage_members_but_not_other_admins(team):
    from app.main import app

    owner, _, b = team
    _join(owner, b, role="admin")
    with TestClient(app) as c:
        make_user(c, "c@example.com")
        token = b.post("/v1/team/invites", json={"email": "c@example.com", "role": "viewer"}).json()["token"]
        assert c.post(f"/v1/invites/{token}/accept").status_code == 200
        c_id = _me(c)["user"]["id"]
    b_id = _me(b)["user"]["id"]
    owner_id = _me(owner)["user"]["id"]

    assert b.patch(f"/v1/team/members/{c_id}", json={"role": "developer"}).status_code == 200
    assert b.post("/v1/team/invites", json={"email": "d@example.com", "role": "admin"}).status_code == 403
    admin_invite = owner.post("/v1/team/invites", json={"email": "e@example.com", "role": "admin"}).json()
    assert b.delete(f"/v1/team/invites/{admin_invite['invite']['id']}").status_code == 403
    assert b.patch(f"/v1/team/members/{owner_id}", json={"role": "viewer"}).status_code == 409
    assert owner.patch(f"/v1/team/members/{b_id}", json={"role": "viewer"}).status_code == 200
    assert b.delete(f"/v1/team/members/{c_id}").status_code == 403  # b is a viewer now


def test_removed_member_falls_back_to_their_own_account(team):
    owner, oh, b = team
    _endpoint(owner, oh, ["*"])
    _join(owner, b)
    b_id = _me(b)["user"]["id"]
    assert owner.delete(f"/v1/team/members/{b_id}").status_code == 204
    me = _me(b)
    assert me["account"]["personal"] is True and len(me["accounts"]) == 1
    assert b.get("/v1/endpoints").json()["data"] == []


def test_member_can_leave(team):
    owner, _, b = team
    _join(owner, b, role="viewer")
    b_id = _me(b)["user"]["id"]
    assert b.delete(f"/v1/team/members/{b_id}").status_code == 204
    assert _me(b)["account"]["personal"] is True


def test_new_invite_replaces_the_old_link_and_can_be_revoked(team):
    owner, _, b = team
    first = _invite(owner)
    second = _invite(owner)
    assert b.post(f"/v1/invites/{first['token']}/accept").status_code == 404
    assert len(owner.get("/v1/team/invites").json()["data"]) == 1
    owner.delete(f"/v1/team/invites/{second['invite']['id']}")
    assert b.post(f"/v1/invites/{second['token']}/accept").status_code == 404


def test_cannot_invite_existing_members_or_the_owner(team):
    owner, _, b = team
    _join(owner, b)
    assert owner.post("/v1/team/invites", json={"email": "b@example.com"}).status_code == 409
    assert owner.post("/v1/team/invites", json={"email": "owner@example.com"}).status_code == 409


def test_audit_log_names_the_person_who_acted(team):
    owner, oh, b = team
    ep = _endpoint(owner, oh, ["*"])
    _join(owner, b)
    b.patch(f"/v1/endpoints/{ep['id']}", json={"description": "changed by b"})
    entries = owner.get("/v1/audit-logs", params={"action": "endpoint.updated"}).json()["data"]
    assert entries[0]["actor"]["email"] == "b@example.com"
    created = owner.get("/v1/audit-logs", params={"action": "endpoint.created"}).json()["data"]
    # Made with the owner's API key: the key's creator is named.
    assert created[0]["actor"]["type"] == "api_key" and created[0]["actor"]["email"] == "owner@example.com"
    with SessionLocal() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action == "team.member_joined")) is not None


def test_team_members_list_is_visible_to_members_only(team):
    from app.main import app

    owner, _, b = team
    _join(owner, b, role="viewer")
    assert len(b.get("/v1/team/members").json()["data"]) == 2
    with TestClient(app) as stranger:
        make_user(stranger, "stranger@example.com")
        # A stranger only sees their own account's members.
        data = stranger.get("/v1/team/members").json()["data"]
        assert [(m["email"], m["role"]) for m in data] == [("stranger@example.com", "owner")]
