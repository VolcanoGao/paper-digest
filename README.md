# Paper Digest · 推荐系统论文日报

每天自动从 arXiv 抓取最新的推荐系统相关论文，用大模型多维度打分、提取关键词、生成中文解读，挑出 Top N 渲染成 Markdown。

## 它能干啥

- **抓取**：从 arXiv `cs.IR` 类目拉最近 N 天的新论文，按关键词（recommendation / ranking / retrieval / CTR / ...）粗筛
- **评估**：用 DeepSeek 对每篇论文从 4 个维度打分（创新性 / 实用性 / 严谨性 / 相关性），并提取关键词、推断作者所属单位、写一段中文解读
- **排序**：按加权分数排序，挑 Top N
- **渲染**：输出到 `output/YYYY-MM-DD.md`

输出片段示例：

```markdown
## 1. CapsID: Soft-Routed Variable-Length Semantic IDs for Generative Recommendation

**单位**: 快手 / 清华大学
**作者**: Zhang San, Li Si, Wang Wu et al.
**链接**: [arXiv](...) · [PDF](...)
**评分**: 综合 8.10  ·  创新 9  ·  实用 8  ·  严谨 7  ·  相关 9

**关键词**: `semantic ID` · `生成式推荐` · `variable-length tokens`

### 解读
本文针对……（200-300 字中文解读）
```

## 快速开始

需要 Python 3.9+ 与 DeepSeek API key。

```bash
# 1. 装依赖
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. 设密钥
export DEEPSEEK_API_KEY=sk-...

# 3. 跑一次
.venv/bin/python main.py
```

输出落在 `output/2026-05-07.md`。

## 切换模型

默认用 `deepseek-v4-flash`（便宜、够用）。想换 `deepseek-v4-pro` 设环境变量：

```bash
DEEPSEEK_MODEL=deepseek-v4-pro .venv/bin/python main.py
```

## 调参

参数都集中在 `main.py` 顶部：

| 参数 | 默认 | 说明 |
|---|---|---|
| `TOP_N` | 5 | 输出几篇精选 |
| `MAX_FETCH` | 80 | 从 arXiv 拉多少篇候选（拉得多，过滤后保留多，但评估调用次数也变多） |
| `LOOKBACK_DAYS` | 3 | 往回看几天的论文。arXiv 周末不发新，3 天能覆盖周一断档 |
| `WEIGHTS` | 见下 | 4 维评分的加权 |

```python
WEIGHTS = {
    "novelty": 0.30,       # 创新性
    "practicality": 0.30,  # 实用性
    "rigor": 0.20,         # 严谨性
    "relevance": 0.20,     # 相关性
}
```

四个维度权重之和不必等于 1，最终是相对排序。重视工业落地就拉高 `practicality`，偏理论就拉高 `novelty` + `rigor`。

### 关键词过滤

`fetch.py` 顶部的 `KEYWORDS` 决定哪些 `cs.IR` 论文会进评估流程。默认包含：

```python
KEYWORDS = [
    "recommend", "recommender", "ranking", "retrieval",
    "ctr", "click-through", "collaborative filtering",
    "user modeling",
]
```

只要论文标题或摘要里命中其一就纳入评估。想加新方向（比如 `LLM4Rec`、`agent`），改这个列表即可。

## 项目结构

```
paper-digest/
├── fetch.py          # arXiv 抓取 + 关键词粗筛
├── evaluate.py       # DeepSeek 调用：评分 + 关键词 + 单位 + 解读
├── render.py         # markdown 渲染
├── main.py           # 串起来：抓 → 评 → 排序 → 写文件
├── requirements.txt
└── output/           # 生成的 markdown
```

## 成本估算

每篇论文 ~1 次 API 调用，输入 ~600 tokens（系统 prompt + 摘要），输出 ~800 tokens（评分 + 解读）。按 DeepSeek V4 Flash 计费一篇约 ¥0.001-0.003，一次跑 20 篇候选 ≈ ¥0.05 左右。

## 路线图（按需扩展）

- [ ] 加 RSS 输出（`output/rss.xml`）
- [ ] GitHub Actions 每日定时跑 + 自动 commit
- [ ] 静态站点（Astro / Next.js）展示历史归档
- [ ] 多源：Hugging Face Papers / Semantic Scholar
- [ ] 失败重试 + 速率限制

## 已知限制

- DeepSeek 的 `json_object` 模式偶尔会返回空内容，目前直接抛异常跳过；上线前可加自动重试
- 单位 (`affiliations`) 是 LLM 推断，对知名作者准、对新人可能空着——这是设计选择（"宁缺毋滥"）
- arXiv 周末不出新，每周一会发现 2 天的论文，正常现象
