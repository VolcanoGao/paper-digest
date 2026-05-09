from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_active_user
from app.db import get_async_db
from app.models import Config, Subscription, User
from app.schemas import SubscriptionCreate, SubscriptionRead

router = APIRouter(prefix="/api/subscriptions", tags=["subscriptions"])


@router.get("", response_model=list[SubscriptionRead])
async def list_subscriptions(
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_db),
) -> list[Subscription]:
    rows = await db.scalars(
        select(Subscription).where(Subscription.user_id == user.id).order_by(Subscription.created_at)
    )
    return list(rows)


@router.post("", response_model=SubscriptionRead, status_code=status.HTTP_201_CREATED)
async def create_subscription(
    payload: SubscriptionCreate,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_db),
) -> Subscription:
    cfg = await db.get(Config, payload.config_id)
    if cfg is None or cfg.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="config not found")
    sub = Subscription(
        user_id=user.id,
        config_id=cfg.id,
        send_at_local=payload.send_at_local,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return sub


@router.delete("/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subscription(
    subscription_id: uuid.UUID,
    user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_async_db),
) -> None:
    sub = await db.get(Subscription, subscription_id)
    if sub is None or sub.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="subscription not found")
    await db.delete(sub)
    await db.commit()


# Public, no auth — just the token. Required for one-click unsubscribe in emails.
@router.get("/unsubscribe/{token}")
async def unsubscribe(
    token: str,
    db: AsyncSession = Depends(get_async_db),
) -> dict:
    sub = await db.scalar(select(Subscription).where(Subscription.unsubscribe_token == token))
    if sub is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="unknown token")
    sub.is_active = False
    await db.commit()
    return {"status": "unsubscribed"}
