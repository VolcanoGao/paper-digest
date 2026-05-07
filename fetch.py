from __future__ import annotations

import io
import urllib.request
from datetime import datetime, timedelta, timezone

import arxiv
from pypdf import PdfReader

KEYWORDS = [
    "recommend",
    "recommender",
    "ranking",
    "retrieval",
    "ctr",
    "click-through",
    "collaborative filtering",
    "user modeling",
]


def fetch_recent_papers(max_results: int = 80, days: int = 3) -> list[dict]:
    search = arxiv.Search(
        query="cat:cs.IR",
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    client = arxiv.Client(page_size=50, delay_seconds=3, num_retries=3)

    papers = []
    for result in client.results(search):
        if result.published < cutoff:
            continue
        text = (result.title + " " + result.summary).lower()
        if not any(kw in text for kw in KEYWORDS):
            continue
        papers.append(
            {
                "id": result.entry_id.rsplit("/", 1)[-1],
                "title": result.title.strip().replace("\n", " "),
                "authors": [a.name for a in result.authors],
                "abstract": result.summary.strip().replace("\n", " "),
                "url": result.entry_id,
                "pdf_url": result.pdf_url,
                "published": result.published.isoformat(),
            }
        )
    return papers


def download_first_page_text(
    pdf_url: str, max_chars: int = 2500, timeout: int = 30
) -> str:
    """Download a PDF and return the first page's extracted text (truncated).

    Returns "" on any error (network, parse, empty page). The caller should
    treat empty as "no hint" rather than fatal.
    """
    try:
        req = urllib.request.Request(
            pdf_url, headers={"User-Agent": "paper-digest/0.1 (+arxiv)"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        reader = PdfReader(io.BytesIO(data))
        if not reader.pages:
            return ""
        text = reader.pages[0].extract_text() or ""
        return text.strip()[:max_chars]
    except Exception:
        return ""
