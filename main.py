import os
import sys
from datetime import date

from evaluate import evaluate_paper, make_client
from fetch import download_first_page_text, fetch_recent_papers
from render import render_markdown

TOP_N = 5
MAX_FETCH = 80
LOOKBACK_DAYS = 3
WEIGHTS = {
    "novelty": 0.30,
    "practicality": 0.30,
    "rigor": 0.20,
    "relevance": 0.20,
}


def composite_score(e: dict) -> float:
    return sum(e[k] * w for k, w in WEIGHTS.items())


def main() -> int:
    print(f"[1/3] Fetching arXiv cs.IR papers (last {LOOKBACK_DAYS} days)...")
    papers = fetch_recent_papers(max_results=MAX_FETCH, days=LOOKBACK_DAYS)
    print(f"      Found {len(papers)} relevant papers.")
    if not papers:
        print("No papers to evaluate. Exiting.")
        return 0

    print(f"[2/3] Fetching PDF first pages and evaluating with DeepSeek...")
    client = make_client()
    scored = []
    for i, paper in enumerate(papers, 1):
        title_short = paper["title"][:70]
        print(f"      [{i}/{len(papers)}] {title_short}")
        first_page = download_first_page_text(paper["pdf_url"])
        if not first_page:
            print(f"        ~ first-page text unavailable, affiliations may be empty")
        try:
            paper["evaluation"] = evaluate_paper(
                client,
                paper["title"],
                paper["abstract"],
                authors=paper["authors"],
                first_page_text=first_page,
            )
            paper["score"] = composite_score(paper["evaluation"])
            scored.append(paper)
        except Exception as exc:
            print(f"        ! evaluation failed: {exc}")

    if not scored:
        print("All evaluations failed.")
        return 1

    scored.sort(key=lambda p: p["score"], reverse=True)
    top = scored[:TOP_N]

    print(f"[3/3] Rendering top {len(top)} to markdown...")
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{date.today().isoformat()}.md")
    render_markdown(top, output_path)
    print(f"      Wrote {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
