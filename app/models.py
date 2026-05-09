from __future__ import annotations

import enum
import secrets
import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    ARRAY,
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from fastapi_users.db import SQLAlchemyBaseUserTableUUID
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


# --- Users (fastapi-users base + our custom fields) ---


class User(SQLAlchemyBaseUserTableUUID, Base):
    __tablename__ = "users"

    # Encrypted via Fernet; nullable until user opts into "bring your own key" (v2).
    deepseek_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    tz: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    configs: Mapped[list["Config"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


# --- User-defined query/scoring configs ---


class Config(Base):
    __tablename__ = "configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    keywords: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    # {"novelty": 0.3, "practicality": 0.3, "rigor": 0.2, "relevance": 0.2}
    weights: Mapped[dict] = mapped_column(JSONB, nullable=False)
    top_n: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="configs")
    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="config")


# --- Shared paper pool (one row per arXiv paper, deduped) ---


class Paper(Base):
    __tablename__ = "papers"

    arxiv_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    authors: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    abstract: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    pdf_url: Mapped[str] = mapped_column(Text, nullable=False)
    categories: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    first_page_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    evaluation: Mapped["Evaluation | None"] = relationship(
        back_populates="paper", uselist=False, cascade="all, delete-orphan"
    )


# --- Shared evaluations: one per paper, scoped by prompt_version ---


class Evaluation(Base):
    __tablename__ = "evaluations"

    paper_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("papers.arxiv_id", ondelete="CASCADE"), primary_key=True
    )
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    novelty: Mapped[int] = mapped_column(Integer, nullable=False)
    practicality: Mapped[int] = mapped_column(Integer, nullable=False)
    rigor: Mapped[int] = mapped_column(Integer, nullable=False)
    relevance: Mapped[int] = mapped_column(Integer, nullable=False)

    keywords: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    affiliations: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    summary_zh: Mapped[str] = mapped_column(Text, nullable=False)

    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    paper: Mapped[Paper] = relationship(back_populates="evaluation")


# --- Subscriptions (daily email digest) ---


class SubChannel(str, enum.Enum):
    email = "email"


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("configs.id", ondelete="CASCADE"), nullable=False
    )

    channel: Mapped[SubChannel] = mapped_column(
        SAEnum(SubChannel, name="sub_channel"), default=SubChannel.email, nullable=False
    )
    send_at_local: Mapped[time] = mapped_column(Time, nullable=False)  # in user's tz
    last_sent_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    unsubscribe_token: Mapped[str] = mapped_column(
        String(64), unique=True, default=lambda: secrets.token_urlsafe(32), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="subscriptions")
    config: Mapped[Config] = relationship(back_populates="subscriptions")


# --- Run log (platform daily job + future user runs) ---


class RunKind(str, enum.Enum):
    platform = "platform"
    user = "user"


class RunStatus(str, enum.Enum):
    running = "running"
    success = "success"
    failed = "failed"


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[RunKind] = mapped_column(SAEnum(RunKind, name="run_kind"), nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        SAEnum(RunStatus, name="run_status"), default=RunStatus.running, nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    n_fetched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    n_evaluated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    n_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)
