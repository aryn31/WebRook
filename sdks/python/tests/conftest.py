"""Test helpers: a local http.server stub standing in for the HookFlow API, and a copy of the backend signer."""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
UTC = timezone.utc
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_SIGNING = REPO_ROOT / "backend" / "app" / "signing.py"
API_DOCS = REPO_ROOT / "docs" / "api.md"


# --- Exactly backend/app/signing.py::sign and worker/engine.py::build_body ---------------------------

def backend_sign(secret: str, timestamp: int, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"v1={mac.hexdigest()}"


def build_body(event_id: str, event_type: str, created_at: datetime, data: dict) -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "type": event_type,
            "created_at": created_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "data": data,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()


# --- API stub ----------------------------------------------------------------------------------------

@dataclass
class Recorded:
    method: str
    path: str
    query: dict[str, list[str]]
    headers: dict[str, str]
    body: bytes

    @property
    def json(self) -> Any:
        return json.loads(self.body) if self.body else None


Reply = tuple[int, Any] | tuple[int, Any, dict[str, str]]


@dataclass
class Stub:
    base_url: str = ""
    requests: list[Recorded] = field(default_factory=list)
    handler: Callable[[Recorded], Reply] = lambda req: (200, {})
    queue: list[Reply] = field(default_factory=list)

    def reply(self, *replies: Reply) -> None:
        """Answer the next requests with these replies, in order (then fall back to ``handler``)."""
        self.queue.extend(replies)

    @property
    def last(self) -> Recorded:
        return self.requests[-1]


@pytest.fixture
def stub():
    state = Stub()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep test output quiet
            pass

        def _handle(self):
            parsed = urllib.parse.urlsplit(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            rec = Recorded(
                method=self.command,
                path=parsed.path,
                query=urllib.parse.parse_qs(parsed.query),
                headers={k.lower(): v for k, v in self.headers.items()},
                body=self.rfile.read(length) if length else b"",
            )
            state.requests.append(rec)
            reply = state.queue.pop(0) if state.queue else state.handler(rec)
            status, payload = reply[0], reply[1]
            headers = reply[2] if len(reply) > 2 else {}
            raw = b"" if payload is None else (payload if isinstance(payload, bytes) else json.dumps(payload).encode())
            self.send_response(status)
            if payload is not None and not isinstance(payload, bytes):
                self.send_header("Content-Type", "application/json")
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        do_GET = do_POST = do_PATCH = do_DELETE = _handle

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    state.base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()


def error_body(code: str, message: str, details: Any = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}
