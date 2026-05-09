from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_active_user
from app.config import DEFAULT_WEIGHTS
from app.db import get_async_db
from app.models import Config, User
from app.schemas import ConfigCreate, ConfigRead, ConfigUpdate

router = APIRouter(prefix="/api/configs", tags=["configs"])


WEIGHT_KEYS = {"novelty", "practicality", "rigor", "relevance"}


def _normalize_weights(weights: dict[str, float] | None) -> dict[str, float]:
    if not weights:
        return dict(DEFAULT_WEIGHTS)
    missing = WEIGHT_KEYS - weights.keys()
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"weights missing keys: {sorted(missing)}",
        )
    extra = set(weights.keys()) - WEIGHT_KEYS
    if extra:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"weights has unknown keys: {sorted(extra)}",
        )
    for k, v in weights.items():
        if not isinstance(v, (int, float)) or v < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"weights[{k}] must be a non-negative number",
            )
    return {k: float(v) for k, v in weights.items()}


async def _get_owned_config(
    cfg_id: uuid.UUID, user: User, db: AsyncSession
) -> Config:
    cfg = await db.get(Config, cfg_id)
    if cfg is None or cfg.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="config not found")
    return cfg


async def _clear_other_defaults(user_id: uuid.UUID, except_id: uuid.UUID, db: AsyncSession) -> None:
    await db.execute(
        update(Config)
        .where(Config.user_id == user_id, Config.id != except_id, Config.is_default.is_(True))
        .values(is_default=False)
    )


@router.get("", response_model=list[ConfigRead])
async def list_configs(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_db),
) -> list[Config]:
    rows = await db.scalars(
        select(Config).where(Config.user_id == user.id).order_by(Config.created_at)
    )
    return list(rows)


@router.post("", response_model=ConfigRead, status_code=status.HTTP_201_CREATED)
async def create_config(
    payload: ConfigCreate,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_db),
) -> Config:
    weights = _normalize_weights(payload.weights)
    cfg = Config(
        user_id=user.id,
        name=payload.name,
        keywords=list(payload.keywords or []),
        weights=weights,
        top_n=payload.top_n,
        is_default=payload.is_default,
    )
    db.add(cfg)
    await db.flush()
    if payload.is_default:
        await _clear_other_defaults(user.id, cfg.id, db)
    await db.commit()
    await db.refresh(cfg)
    return cfg


@router.patch("/{config_id}", response_model=ConfigRead)
async def update_config(
    config_id: uuid.UUID,
    payload: ConfigUpdate,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_db),
) -> Config:
    cfg = await _get_owned_config(config_id, user, db)
    if payload.name is not None:
        cfg.name = payload.name
    if payload.keywords is not None:
        cfg.keywords = list(payload.keywords)
    if payload.weights is not None:
        cfg.weights = _normalize_weights(payload.weights)
    if payload.top_n is not None:
        cfg.top_n = payload.top_n
    if payload.is_default is not None:
        cfg.is_default = payload.is_default
        if payload.is_default:
            await _clear_other_defaults(user.id, cfg.id, db)
    await db.commit()
    await db.refresh(cfg)
    return cfg


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_config(
    config_id: uuid.UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_db),
) -> None:
    cfg = await _get_owned_config(config_id, user, db)
    await db.delete(cfg)
    await db.commit()


async def ensure_default_config(user: User, db: AsyncSession) -> Config:
    """Create a starter default config if the user has none. Idempotent."""
    existing = await db.scalar(
        select(Config).where(Config.user_id == user.id, Config.is_default.is_(True))
    )
    if existing is not None:
        return existing
    cfg = Config(
        user_id=user.id,
        name="default",
        keywords=["recommend", "ranking", "retrieval", "ctr"],
        weights=dict(DEFAULT_WEIGHTS),
        top_n=10,
        is_default=True,
    )
    db.add(cfg)
    await db.commit()
    await db.refresh(cfg)
    return cfg
