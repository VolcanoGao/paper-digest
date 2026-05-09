from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("App starting; env=%s", settings.app_env)
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
