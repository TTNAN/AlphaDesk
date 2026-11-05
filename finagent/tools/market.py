"""行情与新闻工具。数据为日线收盘价（非实时），返回结果都带 source 和 as_of。"""
from __future__ import annotations

from .. import config
from ..data_sources import load_news, load_prices


def _check_ticker(ticker: str) -> str:
    t = (ticker or "").strip().upper()
    if t not in config.PRICE_TICKERS:
        raise ValueError(f"不支持的代码 {ticker}，当前标的池: {', '.join(config.PRICE_TICKERS)}")
    return t


def get_quote(ticker: str) -> dict:
    t = _check_ticker(ticker)
    data = load_prices(t)
    rows = data["rows"]
    last, prev = rows[-1], rows[-2]
    year = rows[-252:]
    return {
        "ticker": t,
        "as_of": last["date"],
        "close": round(last["close"], 4),
        "prev_close": round(prev["close"], 4),
        "change_pct": round((last["close"] / prev["close"] - 1) * 100, 3),
        "volume": last["volume"],
        "high_52w": round(max(r["high"] for r in year), 4),
        "low_52w": round(min(r["low"] for r in year), 4),
        "source": data["source"],
        "note": "日线收盘价，非实时行情",
    }


def get_price_history(ticker: str, days: int = 30) -> dict:
    t = _check_ticker(ticker)
    days = max(1, min(int(days), 500))
    data = load_prices(t)
    rows = data["rows"][-days:]
    first, last = rows[0]["adj_close"], rows[-1]["adj_close"]
    return {
        "ticker": t,
        "start": rows[0]["date"],
        "end": rows[-1]["date"],
        "n": len(rows),
        "period_return_pct": round((last / first - 1) * 100, 3),
        "rows": [{"date": r["date"], "close": round(r["close"], 4), "volume": r["volume"]} for r in rows],
        "source": data["source"],
    }


def get_company_news(ticker: str, limit: int = 5) -> dict:
    t = _check_ticker(ticker)
    data = load_news(t)
    items = data["items"][: max(1, min(int(limit), 20))]
    return {"ticker": t, "fetched_at": data["fetched_at"], "source": data["source"], "items": items}
