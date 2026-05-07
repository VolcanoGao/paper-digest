from datetime import datetime, timedelta, timezone

import arxiv

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
