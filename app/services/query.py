from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models import Config, Evaluation, Paper


@dataclass
class PaperHit:
    arxiv_id: str
    title: str
    authors: list[str]
    url: str
    pdf_url: str
    published_at: datetime
    novelty: int
    practicality: int
    rigor: int
    relevance: int
    composite: float
    keywords: list[str]
    affiliations: list[str]
    summary_zh: str


def _composite(
    n: int, p: int, r: int, rel: int, weights: dict[str, float]
) -> float:
    return (
        n * weights["novelty"]
        + p * weights["practicality"]
        + r * weights["rigor"]
        + rel * weights["relevance"]
    )


async def query_for_config(
    db: AsyncSession,
    config: Config,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int | None = None,
) -> list[PaperHit]:
    """Filter shared paper pool by config.keywords (case-insensitive substring on
    title+abstract), sort by user-weighted composite score.

    `limit` defaults to config.top_n if not provided.
    """
    stmt = (
        select(Paper, Evaluation)
        .join(Evaluation, Evaluation.paper_id == Paper.arxiv_id)
    )

    if since is not None:
        stmt = stmt.where(Paper.published_at >= since)
    if until is not None:
        stmt = stmt.where(Paper.published_at < until)

    keywords = [k.strip() for k in (config.keywords or []) if k.strip()]
    if keywords:
        # Concatenate title + " " + abstract once, then substring match each keyword.
        # Postgres ILIKE is case-insensitive; %escape isn't a concern here since
        # users typically type plain words/phrases.
        haystack = (Paper.title + " " + Paper.abstract)
        clauses = [haystack.ilike(f"%{kw}%") for kw in keywords]
        stmt = stmt.where(or_(*clauses))

    rows = (await db.execute(stmt)).all()

    weights = config.weights
    hits = [
        PaperHit(
            arxiv_id=p.arxiv_id,
            title=p.title,
            authors=p.authors or [],
            url=p.url,
            pdf_url=p.pdf_url,
            published_at=p.published_at,
            novelty=e.novelty,
            practicality=e.practicality,
            rigor=e.rigor,
            relevance=e.relevance,
            composite=round(
                _composite(e.novelty, e.practicality, e.rigor, e.relevance, weights), 2
            ),
            keywords=e.keywords or [],
            affiliations=e.affiliations or [],
            summary_zh=e.summary_zh or "",
        )
        for p, e in rows
    ]

    hits.sort(key=lambda h: h.composite, reverse=True)
    return hits[: (limit if limit is not None else config.top_n)]


async def query_today(db: AsyncSession, config: Config) -> list[PaperHit]:
    """Latest day-or-so window. Mirrors the platform's lookback (3 days) so users
    aren't surprised by an empty page on weekends — arXiv doesn't publish."""
    since = datetime.now(timezone.utc) - timedelta(days=3)
    return await query_for_config(db, config, since=since)


async def query_for_date(db: AsyncSession, config: Config, day: date) -> list[PaperHit]:
    """Papers published on a specific day (UTC)."""
    since = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
    until = since + timedelta(days=1)
    # Loosen: users care about ranked results, not exact-day cap. Don't apply top_n.
    return await query_for_config(db, config, since=since, until=until, limit=None)
