from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse

from app.auth import auth_backend, fastapi_users
from app.config import ARXIV_CATEGORIES, PLATFORM_KEYWORDS, settings
from app.jobs.scheduler import start_scheduler, stop_scheduler
from app.pipeline.platform_run import run_platform_pipeline
from app.routers import configs as configs_router
from app.routers import pages as pages_router
from app.routers import subscriptions as subs_router
from app.schemas import UserCreate, UserRead, UserUpdate

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("app")


def _check_prod_invariants() -> None:
    """Refuse to start in prod with placeholder secrets. Catching this at boot
    is much cheaper than discovering it via a security incident later."""
    if settings.app_env != "prod":
        return
    problems = []
    if not settings.secret_key or settings.secret_key in {"change-me", "change-me-to-a-random-string"}:
        problems.append("SECRET_KEY is empty or placeholder")
    if not settings.fernet_key:
        problems.append("FERNET_KEY is empty (would generate a transient key — encrypted data wouldn't survive restarts)")
    if not settings.deepseek_api_key:
        problems.append("DEEPSEEK_API_KEY is empty (platform pipeline would fail)")
    if not settings.base_url or settings.base_url.startswith("http://127.0.0.1"):
        problems.append("BASE_URL still points at localhost; emails would have broken unsubscribe links")
    if problems:
        msg = "Refusing to start in prod with bad config:\n  - " + "\n  - ".join(problems)
        raise RuntimeError(msg)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("App starting; env=%s", settings.app_env)
    _check_prod_invariants()
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()
        log.info("App stopped")


app = FastAPI(title="Paper Digest", lifespan=lifespan)


# --- Auth routes (fastapi-users) ---

app.include_router(
    fastapi_users.get_auth_router(auth_backend),
    prefix="/auth",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
    tags=["auth"],
)
app.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate),
    prefix="/users",
    tags=["users"],
)


# --- Domain routes (JSON API) ---

app.include_router(configs_router.router)
app.include_router(subs_router.router)


# --- HTML pages ---

app.include_router(pages_router.router)


# --- Misc ---


@app.get("/healthz")
def healthz() -> dict:
    return {
        "status": "ok",
        "env": settings.app_env,
        "prompt_version": settings.prompt_version,
        "categories": ARXIV_CATEGORIES,
        "platform_keywords": len(PLATFORM_KEYWORDS),
    }


@app.post("/admin/run-now")
async def admin_run_now() -> dict:
    if settings.app_env == "prod":
        raise HTTPException(status_code=403, detail="disabled in prod")
    stats = await run_in_threadpool(run_platform_pipeline)
    return stats


@app.post("/admin/send-digest-now")
async def admin_send_digest_now() -> list[dict]:
    """Force-fire the digest sweep for all active subs, ignoring time-of-day
    and last_sent_on. Dev-only — for testing email rendering and delivery."""
    if settings.app_env == "prod":
        raise HTTPException(status_code=403, detail="disabled in prod")
    from app.jobs.send_digests import run_digest_sweep
    return await run_digest_sweep(force=True)


@app.get("/admin/preview-digest", response_class=HTMLResponse)
async def admin_preview_digest(sub_id: str | None = None):
    """Render the email HTML for a subscription so you can see it in a browser.
    Pass ?sub_id=<uuid> or omits to grab the first active subscription."""
    if settings.app_env == "prod":
        raise HTTPException(status_code=403, detail="disabled in prod")

    import uuid as _uuid
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.db import AsyncSessionLocal
    from app.jobs.send_digests import _render_email
    from app.models import Subscription
    from app.services.query import query_today

    async with AsyncSessionLocal() as db:
        stmt = (
            select(Subscription)
            .options(selectinload(Subscription.user), selectinload(Subscription.config))
        )
        if sub_id:
            stmt = stmt.where(Subscription.id == _uuid.UUID(sub_id))
        else:
            stmt = stmt.where(Subscription.is_active.is_(True)).order_by(Subscription.created_at)
        sub = (await db.scalars(stmt)).first()
        if sub is None:
            raise HTTPException(404, "no subscription found")

        cfg = sub.config
        user = sub.user
        try:
            tz = ZoneInfo(user.tz or "UTC")
        except Exception:
            tz = ZoneInfo("UTC")
        today_local = datetime.now(tz=tz).date()
        hits = await query_today(db, cfg)
        unsubscribe_url = f"{settings.base_url.rstrip('/')}/api/subscriptions/unsubscribe/{sub.unsubscribe_token}"
        html, _text = _render_email(
            today=today_local.isoformat(),
            config_name=cfg.name,
            hits=hits,
            send_at_local=f"{sub.send_at_local.hour:02d}:{sub.send_at_local.minute:02d}",
            tz=user.tz or "UTC",
            unsubscribe_url=unsubscribe_url,
            base_url=settings.base_url.rstrip("/"),
        )
    return HTMLResponse(html)
