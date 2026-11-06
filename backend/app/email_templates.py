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


def _code_email(*, label: str, heading: str, accent: str, intro_text: str, intro_html: str, code: str,
                minutes: int, button: str, button_url: str, ignore_title: str, ignore_text: str,
                app_url: str) -> tuple[str, str]:
    """Plain text and HTML for an email whose main content is a one-time code."""
    text = f"""{heading} {accent}

{intro_text}

    {code}

The code expires in {minutes} minutes and can only be used once.
Enter it here: {button_url}

{ignore_title}
{ignore_text}
Never share this code with anyone. HookFlow will never ask you for it.

HookFlow: send the event once, we make sure it arrives.
{app_url}
"""

    body = f"""            <p style="margin:0 0 14px;font-family:{MONO};font-size:11px;line-height:16px;letter-spacing:0.14em;text-transform:uppercase;color:{MUTED};">{escape(label)}</p>
            <h1 style="margin:0 0 14px;font-family:{SERIF};font-size:38px;line-height:40px;font-weight:400;color:{TEXT};letter-spacing:-0.01em;">{escape(heading)} <em style="color:{SIGNAL};">{escape(accent)}</em></h1>
            <p style="margin:0 0 26px;font-size:15px;line-height:24px;color:{TEXT_2};">
              {intro_html}
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
                  <a href="{escape(button_url)}" style="display:inline-block;padding:12px 26px;font-family:{SANS};font-size:14px;font-weight:600;color:{BG};text-decoration:none;">{escape(button)} &rarr;</a>
                </td>
              </tr>
            </table>
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-top:32px;">
              <tr><td style="border-top:1px solid {BORDER};font-size:0;line-height:0;">&nbsp;</td></tr>
            </table>
            <p style="margin:20px 0 6px;font-size:13px;line-height:20px;font-weight:600;color:{TEXT};">{escape(ignore_title)}</p>
            <p style="margin:0;font-size:13px;line-height:20px;color:{MUTED};">
              {escape(ignore_text)}
              Never share it with anyone. HookFlow will never ask you for it.
            </p>"""

    html = _layout(preheader=f"Your code expires in {minutes} minutes.", body=body, app_url=app_url)
    return text, html


# Codes stay out of subjects and preview text, so they aren't shown in notifications or on a lock screen.

def verification_code(*, code: str, email: str, minutes: int, app_url: str) -> tuple[str, str, str]:
    subject = "Confirm your email for HookFlow"
    strong = f'<strong style="color:{TEXT};font-weight:600;">{escape(email)}</strong>'
    text, html = _code_email(
        label="Email verification",
        heading="Confirm your",
        accent="email.",
        intro_text=f"Use this code to finish creating your HookFlow account for {email}:",
        intro_html=f"Use this code to finish creating your HookFlow account for {strong}.",
        code=code,
        minutes=minutes,
        button="Enter code in HookFlow",
        button_url=f"{app_url.rstrip('/')}/verify-email",
        ignore_title="Didn't sign up?",
        ignore_text="You can safely ignore this email. Nobody can use the account without this code.",
        app_url=app_url,
    )
    return subject, text, html


def password_reset_code(*, code: str, email: str, minutes: int, app_url: str) -> tuple[str, str, str]:
    subject = "Reset your HookFlow password"
    strong = f'<strong style="color:{TEXT};font-weight:600;">{escape(email)}</strong>'
    text, html = _code_email(
        label="Password reset",
        heading="Reset your",
        accent="password.",
        intro_text=f"Someone asked to reset the password for the HookFlow account {email}. "
                   "If it was you, use this code to choose a new one:",
        intro_html=f"Someone asked to reset the password for the HookFlow account {strong}. "
                   "If it was you, use this code to choose a new one.",
        code=code,
        minutes=minutes,
        button="Reset password",
        button_url=f"{app_url.rstrip('/')}/forgot-password",
        ignore_title="Didn't ask for this?",
        ignore_text="You can safely ignore this email. Your password stays the same, and nobody can change it "
                    "without this code.",
        app_url=app_url,
    )
    return subject, text, html


# --- Endpoint alerts -------------------------------------------------------------

def _duration(seconds: float) -> str:
    m = int(seconds // 60)
    if m < 1:
        return "under a minute"
    if m < 60:
        return f"{m} minute{'s' if m != 1 else ''}"
    h, m = divmod(m, 60)
    if h < 48:
        return f"{h} hour{'s' if h != 1 else ''}" + (f" {m} min" if m else "")
    d = h // 24
    return f"{d} days"


def _facts(rows: list[tuple[str, str]]) -> str:
    cells = "".join(
        f"""<tr>
                <td style="padding:9px 0;border-top:1px solid {BORDER};font-size:13px;color:{MUTED};width:38%;vertical-align:top;">{escape(k)}</td>
                <td style="padding:9px 0;border-top:1px solid {BORDER};font-size:13px;color:{TEXT};font-family:{MONO};word-break:break-all;">{escape(v)}</td>
              </tr>"""
        for k, v in rows
    )
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 26px;">{cells}</table>'


def _alert_email(*, label: str, tone: str, heading: str, accent: str, intro: str, facts: list[tuple[str, str]],
                 button: str, link: str, footnote: str, app_url: str, preheader: str) -> tuple[str, str]:
    text = "\n".join([
        f"{heading} {accent}", "", intro, "",
        *[f"{k}: {v}" for k, v in facts], "",
        f"{button}: {link}", "", footnote,
        f"Turn these emails off: {app_url}/security", "",
        "HookFlow: send the event once, we make sure it arrives.", app_url, "",
    ])
    body = f"""            <p style="margin:0 0 14px;font-family:{MONO};font-size:11px;line-height:16px;letter-spacing:0.14em;text-transform:uppercase;color:{tone};">&#9679;&nbsp; {escape(label)}</p>
            <h1 style="margin:0 0 14px;font-family:{SERIF};font-size:36px;line-height:40px;font-weight:400;color:{TEXT};letter-spacing:-0.01em;">{escape(heading)} <em style="color:{tone};">{escape(accent)}</em></h1>
            <p style="margin:0 0 22px;font-size:15px;line-height:24px;color:{TEXT_2};">{escape(intro)}</p>
            {_facts(facts)}
            <table role="presentation" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td align="center" bgcolor="{TEXT}" style="background:{TEXT};border-radius:999px;">
                  <a href="{escape(link)}" style="display:inline-block;padding:12px 26px;font-family:{SANS};font-size:14px;font-weight:600;color:{BG};text-decoration:none;">{escape(button)} &rarr;</a>
                </td>
              </tr>
            </table>
            <p style="margin:26px 0 0;font-size:13px;line-height:20px;color:{MUTED};">
              {escape(footnote)}
              <a href="{escape(app_url)}/security" style="color:{MUTED};">Turn these emails off</a>.
            </p>"""
    return text, _layout(preheader=preheader, body=body, app_url=app_url)


FAILED = "#ff6b5b"
OK = "#4ade80"


def endpoint_failing(*, name: str, url: str, failures: int, failing_since, status_code: int | None,
                     error: str | None, endpoint_link: str, app_url: str) -> tuple[str, str, str]:
    subject = f"Alert: {name} is failing"
    problem = error or (f"Destination returned HTTP {status_code}." if status_code else "Requests are failing.")
    facts = [("Endpoint", url), ("Failed in a row", str(failures)), ("Last error", problem)]
    if failing_since is not None:
        facts.insert(2, ("Failing since", failing_since.strftime("%d %b %Y, %H:%M UTC")))
    text, html = _alert_email(
        label="Endpoint alert", tone=FAILED, heading=name, accent="is failing.",
        intro=f"The last {failures} attempts to deliver to this endpoint failed. HookFlow keeps retrying as "
              "usual; deliveries that run out of attempts can be replayed once it's fixed.",
        facts=facts, button="Open endpoint", link=endpoint_link,
        footnote="You'll get one more email when it's working again. Nothing else is sent while it stays down.",
        app_url=app_url, preheader=f"{failures} failed attempts in a row. {problem}",
    )
    return subject, text, html


def endpoint_recovered(*, name: str, url: str, down_for, failed_deliveries: int, endpoint_link: str,
                       app_url: str) -> tuple[str, str, str]:
    subject = f"Resolved: {name} is working again"
    facts = [("Endpoint", url)]
    if down_for is not None:
        facts.append(("Down for", _duration(down_for.total_seconds())))
    facts.append(("Deliveries that failed", str(failed_deliveries)))
    intro = "The latest delivery to this endpoint succeeded, so it's accepting events again."
    if failed_deliveries:
        intro += f" {failed_deliveries} deliver{'y' if failed_deliveries == 1 else 'ies'} ran out of attempts " \
                 "while it was down. Replay them from the endpoint's page so nothing is lost."
    text, html = _alert_email(
        label="Resolved", tone=OK, heading=name, accent="is back.", intro=intro, facts=facts,
        button="Replay failed deliveries" if failed_deliveries else "Open endpoint", link=endpoint_link,
        footnote="You'll be emailed again if it starts failing.", app_url=app_url,
        preheader="Deliveries are succeeding again.",
    )
    return subject, text, html


# --- Contact form ------------------------------------------------------------------

TOPIC_LABEL = {"question": "General question", "support": "Help with my account", "sales": "Pricing or sales",
               "bug": "Bug report", "other": "Other"}


def contact_message(*, name: str, email: str, topic: str, message: str, ip: str, app_url: str) -> tuple[str, str, str]:
    """Sent to the support inbox. Reply-To is the sender, so replying answers them directly."""
    label = TOPIC_LABEL.get(topic, topic)
    subject = f"[Contact] {label} from {name}"
    text = f"""New message from the HookFlow contact form. Reply to this email to answer {name}.

Name: {name}
Email: {email}
Topic: {label}
IP: {ip}

{message}
"""
    paragraphs = "".join(
        f'<p style="margin:0 0 12px;">{escape(p)}</p>' for p in message.replace("\r\n", "\n").split("\n") if p.strip()
    )
    body = f"""            <p style="margin:0 0 14px;font-family:{MONO};font-size:11px;line-height:16px;letter-spacing:0.14em;text-transform:uppercase;color:{SIGNAL};">&#9679;&nbsp; Contact form</p>
            <h1 style="margin:0 0 14px;font-family:{SERIF};font-size:34px;line-height:38px;font-weight:400;color:{TEXT};">{escape(label)} <em style="color:{SIGNAL};">from {escape(name)}.</em></h1>
            <p style="margin:0 0 20px;font-size:14px;line-height:22px;color:{TEXT_2};">Reply to this email to answer them directly.</p>
            {_facts([("Name", name), ("Email", email), ("Topic", label), ("IP", ip)])}
            <div style="padding:18px 20px;border-radius:12px;background:{SURFACE_2};border:1px solid {BORDER};font-size:14px;line-height:22px;color:{TEXT};">
              {paragraphs}
            </div>"""
    return subject, text, _layout(preheader=message[:120], body=body, app_url=app_url)
