from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from fastapi_users.exceptions import UserAlreadyExists
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    cookie_transport,
    fastapi_users,
    get_jwt_strategy,
    get_user_manager,
)
from app.config import DEFAULT_WEIGHTS, PLATFORM_KEYWORDS
from app.crypto import encrypt
from app.db import get_async_db
from app.models import Config, Subscription, User
from app.routers.configs import _normalize_weights, ensure_default_config
from app.schemas import UserCreate
from app.services.query import query_for_date, query_today

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(tags=["pages"])

# Optional-user dependency: pages render differently if logged in vs out.
optional_user = fastapi_users.current_user(active=True, optional=True)


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=cookie_transport.cookie_name,
        value=token,
        max_age=cookie_transport.cookie_max_age,
        path=cookie_transport.cookie_path,
        domain=cookie_transport.cookie_domain,
        secure=cookie_transport.cookie_secure,
        httponly=cookie_transport.cookie_httponly,
        samesite=cookie_transport.cookie_samesite,
    )


def render(
    request: Request,
    template: str,
    user: User | None = None,
    *,
    active_nav: str | None = None,
    flash: dict | None = None,
    status_code: int = 200,
    **ctx,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        template,
        {"user": user, "active_nav": active_nav, "flash": flash, **ctx},
        status_code=status_code,
    )


# --- Index ---


@router.get("/", response_class=HTMLResponse)
async def index(user: User | None = Depends(optional_user)) -> Response:
    return RedirectResponse(url="/today" if user else "/login", status_code=302)


# --- Login ---


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request, user: User | None = Depends(optional_user)
) -> Response:
    if user:
        return RedirectResponse(url="/today", status_code=302)
    return render(request, "login.html")


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    user_manager=Depends(get_user_manager),
):
    # Manual auth: match what fastapi-users' login endpoint does.
    from fastapi_users.exceptions import UserNotExists

    try:
        candidate = await user_manager.get_by_email(email)
    except UserNotExists:
        candidate = None

    valid = False
    updated_password_hash: str | None = None
    if candidate is not None:
        valid, updated_password_hash = user_manager.password_helper.verify_and_update(
            password, candidate.hashed_password
        )

    if not candidate or not valid or not candidate.is_active:
        return render(
            request,
            "login.html",
            flash={"kind": "error", "text": "邮箱或密码错误"},
            email=email,
            status_code=400,
        )

    if updated_password_hash is not None:
        await user_manager.user_db.update(candidate, {"hashed_password": updated_password_hash})

    strategy = get_jwt_strategy()
    token = await strategy.write_token(candidate)
    response = RedirectResponse(url="/today", status_code=303)
    _set_session_cookie(response, token)
    return response


# --- Register ---


@router.get("/register", response_class=HTMLResponse)
async def register_page(
    request: Request, user: User | None = Depends(optional_user)
) -> Response:
    if user:
        return RedirectResponse(url="/today", status_code=302)
    return render(request, "register.html")


@router.post("/register", response_class=HTMLResponse)
async def register_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    invite_code: str | None = Form(default=None),
    tz: str = Form(default="Asia/Shanghai"),
    user_manager=Depends(get_user_manager),
):
    try:
        user = await user_manager.create(
            UserCreate(
                email=email,
                password=password,
                invite_code=invite_code or None,
                tz=tz,
            )
        )
    except UserAlreadyExists:
        return render(
            request,
            "register.html",
            flash={"kind": "error", "text": "该邮箱已注册"},
            email=email,
            status_code=400,
        )
    except HTTPException as exc:
        return render(
            request,
            "register.html",
            flash={"kind": "error", "text": exc.detail or "注册失败"},
            email=email,
            status_code=exc.status_code,
        )
    except ValueError as exc:
        return render(
            request,
            "register.html",
            flash={"kind": "error", "text": str(exc)},
            email=email,
            status_code=400,
        )

    # Auto-login after registration.
    strategy = get_jwt_strategy()
    token = await strategy.write_token(user)
    response = RedirectResponse(url="/today", status_code=303)
    _set_session_cookie(response, token)
    return response


# --- Logout ---


@router.post("/logout")
async def logout(user: User | None = Depends(optional_user)) -> Response:
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(
        key=cookie_transport.cookie_name,
        path=cookie_transport.cookie_path,
        domain=cookie_transport.cookie_domain,
    )
    return response


# --- Today / archive ---


async def _resolve_config(
    db: AsyncSession, user: User, config_id: uuid.UUID | None
) -> Config | None:
    if config_id is not None:
        cfg = await db.get(Config, config_id)
        if cfg and cfg.user_id == user.id:
            return cfg
    # fallback: default config
    cfg = await db.scalar(
        select(Config).where(Config.user_id == user.id, Config.is_default.is_(True))
    )
    if cfg:
        return cfg
    # last resort: any config
    return await db.scalar(
        select(Config).where(Config.user_id == user.id).order_by(Config.created_at)
    )


async def _user_configs(db: AsyncSession, user: User) -> list[Config]:
    rows = await db.scalars(
        select(Config).where(Config.user_id == user.id).order_by(Config.created_at)
    )
    return list(rows)


@router.get("/today", response_class=HTMLResponse)
async def today_page(
    request: Request,
    config_id: uuid.UUID | None = Query(default=None),
    user: User | None = Depends(optional_user),
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    cfg = await _resolve_config(db, user, config_id)
    if cfg is None:
        return render(
            request, "today.html",
            user=user, active_nav="today",
            cfg=None, configs=[], hits=[],
            flash={"kind": "error", "text": "你还没有配置，请去 Configs 创建一个"},
        )
    configs = await _user_configs(db, user)
    hits = await query_today(db, cfg)
    return render(
        request, "today.html",
        user=user, active_nav="today",
        cfg=cfg, configs=configs, hits=hits,
    )


@router.get("/archive", response_class=HTMLResponse)
async def archive_page(
    request: Request,
    day: str | None = Query(default=None, alias="date"),
    config_id: uuid.UUID | None = Query(default=None),
    user: User | None = Depends(optional_user),
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    cfg = await _resolve_config(db, user, config_id)
    configs = await _user_configs(db, user)

    # Default to yesterday (UTC) so archive doesn't duplicate /today on first hit.
    if day is None:
        target_day = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    else:
        try:
            target_day = date.fromisoformat(day)
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid date format, expect YYYY-MM-DD")

    hits = await query_for_date(db, cfg, target_day) if cfg else []
    return render(
        request, "archive.html",
        user=user, active_nav="archive",
        cfg=cfg, configs=configs, hits=hits, target_day=target_day,
    )


# --- Configs page ---


def _parse_keywords(raw: str) -> list[str]:
    items: list[str] = []
    for chunk in raw.replace("\r", "").split("\n"):
        for kw in chunk.split(","):
            kw = kw.strip()
            if kw and kw not in items:
                items.append(kw)
    return items


def _classify_keywords(keywords: list[str]) -> list[dict]:
    plat = {k.lower() for k in PLATFORM_KEYWORDS}
    return [{"text": k, "monitored": k.lower() in plat} for k in keywords]


@router.get("/configs", response_class=HTMLResponse)
async def configs_page(
    request: Request,
    user: User | None = Depends(optional_user),
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    rows = await db.scalars(
        select(Config).where(Config.user_id == user.id).order_by(Config.created_at)
    )
    configs = list(rows)
    annotated = [
        {"cfg": c, "kw_status": _classify_keywords(c.keywords or [])} for c in configs
    ]
    return render(
        request, "configs.html",
        user=user, active_nav="configs",
        configs=annotated,
        default_weights=DEFAULT_WEIGHTS,
        platform_keywords=PLATFORM_KEYWORDS,
    )


@router.post("/configs/new")
async def configs_new(
    name: str = Form(...),
    user: User = Depends(fastapi_users.current_user(active=True)),
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    name = name.strip() or "untitled"
    cfg = Config(
        user_id=user.id,
        name=name,
        keywords=[],
        weights=dict(DEFAULT_WEIGHTS),
        top_n=10,
        is_default=False,
    )
    db.add(cfg)
    await db.commit()
    return RedirectResponse(url="/configs", status_code=303)


@router.post("/configs/{config_id}/save")
async def configs_save(
    config_id: uuid.UUID,
    request: Request,
    name: str = Form(...),
    keywords_raw: str = Form(default=""),
    top_n: int = Form(...),
    weight_novelty: float = Form(...),
    weight_practicality: float = Form(...),
    weight_rigor: float = Form(...),
    weight_relevance: float = Form(...),
    is_default: str | None = Form(default=None),
    user: User = Depends(fastapi_users.current_user(active=True)),
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    cfg = await db.get(Config, config_id)
    if cfg is None or cfg.user_id != user.id:
        raise HTTPException(status_code=404, detail="config not found")

    cfg.name = name.strip() or cfg.name
    cfg.keywords = _parse_keywords(keywords_raw)
    cfg.top_n = max(1, min(50, top_n))
    try:
        cfg.weights = _normalize_weights({
            "novelty": weight_novelty,
            "practicality": weight_practicality,
            "rigor": weight_rigor,
            "relevance": weight_relevance,
        })
    except HTTPException as exc:
        raise exc

    new_default = is_default == "on"
    if new_default and not cfg.is_default:
        # Clear other defaults.
        from sqlalchemy import update as sa_update
        await db.execute(
            sa_update(Config)
            .where(Config.user_id == user.id, Config.id != cfg.id, Config.is_default.is_(True))
            .values(is_default=False)
        )
    cfg.is_default = new_default
    await db.commit()
    return RedirectResponse(url="/configs", status_code=303)


@router.post("/configs/{config_id}/delete")
async def configs_delete(
    config_id: uuid.UUID,
    user: User = Depends(fastapi_users.current_user(active=True)),
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    cfg = await db.get(Config, config_id)
    if cfg is None or cfg.user_id != user.id:
        raise HTTPException(status_code=404, detail="config not found")
    await db.delete(cfg)
    await db.commit()
    return RedirectResponse(url="/configs", status_code=303)


# --- Settings page ---


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    user: User | None = Depends(optional_user),
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    configs = await _user_configs(db, user)
    subs = list(
        await db.scalars(
            select(Subscription).where(Subscription.user_id == user.id).order_by(Subscription.created_at)
        )
    )
    cfg_by_id = {c.id: c for c in configs}
    sub_rows = [{"sub": s, "config": cfg_by_id.get(s.config_id)} for s in subs]
    return render(
        request, "settings.html",
        user=user, active_nav="settings",
        configs=configs, subs=sub_rows,
        has_deepseek_key=bool(user.deepseek_key_encrypted),
    )


@router.post("/settings/profile")
async def settings_save_profile(
    tz: str = Form(...),
    user: User = Depends(fastapi_users.current_user(active=True)),
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    user.tz = tz.strip() or user.tz
    db.add(user)
    await db.commit()
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/settings/deepseek-key")
async def settings_save_key(
    deepseek_key: str = Form(default=""),
    clear: str | None = Form(default=None),
    user: User = Depends(fastapi_users.current_user(active=True)),
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    if clear == "1":
        user.deepseek_key_encrypted = None
    elif deepseek_key.strip():
        user.deepseek_key_encrypted = encrypt(deepseek_key.strip())
    db.add(user)
    await db.commit()
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/settings/subscriptions/new")
async def settings_sub_new(
    config_id: uuid.UUID = Form(...),
    send_at_local: str = Form(...),
    user: User = Depends(fastapi_users.current_user(active=True)),
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    cfg = await db.get(Config, config_id)
    if cfg is None or cfg.user_id != user.id:
        raise HTTPException(status_code=404, detail="config not found")
    from datetime import time as dtime
    try:
        h, m = send_at_local.split(":")[:2]
        t = dtime(hour=int(h), minute=int(m))
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="invalid time format, expect HH:MM")
    sub = Subscription(user_id=user.id, config_id=cfg.id, send_at_local=t)
    db.add(sub)
    await db.commit()
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/settings/subscriptions/{sub_id}/delete")
async def settings_sub_delete(
    sub_id: uuid.UUID,
    user: User = Depends(fastapi_users.current_user(active=True)),
    db: AsyncSession = Depends(get_async_db),
) -> Response:
    sub = await db.get(Subscription, sub_id)
    if sub is None or sub.user_id != user.id:
        raise HTTPException(status_code=404, detail="subscription not found")
    await db.delete(sub)
    await db.commit()
    return RedirectResponse(url="/settings", status_code=303)
