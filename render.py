from datetime import date


def render_markdown(papers: list[dict], output_path: str) -> None:
    today = date.today().isoformat()
    lines = [f"# 推荐系统论文日报 · {today}", "", f"今日精选 {len(papers)} 篇。", ""]

    for i, paper in enumerate(papers, 1):
        e = paper["evaluation"]
        authors = paper["authors"][:5]
        author_str = ", ".join(authors)
        if len(paper["authors"]) > 5:
            author_str += " et al."

        keywords = " · ".join(f"`{k}`" for k in e["keywords"])
        affs = e.get("affiliations") or []
        aff_str = " / ".join(affs) if affs else "—"

        lines += [
            f"## {i}. {paper['title']}",
            "",
            f"**单位**: {aff_str}  ",
            f"**作者**: {author_str}  ",
            f"**链接**: [arXiv]({paper['url']}) · [PDF]({paper['pdf_url']})  ",
            (
                f"**评分**: 综合 {paper['score']:.2f}  ·  "
                f"创新 {e['novelty']}  ·  "
                f"实用 {e['practicality']}  ·  "
                f"严谨 {e['rigor']}  ·  "
                f"相关 {e['relevance']}"
            ),
            "",
            f"**关键词**: {keywords}",
            "",
            "### 解读",
            "",
            e["summary_zh"],
            "",
            "---",
            "",
        ]

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
