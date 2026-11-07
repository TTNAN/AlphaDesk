import os
import stat
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import pytest

from finagent import config
from finagent.data_sources import load_prices
from finagent.tools import orders
from finagent.tools.registry import call_tool


@pytest.fixture(autouse=True)
def snapshot_prices_are_fresh(monkeypatch):
    """订单测试以快照的最新行情日期为基准，避免多年后测试被旧快照时效影响。"""
    latest = max(date.fromisoformat(load_prices(t)["rows"][-1]["date"]) for t in config.PRICE_TICKERS)
    monkeypatch.setattr(orders, "_utc_today", lambda: latest)


def test_draft_hides_token_and_is_pending():
    res, _ = call_tool("draft_order", {"ticker": "AAPL", "side": "buy", "quantity": 2})
    assert res["status"] == "PENDING_CONFIRMATION" and res["simulated"] is True
    assert "confirmation_token" not in res


def test_confirm_requires_correct_token():
    order = orders.draft_order_with_token("MSFT", "buy", 1)
    with pytest.raises(ValueError):
        orders.confirm_order(order["order_id"], "wrong")
    done = orders.confirm_order(order["order_id"], order["confirmation_token"])
    assert done["status"] == "SIMULATED_CONFIRMED"
    with pytest.raises(ValueError):  # 不能重复确认
        orders.confirm_order(order["order_id"], order["confirmation_token"])


def test_reject_and_expiry(monkeypatch):
    order = orders.draft_order_with_token("TSLA", "sell", 1)
    assert orders.reject_order(order["order_id"])["status"] == "REJECTED_BY_USER"
    order2 = orders.draft_order_with_token("TSLA", "sell", 1)
    import time
    monkeypatch.setattr(time, "time", lambda: order2["token_expires"] + 1)
    with pytest.raises(ValueError, match="过期"):
        orders.confirm_order(order2["order_id"], order2["confirmation_token"])


@pytest.mark.parametrize("args", [
    {"ticker": "AAPL", "side": "hold", "quantity": 1},
    {"ticker": "AAPL", "side": "buy", "quantity": 0},
    {"ticker": "AAPL", "side": "buy", "quantity": 1.5},
    {"ticker": "AAPL", "side": "buy", "quantity": 1, "order_type": "limit"},
    {"ticker": "AAPL", "side": "buy", "quantity": 1, "order_type": "limit", "limit_price": float("nan")},
    {"ticker": "AAPL", "side": "buy", "quantity": 1, "order_type": "limit", "limit_price": float("inf")},
    {"ticker": "AAPL", "side": "buy", "quantity": float("inf")},
    {"ticker": "AAPL", "side": "buy", "quantity": 100000},
    {"ticker": "QQQ", "side": "buy", "quantity": 1},
])
def test_invalid_orders_return_error(args):
    res, _ = call_tool("draft_order", args)
    assert "error" in res


def test_registry_unknown_tool_and_bad_json():
    assert "error" in call_tool("nope", {})[0]
    assert "error" in call_tool("get_quote", "{bad json")[0]
    assert "error" in call_tool("get_quote", {"symbol": "NVDA"})[0]


def test_split_orders_cannot_bypass_limit():
    """拆成多笔小单也不能绕过单笔 10 万美元上限。"""
    price = orders.load_prices("MSFT")["rows"][-1]["close"]
    qty = int(60_000 // price)
    orders.draft_order("MSFT", "buy", qty)
    with pytest.raises(ValueError, match="拆单"):
        orders.draft_order("MSFT", "buy", qty)
    orders.draft_order("MSFT", "sell", qty)  # 反方向单独计算


def test_market_order_rejects_stale_price(monkeypatch):
    today = orders._utc_today()
    monkeypatch.setattr(orders, "_utc_today", lambda: today + timedelta(days=config.MAX_MARKET_DATA_AGE_DAYS + 1))
    with pytest.raises(ValueError, match="过旧"):
        orders.draft_order("AAPL", "buy", 1)


def test_explicit_limit_order_does_not_need_market_cache(monkeypatch):
    today = orders._utc_today()
    monkeypatch.setattr(orders, "_utc_today", lambda: today + timedelta(days=365))
    order = orders.draft_order("AAPL", "buy", 1, "limit", 100.0)
    assert order["ref_price"] == 100.0


def test_order_ledger_is_private_on_posix():
    if os.name == "nt":
        pytest.skip("POSIX permission bits are not portable to Windows")
    orders.draft_order("AAPL", "buy", 1)
    assert stat.S_IMODE(orders.ORDERS_PATH.stat().st_mode) == 0o600
    assert stat.S_IMODE(orders.ORDERS_PATH.with_name(orders.ORDERS_PATH.name + ".lock").stat().st_mode) == 0o600


def test_concurrent_orders_cannot_bypass_cumulative_limit():
    price = load_prices("MSFT")["rows"][-1]["close"]
    quantity = int(60_000 // price)

    def draft():
        try:
            return orders.draft_order("MSFT", "buy", quantity)
        except ValueError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: draft(), range(2)))
    accepted = [result for result in results if isinstance(result, dict)]
    assert len(accepted) == 1
    assert len(orders.list_orders()) == 1
