from __future__ import annotations

from datetime import datetime, timedelta, timezone

import arxiv


def fetch_recent_papers(
    categories: list[str],
    keywords: list[str],
    days: int = 3,
    max_per_category: int = 120,
) -> list[dict]:
    """Fetch recent arXiv papers across multiple categories, filtered by keyword union.

    Returns one dict per paper, deduped on arxiv_id. Caller decides DB upsert.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    client = arxiv.Client(page_size=50, delay_seconds=3, num_retries=3)
    kw_lower = [k.lower() for k in keywords]

    seen: dict[str, dict] = {}
    for cat in categories:
        search = arxiv.Search(
            query=f"cat:{cat}",
            max_results=max_per_category,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )
        for result in client.results(search):
            if result.published < cutoff:
                continue
            text = (result.title + " " + result.summary).lower()
            if not any(kw in text for kw in kw_lower):
                continue

            arxiv_id = result.entry_id.rsplit("/", 1)[-1]
            if arxiv_id in seen:
                # Merge categories from a second sighting.
                if cat not in seen[arxiv_id]["categories"]:
                    seen[arxiv_id]["categories"].append(cat)
                continue

            seen[arxiv_id] = {
                "arxiv_id": arxiv_id,
                "title": result.title.strip().replace("\n", " "),
                "authors": [a.name for a in result.authors],
                "abstract": result.summary.strip().replace("\n", " "),
                "url": result.entry_id,
                "pdf_url": result.pdf_url,
                "categories": [cat],
                "published_at": result.published,
            }
    return list(seen.values())
