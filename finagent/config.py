"""全局配置。路径、标的池、数据源请求头。"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
PRICES_DIR = CACHE_DIR / "prices"
FILINGS_DIR = CACHE_DIR / "filings"
FACTS_DIR = CACHE_DIR / "facts"
NEWS_DIR = CACHE_DIR / "news"
INDEX_DIR = DATA_DIR / "index"
TRACE_DIR = ROOT / "traces"
REPORT_DIR = ROOT / "reports"
PROFILE_PATH = DATA_DIR / "user_profile.json"

# SEC 要求请求头带上联系方式，见 https://www.sec.gov/os/accessing-edgar-data
SEC_USER_AGENT = os.getenv(
    "SEC_USER_AGENT", "AlphaDesk research project contact@example.com"
)
HTTP_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AlphaDesk/0.1"

# 标的池：5 家纳斯达克公司 + QQQ 作为 beta 基准
COMPANIES = {
    "NVDA": {"cik": "0001045810", "name": "NVIDIA Corp"},
    "MSFT": {"cik": "0000789019", "name": "Microsoft Corp"},
    "AAPL": {"cik": "0000320193", "name": "Apple Inc"},
    "TSLA": {"cik": "0001318605", "name": "Tesla Inc"},
    "AMZN": {"cik": "0001018724", "name": "Amazon.com Inc"},
}
BENCHMARK = "QQQ"
PRICE_TICKERS = list(COMPANIES) + [BENCHMARK]

# 离线模式：只读缓存，不发网络请求。评测默认开启，保证可复现。
OFFLINE = os.getenv("FINAGENT_OFFLINE", "1") == "1"


def now_iso() -> str:
    """UTC 时间戳，手动格式化（ISO 8601）。"""
    import time
    from datetime import datetime, timezone
    d = datetime.fromtimestamp(time.time(), timezone.utc)
    return f"{d.year:04d}-{d.month:02d}-{d.day:02d}T{d.hour:02d}:{d.minute:02d}:{d.second:02d}Z"
