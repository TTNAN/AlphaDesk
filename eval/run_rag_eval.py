"""RAG 检索评测：recall@k、MRR@10。

标注方法（见 docs/eval-report.md）：
- 每道题人工阅读财报原文后编写，答案取原文中的一段逐字片段（answer_span）。
- 相关文档集合 = 同一公司下、正文包含该片段（空白归一化后）的所有 chunk。
  同一句话可能同时出现在 10-K 和 10-Q（如风险因素），两者都算相关。
- 两种检索设置：A) 按 ticker 过滤（Agent 实际调用方式）；B) 不过滤，全库 1,8xx 个 chunk 检索。

用法: python eval/run_rag_eval.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from finagent.rag.retriever import FilingRetriever  # noqa: E402

KS = (1, 3, 5, 10)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def run(stem: str) -> tuple[dict, list]:
    qs = [json.loads(l) for l in (ROOT / "eval/rag_questions.jsonl").read_text().splitlines() if l]
    r = FilingRetriever(stem=stem)
    per_q, problems = [], []
    for q in qs:
        span = norm(q["answer_span"])
        gold = {c.chunk_id for c in r.chunks if c.ticker == q["ticker"] and span in norm(c.text)}
        if not gold:
            problems.append(q["id"])
            continue
        row = {"id": q["id"], "ticker": q["ticker"], "topic": q["topic"], "question": q["question"],
               "gold": sorted(gold)}
        for setting, ticker in (("filtered", q["ticker"]), ("global", None)):
            t0 = time.perf_counter()
            hits = [c.chunk_id for c, _ in r.search(q["question"], ticker=ticker, k=10)]
            row[f"{setting}_ms"] = (time.perf_counter() - t0) * 1000
            rank = next((i + 1 for i, h in enumerate(hits) if h in gold), None)
            row[f"{setting}_rank"] = rank
            row[f"{setting}_top3"] = hits[:3]
        per_q.append(row)

    def agg(setting: str) -> dict:
        n = len(per_q)
        ranks = [p[f"{setting}_rank"] for p in per_q]
        out = {f"recall@{k}": round(sum(1 for x in ranks if x and x <= k) / n, 6) for k in KS}
        out["mrr@10"] = round(sum(1 / x for x in ranks if x) / n, 6)
        out["avg_latency_ms"] = round(sum(p[f"{setting}_ms"] for p in per_q) / n, 2)
        return out

    summary = {"tokenizer": stem, "n_questions": len(per_q), "n_chunks": len(r.chunks), "unlabeled": problems,
               "filtered_by_ticker": agg("filtered"), "global": agg("global"),
               "misses_filtered@5": [p["id"] for p in per_q if not (p["filtered_rank"] and p["filtered_rank"] <= 5)],
               "misses_global@5": [p["id"] for p in per_q if not (p["global_rank"] and p["global_rank"] <= 5)]}
    return summary, per_q


def main() -> dict:
    """默认配置为 simple（去复数 s）。porter 词干化作为消融对比，实测没有整体提升，未采用。"""
    out_dir = ROOT / "eval/results"
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {}
    for stem in ("simple", "porter"):
        summary, per_q = run(stem)
        result[stem] = {"summary": summary, "per_question": per_q}
        print(json.dumps(summary, ensure_ascii=False, indent=1))
    (out_dir / "rag_eval.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return result


if __name__ == "__main__":
    main()
