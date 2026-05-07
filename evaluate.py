from __future__ import annotations

import json
import os

from openai import OpenAI

DEFAULT_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

SYSTEM_PROMPT = """你是推荐系统(Recommender Systems)领域的资深研究员，正在为同行整理论文摘要。
基于用户提供的标题、作者、摘要、以及论文首页文本(first_page_text)，从以下 4 个维度评分（1-10 整数，越高越好）：

- novelty (创新性): 方法/思路是否新颖，是否有实质创新
- practicality (实用性): 工业落地可行性，是否在真实数据/线上 A/B 验证
- rigor (严谨性): 实验设计、对比基线、消融分析的完备程度
- relevance (相关性): 与推荐系统主流方向（召回/排序/CTR/序列建模/LLM4Rec 等）的契合度

同时输出：
1) keywords: 3-5 个关键词（中英文混用，名词短语，避免 "deep learning" 这类泛词）
2) affiliations: 作者主要所属单位列表，最多 3 个，简短形式。
   - **必须从用户给出的 first_page_text（论文首页文本）中提取**——首页通常在作者名下方列出单位
   - 去重并合并到机构粒度（如 "Department of CS, Tsinghua University" → "清华大学"；"Kuaishou Technology" → "快手"）
   - 中文机构用中文，英文机构保留原名（如 "MIT"、"Google"）
   - 如果 first_page_text 为空或解析不出单位，留空数组——禁止从作者名/摘要"猜"或编造
3) summary_zh: 中文解读 200-300 字，结构为：研究动机 → 核心方法 → 主要亮点 → 局限或风险

输出必须是合法 json，严格使用以下字段（不要多余字段、不要 markdown、不要解释）：
{
  "novelty": 7,
  "practicality": 6,
  "rigor": 8,
  "relevance": 9,
  "keywords": ["sequential recommendation", "对比学习", "cold-start"],
  "affiliations": ["快手", "清华大学"],
  "summary_zh": "本文针对……（200-300 字中文解读）"
}

如果摘要明显与推荐系统无关，所有分数给 1。"""


REQUIRED_KEYS = {
    "novelty",
    "practicality",
    "rigor",
    "relevance",
    "keywords",
    "affiliations",
    "summary_zh",
}


def make_client() -> OpenAI:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY environment variable is not set")
    return OpenAI(api_key=api_key, base_url="https://api.deepseek.com")


def evaluate_paper(
    client: OpenAI,
    title: str,
    abstract: str,
    authors: list[str] | None = None,
    first_page_text: str = "",
    model: str = DEFAULT_MODEL,
) -> dict:
    author_line = ", ".join(authors[:8]) if authors else "(未知)"
    fp_block = first_page_text.strip() if first_page_text else "(首页文本未获取)"
    user_text = (
        f"请按 system 中的要求评估以下论文，并以 json 输出。\n\n"
        f"标题: {title}\n"
        f"作者: {author_line}\n\n"
        f"摘要: {abstract}\n\n"
        f"---\nfirst_page_text:\n{fp_block}"
    )
    response = client.chat.completions.create(
        model=model,
        max_tokens=2000,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("DeepSeek returned empty content")
    data = json.loads(content)
    missing = REQUIRED_KEYS - data.keys()
    if missing:
        raise ValueError(f"Missing keys in response: {missing}")
    for k in ("novelty", "practicality", "rigor", "relevance"):
        v = data[k]
        if not isinstance(v, int) or not 1 <= v <= 10:
            data[k] = max(1, min(10, int(v)))
    if not isinstance(data["affiliations"], list):
        data["affiliations"] = []
    return data
