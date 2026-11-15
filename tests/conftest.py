import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """订单与轨迹写到临时目录，不污染仓库。"""
    from finagent import config
    from finagent.tools import orders

    monkeypatch.setattr(orders, "ORDERS_PATH", tmp_path / "orders.json")
    monkeypatch.setattr(config, "TRACE_DIR", tmp_path / "traces")
    yield

@pytest.fixture(autouse=True)
def snapshot_prices_are_fresh(monkeypatch):
    """把“今天”钉在快照的最新行情日期，避免墙上时钟越过快照 7 天有效期后测试变红。"""
    from datetime import date

    from finagent import config
    from finagent.data_sources import load_prices
    from finagent.tools import orders

    latest = max(date.fromisoformat(load_prices(t)["rows"][-1]["date"]) for t in config.PRICE_TICKERS)
    monkeypatch.setattr(orders, "_utc_today", lambda: latest)
