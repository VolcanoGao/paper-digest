from __future__ import annotations

import json
import os

from openai import OpenAI

DEFAULT_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")

SYSTEM_PROMPT = """你是推荐系统(Recommender Systems)领域的资深研究员，正在为同行整理论文摘要。
基于用户给出的论文标题、作者列表与摘要，从以下 4 个维度评分（1-10 整数，越高越好）：

- novelty (创新性): 方法/思路是否新颖，是否有实质创新
- practicality (实用性): 工业落地可行性，是否在真实数据/线上 A/B 验证
- rigor (严谨性): 实验设计、对比基线、消融分析的完备程度
- relevance (相关性): 与推荐系统主流方向（召回/排序/CTR/序列建模/LLM4Rec 等）的契合度

同时输出：
1) keywords: 3-5 个关键词（中英文混用，名词短语，避免 "deep learning" 这类泛词）
2) affiliations: 作者主要所属单位列表，最多 3 个，简短形式（如 "快手"、"阿里"、"上海交通大学"、"Google"）。
   - 优先依据摘要里明确提到的部署/实验机构（如 "deployed on Kuaishou" → "快手"）
   - 其次依据知名作者已知所属
   - 不确定就留空数组，宁缺毋滥，禁止编造
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
    model: str = DEFAULT_MODEL,
) -> dict:
    author_line = ", ".join(authors[:8]) if authors else "(未知)"
    user_text = (
        f"请按 system 中的要求评估以下论文，并以 json 输出。\n\n"
        f"标题: {title}\n"
        f"作者: {author_line}\n\n"
        f"摘要: {abstract}"
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
