"""全局配置。路径、标的池、数据源请求头。"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_PKG = Path(__file__).resolve().parent

# 两种运行方式：
# 1) 克隆仓库运行：数据在仓库 data/ 下。
# 2) pip / uvx 安装运行：只读缓存随包安装在 finagent/_data/cache，
#    可写文件（索引、模拟订单、trace）放到 FINAGENT_HOME，默认 ~/.alphadesk。
if (ROOT / "data" / "cache").is_dir() and not os.getenv("FINAGENT_HOME"):
    DATA_DIR = ROOT / "data"
    CACHE_DIR = DATA_DIR / "cache"
    _WORK = ROOT
else:
    _WORK = Path(os.getenv("FINAGENT_HOME", str(Path.home() / ".alphadesk")))
    DATA_DIR = _WORK / "data"
    CACHE_DIR = _PKG / "_data" / "cache"
    if not CACHE_DIR.is_dir() and (ROOT / "data" / "cache").is_dir():
        CACHE_DIR = ROOT / "data" / "cache"
PRICES_DIR = CACHE_DIR / "prices"
FILINGS_DIR = CACHE_DIR / "filings"
FACTS_DIR = CACHE_DIR / "facts"
NEWS_DIR = CACHE_DIR / "news"
INDEX_DIR = DATA_DIR / "index"
TRACE_DIR = _WORK / "traces"
REPORT_DIR = _WORK / "reports"
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
