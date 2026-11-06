"""The website's contact form. Messages are emailed to SUPPORT_EMAIL with Reply-To set to the sender."""

import logging

from fastapi import APIRouter, Request

from app import email_templates, mailer, ratelimit
from app.clientip import client_ip
from app.config import get_settings
from app.errors import ApiError
from app.schemas import ContactIn, ContactOut
from app.security import sha256_hex

router = APIRouter(prefix="/v1", tags=["contact"])
log = logging.getLogger("hookflow.contact")

THANKS = "Thanks, your message was sent. We'll reply to the email you gave, usually within a day or two."
PER_HOUR = 5


@router.post("/contact", status_code=202, response_model=ContactOut)
def contact(body: ContactIn, request: Request) -> dict:
    """Send a message to the HookFlow team. No account needed."""
    if body.website:
        log.info("contact form: dropped a message with the hidden field filled in")
        return {"message": THANKS}  # look successful, so bots learn nothing
    ip = client_ip(request)
    ratelimit.enforce(f"contact:ip:{ip}", PER_HOUR, window_seconds=3600)
    ratelimit.enforce(f"contact:email:{sha256_hex(body.email.lower())}", PER_HOUR, window_seconds=3600)
    s = get_settings()
    subject, text, html = email_templates.contact_message(
        name=body.name.strip(), email=body.email, topic=body.topic, message=body.message.strip(), ip=ip,
        app_url=s.app_url.rstrip("/"),
    )
    try:
        mailer.send(s.support_email, subject, text, html, reply_to=body.email)
    except mailer.MailError:
        raise ApiError(503, f"We couldn't send your message right now. Please email {s.support_email} directly.",
                       code="email_failed", details={"support_email": s.support_email}) from None
    return {"message": THANKS}
