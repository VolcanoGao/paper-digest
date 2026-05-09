"""Email sender. Uses Resend's HTTP API; falls back to logging when
RESEND_API_KEY is unset (dev mode).

Resend free tier: 3000/mo, 100/day. Without a verified domain you can only
deliver to the email you registered with — fine for single-user dev, blocking
for multi-user prod. Set up domain verification before opening signup.
"""
from __future__ import annotations

import json
import logging
from typing import Sequence

import httpx

from app.config import settings

log = logging.getLogger(__name__)

RESEND_URL = "https://api.resend.com/emails"


class MailerError(Exception):
    """Send failed. Caller should not mark the subscription as sent."""


def send_email(
    to: str | Sequence[str],
    subject: str,
    html: str,
    text: str,
    *,
    reply_to: str | None = None,
    headers: dict[str, str] | None = None,
) -> dict:
    recipients = [to] if isinstance(to, str) else list(to)

    if not settings.resend_api_key:
        log.warning(
            "RESEND_API_KEY not set — logging email instead of sending (dev mode).\n"
            "  to=%s\n  subject=%s\n  text(first 400):\n%s",
            recipients, subject, text[:400],
        )
        return {"status": "logged", "to": recipients}

    payload = {
        "from": settings.mail_from,
        "to": recipients,
        "subject": subject,
        "html": html,
        "text": text,
    }
    if reply_to:
        payload["reply_to"] = reply_to
    if headers:
        payload["headers"] = headers

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                RESEND_URL,
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "Content-Type": "application/json",
                },
                content=json.dumps(payload),
            )
    except httpx.HTTPError as exc:
        raise MailerError(f"network error: {exc}") from exc

    if resp.status_code >= 400:
        raise MailerError(
            f"resend api {resp.status_code}: {resp.text[:300]}"
        )
    return resp.json()
