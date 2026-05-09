from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, Request, status
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users.authentication import (
    AuthenticationBackend,
    CookieTransport,
    JWTStrategy,
)
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_async_db
from app.models import User
from app.schemas import UserCreate

COOKIE_NAME = "paperdigest_session"
COOKIE_LIFETIME = 60 * 60 * 24 * 14  # 14 days


# --- DB adapter ---


async def get_user_db(
    session: AsyncSession = Depends(get_async_db),
) -> AsyncIterator[SQLAlchemyUserDatabase]:
    yield SQLAlchemyUserDatabase(session, User)


# --- UserManager: hooks + invite-code gating ---


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = settings.secret_key
    verification_token_secret = settings.secret_key

    async def validate_password(self, password: str, user: User | UserCreate) -> None:
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters.")

    async def on_before_register(
        self, user_create: UserCreate, request: Request | None = None
    ) -> None:
        codes = [c.strip() for c in settings.invite_codes.split(",") if c.strip()]
        if not codes:
            return  # registration is open
        provided = (user_create.invite_code or "").strip()
        if provided not in codes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="invalid or missing invite code",
            )

    async def create(
        self, user_create: UserCreate, safe: bool = False, request: Request | None = None
    ) -> User:
        # Hook in invite-code check before fastapi-users does the DB write.
        await self.on_before_register(user_create, request)
        return await super().create(user_create, safe=safe, request=request)

    async def on_after_register(self, user: User, request: Request | None = None) -> None:
        # Seed a default config so the user lands on a working "Today" page.
        # Deferred import avoids auth <-> routers cycle at module load.
        from app.db import AsyncSessionLocal
        from app.routers.configs import ensure_default_config

        async with AsyncSessionLocal() as session:
            await ensure_default_config(user, session)


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase = Depends(get_user_db),
) -> AsyncIterator[UserManager]:
    yield UserManager(user_db)


# --- Auth backend: cookie transport + JWT strategy ---


cookie_transport = CookieTransport(
    cookie_name=COOKIE_NAME,
    cookie_max_age=COOKIE_LIFETIME,
    # In prod (Fly serves over HTTPS) require Secure. Locally we'd lock ourselves
    # out of HTTP-only dev otherwise.
    cookie_secure=(settings.app_env == "prod"),
    cookie_httponly=True,
    cookie_samesite="lax",
)


def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(secret=settings.secret_key, lifetime_seconds=COOKIE_LIFETIME)


auth_backend = AuthenticationBackend(
    name="cookie",
    transport=cookie_transport,
    get_strategy=get_jwt_strategy,
)


# --- FastAPIUsers entry point ---


fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

current_active_user = fastapi_users.current_user(active=True)
current_superuser = fastapi_users.current_user(active=True, superuser=True)
