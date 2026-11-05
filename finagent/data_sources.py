"""数据源适配层。

可用性实测（2026-11-05，本项目开发沙箱）：
- SEC EDGAR submissions / Archives / XBRL companyfacts：可用（需 User-Agent 带联系方式）
- Yahoo Finance chart API (query1.finance.yahoo.com/v8/finance/chart)：可用，行情主源
- Yahoo Finance RSS (feeds.finance.yahoo.com)：可用，新闻源
- 东方财富 push2his（http）：可用，行情备用源；https 访问超时
- Stooq：不可用（返回 JS 验证页）

所有在线获取的数据都会写入 data/cache，离线模式（FINAGENT_OFFLINE=1，默认）只读缓存。
"""
from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import config


class DataUnavailable(Exception):
    pass


def _get(url: str, ua: str, timeout: int = 20) -> requests.Response:
    r = requests.get(url, headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}, timeout=timeout)
    r.raise_for_status()
    return r


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def _read_json(path: Path):
    if not path.exists():
        raise DataUnavailable(f"缓存不存在: {path}，请先运行 scripts/fetch_data.py")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------- 行情 ----------------

def fetch_prices_yahoo(ticker: str, rng: str = "2y") -> list[dict]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={rng}&interval=1d"
    res = _get(url, config.HTTP_USER_AGENT).json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose") or q["close"]
    rows = []
    for i, ts in enumerate(res["timestamp"]):
        if q["close"][i] is None:
            continue
        rows.append({
            "date": datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d"),
            "open": q["open"][i], "high": q["high"][i], "low": q["low"][i],
            "close": q["close"][i], "adj_close": adj[i], "volume": q["volume"][i],
        })
    return rows


_EM_SECID = {"NVDA": "105.NVDA", "MSFT": "105.MSFT", "AAPL": "105.AAPL", "TSLA": "105.TSLA",
             "AMZN": "105.AMZN", "QQQ": "105.QQQ"}


def fetch_prices_eastmoney(ticker: str, limit: int = 500) -> list[dict]:
    secid = _EM_SECID.get(ticker, f"105.{ticker}")
    url = ("http://push2his.eastmoney.com/api/qt/stock/kline/get?secid=" + secid +
           "&fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56&klt=101&fqt=1&end=20500101&lmt=" + str(limit))
    data = _get(url, config.HTTP_USER_AGENT).json().get("data") or {}
    rows = []
    for line in data.get("klines", []):
        d, o, c, h, l, v = line.split(",")[:6]
        rows.append({"date": d, "open": float(o), "high": float(h), "low": float(l),
                     "close": float(c), "adj_close": float(c), "volume": float(v)})
    if not rows:
        raise DataUnavailable(f"eastmoney 无数据: {ticker}")
    return rows


def refresh_prices(ticker: str) -> dict:
    """在线拉取并缓存。Yahoo 优先，失败时回落东方财富。"""
    source, rows = "yahoo", None
    try:
        rows = fetch_prices_yahoo(ticker)
    except Exception:
        source, rows = "eastmoney", fetch_prices_eastmoney(ticker)
    obj = {"ticker": ticker, "source": source,
           "fetched_at": config.now_iso(), "rows": rows}
    _write_json(config.PRICES_DIR / f"{ticker}.json", obj)
    return obj


def load_prices(ticker: str) -> dict:
    ticker = ticker.upper()
    if not config.OFFLINE:
        try:
            return refresh_prices(ticker)
        except Exception:
            pass
    return _read_json(config.PRICES_DIR / f"{ticker}.json")


# ---------------- 新闻 ----------------

def refresh_news(ticker: str) -> dict:
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
    root = ET.fromstring(_get(url, config.HTTP_USER_AGENT).content)
    items = []
    for it in root.iter("item"):
        items.append({
            "title": (it.findtext("title") or "").strip(),
            "link": (it.findtext("link") or "").strip(),
            "published": (it.findtext("pubDate") or "").strip(),
            "summary": (it.findtext("description") or "").strip()[:400],
        })
    obj = {"ticker": ticker, "source": "yahoo_rss",
           "fetched_at": config.now_iso(), "items": items}
    _write_json(config.NEWS_DIR / f"{ticker}.json", obj)
    return obj


def load_news(ticker: str) -> dict:
    ticker = ticker.upper()
    if not config.OFFLINE:
        try:
            return refresh_news(ticker)
        except Exception:
            pass
    return _read_json(config.NEWS_DIR / f"{ticker}.json")


# ---------------- SEC ----------------

def sec_get(url: str) -> requests.Response:
    time.sleep(0.15)  # SEC 限速 10 req/s，这里留足余量
    return _get(url, config.SEC_USER_AGENT, timeout=40)


def load_facts(ticker: str) -> dict:
    return _read_json(config.FACTS_DIR / f"{ticker.upper()}.json")
