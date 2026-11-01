import time

import pytest

from app import signing
from app.config import get_settings
from app.ids import new_id
from app.security import new_api_key, parse_api_key_prefix
from app.urlguard import UnsafeDestination, check_destination, validate_url_format
from app.worker.retry import is_retryable_status, retry_delay_seconds


def test_signature_roundtrip_and_tamper():
    body = b'{"id":"evt_1","data":{"a":1}}'
    sig = signing.sign("whsec_abc", 1700000000, body)
    assert sig.startswith("v1=")
    assert signing.verify("whsec_abc", 1700000000, body, sig)
    assert not signing.verify("whsec_abc", 1700000000, body + b" ", sig)
    assert not signing.verify("whsec_abc", 1700000001, body, sig)
    assert not signing.verify("whsec_other", 1700000000, body, sig)


def test_signature_matches_documented_algorithm():
    import hashlib
    import hmac

    body, ts, secret = b"{}", 1793361600, "whsec_x"
    expected = hmac.new(secret.encode(), b"1793361600.{}", hashlib.sha256).hexdigest()
    assert signing.sign(secret, ts, body) == f"v1={expected}"


@pytest.mark.parametrize("status,retryable", [(500, True), (503, True), (429, True), (408, True),
                                              (400, False), (404, False), (410, False), (422, False)])
def test_retryable_statuses(status, retryable):
    assert is_retryable_status(status) is retryable


def test_retry_delay_grows_with_jitter_and_cap():
    base = get_settings().retry_base_delay_seconds
    for attempt, factor in [(1, 1), (2, 4), (3, 16), (4, 64)]:
        d = retry_delay_seconds(attempt)
        assert base * factor * 0.75 <= d <= base * factor * 1.25
    assert retry_delay_seconds(50) <= get_settings().retry_max_delay_seconds * 1.25


def test_retry_after_header_is_honoured():
    assert retry_delay_seconds(1, "600") >= 600


def test_ids_are_prefixed_and_time_sortable():
    a = new_id("evt")
    time.sleep(0.002)
    b = new_id("evt")
    assert a.startswith("evt_") and len(a) == 30
    assert a < b


def test_api_key_format():
    key, prefix, key_hash = new_api_key()
    assert parse_api_key_prefix(key) == prefix
    assert key_hash not in key and len(key_hash) == 64
    assert parse_api_key_prefix("not-a-key") is None


@pytest.mark.parametrize("url", ["ftp://example.com", "example.com/hook", "https://user:pw@example.com/"])
def test_url_format_rejects_bad_urls(url):
    with pytest.raises(ValueError):
        validate_url_format(url)


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1/", "http://10.0.0.5/", "http://169.254.169.254/latest", "http://[::1]/", "http://localhost/",
     "http://192.168.1.1/", "http://[::ffff:127.0.0.1]/"],
)
def test_private_destinations_blocked(monkeypatch, url):
    monkeypatch.setattr(get_settings(), "block_private_destinations", True)
    with pytest.raises(ValueError):
        validate_url_format(url)


def test_dns_resolving_to_private_ip_blocked(monkeypatch):
    monkeypatch.setattr(get_settings(), "block_private_destinations", True)
    monkeypatch.setattr("socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("10.1.2.3", 443))])
    with pytest.raises(UnsafeDestination):
        check_destination("https://sneaky.example.com/hook")


def test_dns_resolving_to_public_ip_allowed(monkeypatch):
    monkeypatch.setattr(get_settings(), "block_private_destinations", True)
    monkeypatch.setattr("socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])
    check_destination("https://example.com/hook")


def test_plain_postgres_urls_get_the_psycopg_driver():
    from app.config import Settings

    for given in ("postgres://u:p@h:5432/db", "postgresql://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"):
        s = Settings(database_url=given, secret_encryption_key="x")
        assert s.database_url == "postgresql+psycopg://u:p@h:5432/db"
