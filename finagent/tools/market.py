"""行情与新闻工具。数据为日线收盘价（非实时），返回结果都带 source 和 as_of。"""
from __future__ import annotations

from datetime import date, datetime, timezone

from .. import config
from ..data_sources import load_news, load_prices


def _check_ticker(ticker: str) -> str:
    t = (ticker or "").strip().upper()
    if t not in config.PRICE_TICKERS:
        raise ValueError(f"不支持的代码 {ticker}，当前标的池: {', '.join(config.PRICE_TICKERS)}")
    return t


def _freshness(data: dict, last_row: dict) -> dict:
    try:
        as_of = date.fromisoformat(str(last_row["date"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("行情日期无效") from exc
    age_days = (datetime.now(timezone.utc).date() - as_of).days
    if age_days < 0:
        raise ValueError(f"行情日期 {as_of} 晚于当前日期")
    return {
        "data_age_days": age_days,
        "stale": age_days > config.MAX_MARKET_DATA_AGE_DAYS,
        "fetched_at": data.get("fetched_at"),
        "refresh_status": data.get("refresh_status", "unknown"),
    }


def get_quote(ticker: str) -> dict:
    t = _check_ticker(ticker)
    data = load_prices(t)
    rows = data.get("rows") or []
    if len(rows) < 2:
        raise ValueError(f"{t} 行情至少需要两个交易日，当前缓存不足")
    last, prev = rows[-1], rows[-2]
    year = rows[-252:]
    freshness = _freshness(data, last)
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
        **freshness,
        "note": "日线收盘价，非实时行情；stale=true 表示数据已超过 7 天",
    }


def get_price_history(ticker: str, days: int = 30) -> dict:
    t = _check_ticker(ticker)
    days = max(1, min(int(days), 500))
    data = load_prices(t)
    rows = (data.get("rows") or [])[-days:]
    if not rows:
        raise ValueError(f"{t} 没有可用的历史行情")
    freshness = _freshness(data, rows[-1])
    first, last = rows[0]["adj_close"], rows[-1]["adj_close"]
    return {
        "ticker": t,
        "start": rows[0]["date"],
        "end": rows[-1]["date"],
        "n": len(rows),
        "period_return_pct": round((last / first - 1) * 100, 3),
        "rows": [{"date": r["date"], "close": round(r["close"], 4), "volume": r["volume"]} for r in rows],
        "source": data["source"],
        **freshness,
    }


def get_company_news(ticker: str, limit: int = 5) -> dict:
    t = _check_ticker(ticker)
    data = load_news(t)
    items = data["items"][: max(1, min(int(limit), 20))]
    return {"ticker": t, "fetched_at": data["fetched_at"], "source": data["source"], "items": items}
