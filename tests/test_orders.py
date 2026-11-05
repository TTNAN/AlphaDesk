import pytest

from finagent.tools import orders
from finagent.tools.registry import call_tool


def test_draft_hides_token_and_is_pending():
    res, _ = call_tool("draft_order", {"ticker": "AAPL", "side": "buy", "quantity": 2})
    assert res["status"] == "PENDING_CONFIRMATION" and res["simulated"] is True
    assert "confirmation_token" not in res


def test_confirm_requires_correct_token():
    o = orders.draft_order_with_token("MSFT", "buy", 1)
    with pytest.raises(ValueError):
        orders.confirm_order(o["order_id"], "wrong")
    done = orders.confirm_order(o["order_id"], o["confirmation_token"])
    assert done["status"] == "SIMULATED_CONFIRMED"
    with pytest.raises(ValueError):  # 不能重复确认
        orders.confirm_order(o["order_id"], o["confirmation_token"])


def test_reject_and_expiry(monkeypatch):
    o = orders.draft_order_with_token("TSLA", "sell", 1)
    assert orders.reject_order(o["order_id"])["status"] == "REJECTED_BY_USER"
    o2 = orders.draft_order_with_token("TSLA", "sell", 1)
    import time
    monkeypatch.setattr(time, "time", lambda: o2["token_expires"] + 1)
    with pytest.raises(ValueError, match="过期"):
        orders.confirm_order(o2["order_id"], o2["confirmation_token"])


@pytest.mark.parametrize("args", [
    {"ticker": "AAPL", "side": "hold", "quantity": 1},
    {"ticker": "AAPL", "side": "buy", "quantity": 0},
    {"ticker": "AAPL", "side": "buy", "quantity": 1.5},
    {"ticker": "AAPL", "side": "buy", "quantity": 1, "order_type": "limit"},
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
