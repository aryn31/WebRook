"""Email content. Each template returns (subject, plain text, HTML).

The HTML matches the website's dark theme. It uses tables and inline styles only, because email clients (Gmail,
Outlook, Apple Mail) ignore most CSS. Web fonts load in Apple Mail and iOS Mail; elsewhere they fall back to
Georgia and system fonts. Every email also has a plain-text version.
"""

from html import escape

# The website's dark theme (frontend/app/globals.css).
BG = "#0c0c0b"
SURFACE = "#141412"
SURFACE_2 = "#1c1c19"
BORDER = "#272622"
TEXT = "#f2f0e9"
TEXT_2 = "#bab7ac"
MUTED = "#8a877d"
SIGNAL = "#d4ff3a"
SIGNAL_INK = "#141413"

SANS = "'Geist', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
SERIF = "'Instrument Serif', 'Iowan Old Style', Georgia, 'Times New Roman', serif"
MONO = "'Geist Mono', 'SFMono-Regular', Menlo, Consolas, 'Liberation Mono', monospace"
FONTS_URL = ("https://fonts.googleapis.com/css2?family=Geist:wght@400;600"
             "&family=Geist+Mono:wght@500&family=Instrument+Serif:ital@0;1&display=swap")


def _layout(*, preheader: str, body: str, app_url: str) -> str:
    """The shared frame: logo, card, footer."""
    site = escape(app_url.removeprefix("https://").removeprefix("http://").rstrip("/"))
    url = escape(app_url)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<meta name="supported-color-schemes" content="dark">
<title>HookFlow</title>
<link href="{FONTS_URL}" rel="stylesheet">
<style>
  :root {{ color-scheme: dark; supported-color-schemes: dark; }}
  body {{ background-color: {BG}; }}
  a {{ color: {SIGNAL}; }}
</style>
</head>
<body style="margin:0;padding:0;background:{BG};color:{TEXT};-webkit-text-size-adjust:100%;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:{BG};">{escape(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{BG}" style="background:{BG};">
  <tr>
    <td align="center" style="padding:44px 16px 40px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:520px;">
        <tr>
          <td style="padding:0 4px 22px;">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td width="26" height="26" bgcolor="{TEXT}" style="width:26px;height:26px;background:{TEXT};border-radius:7px;text-align:center;vertical-align:middle;line-height:0;">
                  <span style="display:inline-block;width:10px;height:10px;background:{SIGNAL};border:2px solid {BG};border-radius:50%;"></span>
                </td>
                <td style="padding-left:10px;font-family:{SANS};font-size:17px;font-weight:600;color:{TEXT};letter-spacing:-0.01em;">HookFlow</td>
              </tr>
            </table>
          </td>
        </tr>
        <tr>
          <td bgcolor="{SURFACE}" style="background:{SURFACE};border:1px solid {BORDER};border-radius:16px;padding:36px 32px 32px;font-family:{SANS};color:{TEXT};">
{body}
          </td>
        </tr>
        <tr>
          <td style="padding:24px 8px 0;font-family:{SANS};font-size:12px;line-height:19px;color:{MUTED};text-align:center;">
            <span style="font-family:{SERIF};font-size:15px;color:{TEXT_2};">Send the event once. <em style="color:{SIGNAL};">We make sure it arrives.</em></span><br>
            <a href="{url}" style="color:{MUTED};text-decoration:underline;">{site}</a>
            &nbsp;·&nbsp;
            <a href="{url}/privacy" style="color:{MUTED};text-decoration:underline;">Privacy</a>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
</body>
</html>"""


def verification_code(*, code: str, email: str, minutes: int, app_url: str) -> tuple[str, str, str]:
    # The code stays out of the subject and preview text, so it isn't shown in notifications or on a lock screen.
    subject = "Confirm your email for HookFlow"
    verify_url = f"{app_url.rstrip('/')}/verify-email"

    text = f"""Confirm your email address

Use this code to finish creating your HookFlow account for {email}:

    {code}

The code expires in {minutes} minutes and can only be used once.
Enter it here: {verify_url}

Didn't sign up?
You can safely ignore this email. Nobody can use the account without this code.
Never share this code with anyone. HookFlow will never ask you for it.

HookFlow: send the event once, we make sure it arrives.
{app_url}
"""

    body = f"""            <p style="margin:0 0 14px;font-family:{MONO};font-size:11px;line-height:16px;letter-spacing:0.14em;text-transform:uppercase;color:{MUTED};">Email verification</p>
            <h1 style="margin:0 0 14px;font-family:{SERIF};font-size:38px;line-height:40px;font-weight:400;color:{TEXT};letter-spacing:-0.01em;">Confirm your <em style="color:{SIGNAL};">email.</em></h1>
            <p style="margin:0 0 26px;font-size:15px;line-height:24px;color:{TEXT_2};">
              Use this code to finish creating your HookFlow account for <strong style="color:{TEXT};font-weight:600;">{escape(email)}</strong>.
            </p>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td align="center" bgcolor="{SURFACE_2}" style="background:{SURFACE_2};border:1px solid {BORDER};border-radius:12px;padding:22px 12px;">
                  <span style="font-family:{MONO};font-size:34px;line-height:40px;font-weight:500;letter-spacing:10px;padding-left:10px;color:{SIGNAL};">{escape(code)}</span>
                </td>
              </tr>
            </table>
            <p style="margin:14px 0 28px;font-family:{MONO};font-size:12px;line-height:18px;color:{MUTED};text-align:center;">
              Expires in {minutes} minutes · single use
            </p>
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center">
              <tr>
                <td align="center" bgcolor="{TEXT}" style="background:{TEXT};border-radius:999px;">
                  <a href="{escape(verify_url)}" style="display:inline-block;padding:12px 26px;font-family:{SANS};font-size:14px;font-weight:600;color:{BG};text-decoration:none;">Enter code in HookFlow &rarr;</a>
                </td>
              </tr>
            </table>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:32px;">
              <tr><td style="border-top:1px solid {BORDER};font-size:0;line-height:0;">&nbsp;</td></tr>
            </table>
            <p style="margin:20px 0 6px;font-size:13px;line-height:20px;font-weight:600;color:{TEXT};">Didn&#39;t sign up?</p>
            <p style="margin:0;font-size:13px;line-height:20px;color:{MUTED};">
              You can safely ignore this email. Nobody can use the account without this code.
              Never share it with anyone. HookFlow will never ask you for it.
            </p>"""

    html = _layout(preheader=f"Your code expires in {minutes} minutes.", body=body, app_url=app_url)
    return subject, text, html
