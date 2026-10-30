"""Tiny webhook receiver for local testing.

Prints each request and checks its signature when RECEIVER_SECRET is set.
Control the response with the URL path:
  /hooks            -> 200
  /status/503       -> 503 (any status code)
  /slow/15          -> waits 15 seconds, then 200 (to test timeouts)
"""

import hashlib
import hmac
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SECRET = os.environ.get("RECEIVER_SECRET", "")


def verify(body: bytes, ts: str, header: str) -> str:
    if not SECRET:
        return "not checked (set RECEIVER_SECRET)"
    if abs(time.time() - int(ts or 0)) > 300:
        return "INVALID (timestamp too old)"
    expected = "v1=" + hmac.new(SECRET.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    ok = any(hmac.compare_digest(expected, p.strip()) for p in header.split(","))
    return "valid" if ok else "INVALID"


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("content-length") or 0))
        parts = self.path.strip("/").split("/")
        status = 200
        if parts[0] == "status" and len(parts) > 1 and parts[1].isdigit():
            status = int(parts[1])
        if parts[0] == "slow" and len(parts) > 1 and parts[1].isdigit():
            time.sleep(int(parts[1]))
        sig = verify(body, self.headers.get("HookFlow-Timestamp", ""), self.headers.get("HookFlow-Signature", ""))
        try:
            pretty = json.dumps(json.loads(body), indent=2)
        except ValueError:
            pretty = body.decode(errors="replace")
        print(
            f"\n--> {self.path}  event={self.headers.get('HookFlow-Event-Id')} "
            f"type={self.headers.get('HookFlow-Event-Type')} attempt={self.headers.get('HookFlow-Attempt')} "
            f"signature={sig}  responding {status}\n{pretty}",
            flush=True,
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"received": status < 300}).encode())

    def log_message(self, *args) -> None:
        pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "9000"))
    print(f"Receiver listening on :{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
