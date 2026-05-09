from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import ARXIV_CATEGORIES, PLATFORM_KEYWORDS, settings
from app.db import session_scope
from app.models import Evaluation, Paper, Run, RunKind, RunStatus
from app.pipeline.evaluate import evaluate_paper, make_client
from app.pipeline.fetch import fetch_recent_papers
from app.pipeline.pdf import download_first_page_text

log = logging.getLogger(__name__)


def _upsert_papers(records: list[dict]) -> int:
    """Insert papers, skipping any that already exist. Returns number actually inserted."""
    if not records:
        return 0
    rows = [
        {
            "arxiv_id": r["arxiv_id"],
            "title": r["title"],
            "authors": r["authors"],
            "abstract": r["abstract"],
            "url": r["url"],
            "pdf_url": r["pdf_url"],
            "categories": r["categories"],
            "published_at": r["published_at"],
        }
        for r in records
    ]
    with session_scope() as s:
        stmt = pg_insert(Paper).values(rows)
        stmt = stmt.on_conflict_do_nothing(index_elements=[Paper.arxiv_id])
        result = s.execute(stmt)
        return result.rowcount or 0


def _papers_needing_eval(prompt_version: str) -> list[Paper]:
    with session_scope() as s:
        stmt = (
            select(Paper)
            .outerjoin(Evaluation, Evaluation.paper_id == Paper.arxiv_id)
            .where((Evaluation.paper_id.is_(None)) | (Evaluation.prompt_version != prompt_version))
        )
        return list(s.scalars(stmt))


def _save_first_page(arxiv_id: str, text: str) -> None:
    if not text:
        return
    with session_scope() as s:
        paper = s.get(Paper, arxiv_id)
        if paper is not None:
            paper.first_page_text = text


def _upsert_evaluation(arxiv_id: str, eval_data: dict, prompt_version: str) -> None:
    row = {
        "paper_id": arxiv_id,
        "prompt_version": prompt_version,
        "novelty": eval_data["novelty"],
        "practicality": eval_data["practicality"],
        "rigor": eval_data["rigor"],
        "relevance": eval_data["relevance"],
        "keywords": eval_data["keywords"],
        "affiliations": eval_data["affiliations"],
        "summary_zh": eval_data["summary_zh"],
        "evaluated_at": datetime.now(timezone.utc),
    }
    with session_scope() as s:
        stmt = pg_insert(Evaluation).values(row)
        stmt = stmt.on_conflict_do_update(
            index_elements=[Evaluation.paper_id],
            set_={k: stmt.excluded[k] for k in row if k != "paper_id"},
        )
        s.execute(stmt)


def run_platform_pipeline() -> dict:
    """Daily job: fetch new arXiv papers across monitored categories, evaluate any
    paper that lacks an evaluation at the current prompt_version, persist results.

    Returns a stats dict; also logs a Run row for visibility.
    """
    started = datetime.now(timezone.utc)
    with session_scope() as s:
        run = Run(kind=RunKind.platform, status=RunStatus.running, started_at=started)
        s.add(run)
        s.flush()
        run_id = run.id

    n_fetched = 0
    n_evaluated = 0
    n_failed = 0
    errors: list[str] = []

    try:
        log.info("Fetching arXiv: cats=%s, keywords=%d", ARXIV_CATEGORIES, len(PLATFORM_KEYWORDS))
        records = fetch_recent_papers(
            categories=ARXIV_CATEGORIES,
            keywords=PLATFORM_KEYWORDS,
            days=settings.lookback_days,
            max_per_category=settings.max_fetch_per_category,
        )
        log.info("Fetched %d candidate papers", len(records))
        inserted = _upsert_papers(records)
        n_fetched = inserted
        log.info("%d new papers inserted", inserted)

        todo = _papers_needing_eval(settings.prompt_version)
        log.info("%d papers need evaluation", len(todo))

        if todo:
            client = make_client()
            for i, paper in enumerate(todo, 1):
                title_short = paper.title[:70]
                log.info("[%d/%d] %s", i, len(todo), title_short)

                fp_text = paper.first_page_text
                if not fp_text:
                    fp_text = download_first_page_text(paper.pdf_url)
                    _save_first_page(paper.arxiv_id, fp_text)

                try:
                    result = evaluate_paper(
                        client,
                        paper.title,
                        paper.abstract,
                        authors=paper.authors,
                        first_page_text=fp_text,
                    )
                    _upsert_evaluation(paper.arxiv_id, result, settings.prompt_version)
                    n_evaluated += 1
                except Exception as exc:
                    n_failed += 1
                    msg = f"{paper.arxiv_id}: {type(exc).__name__}: {exc}"
                    errors.append(msg)
                    log.warning("evaluation failed: %s", msg)

        status = RunStatus.success
    except Exception as exc:
        status = RunStatus.failed
        errors.append(f"FATAL: {type(exc).__name__}: {exc}")
        log.exception("platform run failed")
        raise
    finally:
        with session_scope() as s:
            run = s.get(Run, run_id)
            if run is not None:
                run.status = status
                run.finished_at = datetime.now(timezone.utc)
                run.n_fetched = n_fetched
                run.n_evaluated = n_evaluated
                run.n_failed = n_failed
                run.error_log = "\n".join(errors) if errors else None

    return {
        "run_id": str(run_id),
        "n_fetched": n_fetched,
        "n_evaluated": n_evaluated,
        "n_failed": n_failed,
    }
