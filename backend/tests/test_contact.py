"""The website's contact form."""

from app import mailer

GOOD = {"name": "Ana Kim", "email": "ana@example.com", "topic": "sales",
        "message": "Hi! Do you offer a plan for 2 million events a month?"}


def test_sends_to_support_with_reply_to(client, mail):
    r = client.post("/v1/contact", json=GOOD)
    assert r.status_code == 202 and "Thanks" in r.json()["message"]
    [m] = mail
    assert m["to"] == "wendfolk02@gmail.com"
    assert m["reply_to"] == "ana@example.com"
    assert m["subject"] == "[Contact] Pricing or sales from Ana Kim"
    assert "2 million events" in m["text"] and "2 million events" in m["html"]


def test_no_login_needed_and_html_is_escaped(client, mail):
    r = client.post("/v1/contact", json=GOOD | {"name": "<b>x</b>", "message": "<script>alert(1)</script> hello there"})
    assert r.status_code == 202
    assert "<script>" not in mail[-1]["html"] and "&lt;script&gt;" in mail[-1]["html"]


def test_validation(client, mail):
    assert client.post("/v1/contact", json=GOOD | {"email": "nope"}).status_code == 422
    assert client.post("/v1/contact", json=GOOD | {"message": "short"}).status_code == 422
    assert client.post("/v1/contact", json=GOOD | {"topic": "spam"}).status_code == 422
    assert mail == []


def test_hidden_field_drops_bots_quietly(client, mail):
    r = client.post("/v1/contact", json=GOOD | {"website": "http://spam.example"})
    assert r.status_code == 202  # looks fine to the bot
    assert mail == []


def test_rate_limited(client, mail):
    for _ in range(5):
        assert client.post("/v1/contact", json=GOOD).status_code == 202
    r = client.post("/v1/contact", json=GOOD)
    assert r.status_code == 429
    assert len(mail) == 5


def test_mail_failure_points_to_the_address(client, monkeypatch):
    def broken(*a, **k):
        raise mailer.MailError("down")
    monkeypatch.setattr("app.mailer.send", broken)
    r = client.post("/v1/contact", json=GOOD)
    assert r.status_code == 503
    assert "wendfolk02@gmail.com" in r.json()["error"]["message"]
