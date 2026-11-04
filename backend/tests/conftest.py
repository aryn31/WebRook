"""Test setup. Needs Postgres and Redis (run via `docker compose run --rm api pytest`).

Uses a separate ``<db>_test`` database and Redis DB 15, so it never touches dev data.
"""

import os

from cryptography.fernet import Fernet

_base_db = os.environ.get("DATABASE_URL", "postgresql+psycopg://hookflow:hookflow@localhost:5433/hookflow")
os.environ["DATABASE_URL"] = _base_db.rsplit("/", 1)[0] + "/hookflow_test"
_base_redis = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
os.environ["REDIS_URL"] = _base_redis.rsplit("/", 1)[0] + "/15"
os.environ.setdefault("SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ["BLOCK_PRIVATE_DESTINATIONS"] = "false"
os.environ["AUTH_RATE_LIMIT_PER_MINUTE"] = "1000"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app import models  # noqa: E402,F401
from app.db import Base, engine  # noqa: E402
from app.ratelimit import get_redis  # noqa: E402


def _ensure_database() -> None:
    admin_url = _base_db.rsplit("/", 1)[0] + "/postgres"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        if not conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = 'hookflow_test'")):
            conn.execute(text("CREATE DATABASE hookflow_test"))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def _schema():
    _ensure_database()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean():
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} CASCADE"))
    get_redis().flushdb()
    yield


@pytest.fixture(autouse=True)
def queued(monkeypatch) -> list[str]:
    """Capture queue publishes (from the outbox) instead of sending them to Redis."""
    sent: list[str] = []
    monkeypatch.setattr("app.queue.send_delivery", sent.append)
    return sent


SENT_MAIL: list[dict] = []


@pytest.fixture(autouse=True)
def mail(monkeypatch) -> list[dict]:
    """Capture emails instead of sending them. Each is {"to", "subject", "text"}."""
    SENT_MAIL.clear()
    monkeypatch.setattr("app.mailer.send", lambda to, subject, text, html=None: SENT_MAIL.append(
        {"to": to, "subject": subject, "text": text, "html": html}))
    return SENT_MAIL


def last_code(email: str) -> str:
    import re

    msg = next(m for m in reversed(SENT_MAIL) if m["to"] == email.lower())
    return re.search(r"\b(\d{6})\b", msg["text"]).group(1)


def verify(client: TestClient, email: str = "a@example.com") -> None:
    r = client.post("/v1/auth/verify-email", json={"code": last_code(email)})
    assert r.status_code == 200, r.text


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


def make_user(client: TestClient, email: str = "a@example.com") -> TestClient:
    r = client.post("/v1/auth/register", json={"email": email, "password": "correct-horse-battery"})
    assert r.status_code == 201, r.text
    verify(client, email)
    return client


def make_api_key(client: TestClient) -> str:
    r = client.post("/v1/api-keys", json={"name": "test"})
    assert r.status_code == 201, r.text
    return r.json()["key"]


@pytest.fixture
def user_a():
    """(TestClient logged in as user A, API key headers for user A)."""
    from app.main import app

    with TestClient(app) as c:
        make_user(c, "a@example.com")
        yield c, {"Authorization": f"Bearer {make_api_key(c)}"}


@pytest.fixture
def user_b():
    from app.main import app

    with TestClient(app) as c:
        make_user(c, "b@example.com")
        yield c, {"Authorization": f"Bearer {make_api_key(c)}"}
