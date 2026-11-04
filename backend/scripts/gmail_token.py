#!/usr/bin/env python3
"""One-time setup: let HookFlow send verification emails from your Gmail account.

Run it on your own computer (standard library only, no install needed):

    python3 backend/scripts/gmail_token.py

The OAuth client can be a "Desktop app", or a "Web application" with the authorized redirect URI
http://127.0.0.1:8765/ (exactly). It asks for the client ID and secret (see docs/operations.md#email), opens
Google's sign-in page, and prints the settings to paste into Render. Pass --test-to you@example.com to also send
a test email.

The refresh token it prints can send email as you, so treat it like a password: put it only in Render's
environment settings, never in git. You can revoke it any time at https://myaccount.google.com/permissions.
"""

import argparse
import base64
import getpass
import hashlib
import http.server
import json
import secrets
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from email.message import EmailMessage

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
SCOPE = "https://www.googleapis.com/auth/gmail.send"  # send only: it can't read your mail
PORT = 8765


def post(url: str, *, form: dict | None = None, body: dict | None = None, token: str | None = None) -> dict:
    if form is not None:
        data, ctype = urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded"
    else:
        data, ctype = json.dumps(body).encode(), "application/json"
    headers = {"Content-Type": ctype}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=20) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        text = e.read().decode()[:500]
        hint = ""
        if "redirect_uri_mismatch" in text:
            hint = f"\nFor a Web application client, add the redirect URI http://127.0.0.1:{PORT}/ exactly."
        sys.exit(f"\nGoogle said HTTP {e.code}: {text}{hint}")


def wait_for_code(state: str) -> str:
    """Run a tiny web server on localhost that receives Google's redirect with the authorization code."""
    result: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("state", [""])[0] != state:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"State mismatch. Close this tab and run the script again.")
                return
            result.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "Done. You can close this tab and go back to the terminal." if "code" in result else \
                f"Google returned an error: {result.get('error', 'unknown')}. Go back to the terminal."
            self.wfile.write(f"<p style='font:16px sans-serif'>{msg}</p>".encode())
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    server.serve_forever()
    if "code" not in result:
        sys.exit(f"\nSign-in failed: {result.get('error', 'no code received')}")
    return result["code"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--client-id")
    ap.add_argument("--client-secret")
    ap.add_argument("--test-to", help="send a test email to this address once set up")
    args = ap.parse_args()

    client_id = args.client_id or input("OAuth client ID: ").strip()
    client_secret = args.client_secret or getpass.getpass("OAuth client secret (hidden): ").strip()
    if not client_id or not client_secret:
        sys.exit("Both the client ID and the client secret are needed.")

    redirect_uri = f"http://127.0.0.1:{PORT}/"
    state = secrets.token_urlsafe(16)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",  # ask for a refresh token
        "prompt": "consent",       # always return one, even if you've signed in before
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })

    print("\nOpening Google sign-in in your browser. Sign in with the Gmail account that should send the codes.")
    print("If Google says the app isn't verified, click Advanced → Go to (unsafe): it's your own app.")
    print(f"For a Web application client, the redirect URI must be http://127.0.0.1:{PORT}/ exactly.")
    print(f"\nIf the browser doesn't open, visit:\n{url}\n")
    webbrowser.open(url)
    code = wait_for_code(state)

    tokens = post(TOKEN_URL, form={
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "code_verifier": verifier,
    })
    refresh = tokens.get("refresh_token")
    if not refresh:
        sys.exit("\nGoogle didn't return a refresh token. Remove the app at "
                 "https://myaccount.google.com/permissions and run the script again.")

    if args.test_to:
        msg = EmailMessage()
        msg["To"] = args.test_to
        msg["Subject"] = "HookFlow test email"
        msg.set_content("Gmail sending works. HookFlow can now email verification codes.\n")
        post(SEND_URL, body={"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()},
             token=tokens["access_token"])
        print(f"\nTest email sent to {args.test_to}.")

    print("\nSet these on the Render API service (Environment), then save:\n")
    print("MAIL_BACKEND=gmail")
    print("MAIL_FROM_EMAIL=<the Gmail address you just signed in with>")
    print(f"GMAIL_CLIENT_ID={client_id}")
    print("GMAIL_CLIENT_SECRET=<the client secret you entered>")
    print(f"GMAIL_REFRESH_TOKEN={refresh}")
    print("\nKeep the refresh token private: it can send email as you.")


if __name__ == "__main__":
    main()
