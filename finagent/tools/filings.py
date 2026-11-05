"""财报检索（RAG）与 XBRL 关键财务数据。"""
from __future__ import annotations

from datetime import date

from .. import config
from ..data_sources import load_facts
from ..rag.retriever import get_retriever

SNIPPET_CHARS = 1200


def _best_window(text: str, query: str, size: int = SNIPPET_CHARS) -> str:
    """返回与查询词重合最多的一段文本，避免答案落在固定前缀之外被截掉。"""
    if len(text) <= size:
        return text
    from ..rag.retriever import tokenize
    q = set(tokenize(query))
    step = 200
    best, best_score = 0, -1
    for start in range(0, len(text) - size + step, step):
        score = sum(1 for t in tokenize(text[start:start + size]) if t in q)
        if score > best_score:
            best, best_score = start, score
    w = text[best:best + size]
    return ("…" if best > 0 else "") + w + ("…" if best + size < len(text) else "")


def search_filings(query: str, ticker: str | None = None, form: str | None = None, k: int = 5) -> dict:
    if not query or not query.strip():
        raise ValueError("query 不能为空")
    if ticker and ticker.upper() not in config.COMPANIES:
        raise ValueError(f"不支持的公司 {ticker}，财报库: {', '.join(config.COMPANIES)}")
    k = max(1, min(int(k), 10))
    hits = get_retriever().search(query, ticker=ticker, form=form, k=k)
    results = []
    for c, score in hits:
        results.append({
            "chunk_id": c.chunk_id,
            "citation": f"[{c.chunk_id}] {c.company} {c.form} ({c.period}) {c.section} {c.section_title}",
            "ticker": c.ticker, "form": c.form, "period": c.period,
            "section": c.section, "section_title": c.section_title,
            "score": round(score, 3), "url": c.url,
            "text": _best_window(c.text, query),
        })
    return {"query": query, "filters": {"ticker": ticker, "form": form}, "results": results,
            "instruction": "回答中引用财报内容时，必须使用 [chunk_id] 标注来源"}


def _days(s: str | None, e: str) -> int | None:
    if not s:
        return None
    return (date.fromisoformat(e) - date.fromisoformat(s)).days


def get_key_financials(ticker: str, metrics: list[str] | None = None, period: str = "annual",
                       limit: int = 4) -> dict:
    t = (ticker or "").upper()
    if t not in config.COMPANIES:
        raise ValueError(f"不支持的公司 {ticker}")
    if period not in ("annual", "quarterly"):
        raise ValueError("period 只能是 annual 或 quarterly")
    facts = load_facts(t)
    available = list(facts["metrics"])
    wanted = metrics or available
    unknown = [m for m in wanted if m not in available]
    out = {}
    for m in wanted:
        if m not in available:
            continue
        info = facts["metrics"][m]
        vals = []
        for v in info["values"]:
            d = _days(v.get("start"), v["end"])
            if d is None:  # 时点数（资产负债表）
                if period == "annual" and v.get("form") != "10-K":
                    continue
            elif period == "annual" and not (330 <= d <= 380):
                continue
            elif period == "quarterly" and not (80 <= d <= 100):
                continue
            vals.append({"start": v.get("start"), "end": v["end"], "value": v["val"], "fy": v.get("fy"),
                         "fp": v.get("fp"), "form": v.get("form"), "accn": v.get("accn")})
        out[m] = {"concept": f"us-gaap:{info['concept']}", "unit": info["unit"], "values": vals[-limit:]}
    return {"ticker": t, "company": facts["company"], "period": period, "metrics": out,
            "unknown_metrics": unknown, "available_metrics": available, "source": facts["source"]}
