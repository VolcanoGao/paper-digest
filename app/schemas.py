from __future__ import annotations

import uuid
from datetime import time

from fastapi_users import schemas
from pydantic import BaseModel, Field


# --- User schemas (fastapi-users) ---


class UserRead(schemas.BaseUser[uuid.UUID]):
    tz: str = "Asia/Shanghai"


class UserCreate(schemas.BaseUserCreate):
    invite_code: str | None = None
    tz: str = "Asia/Shanghai"

    # invite_code is consumed by UserManager.on_before_register and is NOT a
    # User column — strip it before fastapi-users hands the dict to the DB.
    def create_update_dict(self):  # type: ignore[override]
        d = super().create_update_dict()
        d.pop("invite_code", None)
        return d

    def create_update_dict_superuser(self):  # type: ignore[override]
        d = super().create_update_dict_superuser()
        d.pop("invite_code", None)
        return d


class UserUpdate(schemas.BaseUserUpdate):
    tz: str | None = None


# --- Config schemas ---


class ConfigCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    keywords: list[str] = Field(default_factory=list)
    weights: dict[str, float] | None = None  # falls back to defaults
    top_n: int = Field(default=10, ge=1, le=50)
    is_default: bool = False


class ConfigUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    keywords: list[str] | None = None
    weights: dict[str, float] | None = None
    top_n: int | None = Field(default=None, ge=1, le=50)
    is_default: bool | None = None


class ConfigRead(BaseModel):
    id: uuid.UUID
    name: str
    keywords: list[str]
    weights: dict[str, float]
    top_n: int
    is_default: bool

    model_config = {"from_attributes": True}


# --- Subscription schemas ---


class SubscriptionCreate(BaseModel):
    config_id: uuid.UUID
    send_at_local: time  # HH:MM in user's tz


class SubscriptionRead(BaseModel):
    id: uuid.UUID
    config_id: uuid.UUID
    send_at_local: time
    is_active: bool

    model_config = {"from_attributes": True}
