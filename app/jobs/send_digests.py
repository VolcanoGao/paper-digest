"""Per-minute scheduler scan that fires daily digest emails.

For each active subscription, if "now in the user's tz" >= the subscription's
send_at_local AND we haven't already sent today (in user's tz), render and
send the email, then mark last_sent_on.

Idempotency: last_sent_on is the dedupe key; setting it under a real send AND
under "0 hits skip-but-mark" prevents duplicates.

Failure: if the mailer raises, last_sent_on is NOT updated, so the next minute
will retry. Persistent failures (Resend down, key invalid) log every minute --
acceptable for v1, would want backoff in v2.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import AsyncSessionLocal
from app.models import Config, Subscription, User
from app.services.mailer import MailerError, send_email
from app.services.query import query_today

log = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

# Separate env so autoescape rules can differ between web (HTML) and email (mixed).
_jinja = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
    enable_async=False,
)


def _render_email(
    *,
    today: str,
    config_name: str,
    hits,
    send_at_local: str,
    tz: str,
    unsubscribe_url: str,
    base_url: str,
) -> tuple[str, str]:
    ctx = dict(
        today=today,
        config_name=config_name,
        hits=hits,
        send_at_local=send_at_local,
        tz=tz,
        unsubscribe_url=unsubscribe_url,
        base_url=base_url,
    )
    html = _jinja.get_template("emails/digest.html").render(**ctx)
    text = _jinja.get_template("emails/digest.txt").render(**ctx)
    return html, text


async def _process_one(db, sub: Subscription, *, force: bool = False) -> dict:
    user: User = sub.user
    cfg: Config | None = sub.config
    if cfg is None:
        log.warning("sub %s: missing config, skipping", sub.id)
        return {"sub_id": str(sub.id), "status": "skipped_no_config"}

    try:
        tz = ZoneInfo(user.tz or "UTC")
    except Exception:
        log.warning("sub %s: bad tz %r, defaulting to UTC", sub.id, user.tz)
        tz = ZoneInfo("UTC")

    now_local = datetime.now(tz=tz)
    today_local = now_local.date()

    if not force:
        if sub.last_sent_on is not None and sub.last_sent_on >= today_local:
            return {"sub_id": str(sub.id), "status": "already_sent_today"}
        if now_local.time() < sub.send_at_local:
            return {"sub_id": str(sub.id), "status": "too_early"}

    hits = await query_today(db, cfg)

    if not hits:
        # No matching papers. Mark as sent so we don't retry every minute.
        sub.last_sent_on = today_local
        await db.commit()
        log.info("sub %s: no hits, marked sent", sub.id)
        return {"sub_id": str(sub.id), "status": "no_hits"}

    unsubscribe_url = f"{settings.base_url.rstrip('/')}/api/subscriptions/unsubscribe/{sub.unsubscribe_token}"
    html, text = _render_email(
        today=today_local.isoformat(),
        config_name=cfg.name,
        hits=hits,
        send_at_local=f"{sub.send_at_local.hour:02d}:{sub.send_at_local.minute:02d}",
        tz=user.tz or "UTC",
        unsubscribe_url=unsubscribe_url,
        base_url=settings.base_url.rstrip("/"),
    )
    subject = f"Paper Digest · {today_local.isoformat()} · {cfg.name} ({len(hits)} 篇)"

    try:
        result = send_email(user.email, subject, html, text)
    except MailerError as exc:
        log.error("sub %s: send failed: %s (will retry next minute)", sub.id, exc)
        return {"sub_id": str(sub.id), "status": "send_failed", "error": str(exc)}

    sub.last_sent_on = today_local
    await db.commit()
    log.info("sub %s: sent (%s hits) → %s", sub.id, len(hits), result.get("status", "ok"))
    return {"sub_id": str(sub.id), "status": "sent", "hits": len(hits)}


async def run_digest_sweep(*, force: bool = False) -> list[dict]:
    """Single sweep across all active subscriptions. Returns per-sub results."""
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(Subscription)
            .options(selectinload(Subscription.user), selectinload(Subscription.config))
            .where(Subscription.is_active.is_(True))
        )
        results = []
        for sub in rows:
            try:
                r = await _process_one(db, sub, force=force)
            except Exception as exc:
                log.exception("sub %s: unexpected error", sub.id)
                r = {"sub_id": str(sub.id), "status": "error", "error": str(exc)}
            results.append(r)
        return results
