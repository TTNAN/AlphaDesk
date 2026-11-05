"""模拟下单。本模块不连接任何券商，不会执行任何真实交易。

流程：
1. draft_order 生成一张 PENDING_CONFIRMATION 状态的模拟订单，同时生成一次性确认 token。
2. token 只写入本地 data/orders/orders.json 并交给人工确认环节，不返回给模型。
3. 只有人工在 CLI 中确认（或调用方持有 token 调用 confirm_order）后，订单才变为 SIMULATED_CONFIRMED。
   即便确认，也只是记账，仍然不会发往任何交易系统。

人工确认入口：python -m finagent.orders list / confirm <order_id> / reject <order_id>
"""
from __future__ import annotations

import json
import secrets
import time
import uuid

from .. import config
from ..data_sources import load_prices

ORDERS_PATH = config.DATA_DIR / "orders" / "orders.json"
MAX_NOTIONAL = 100_000  # 单笔模拟订单名义金额上限（美元），超过直接拒绝
TOKEN_TTL_SECONDS = 600


def _load() -> dict:
    if ORDERS_PATH.exists():
        return json.loads(ORDERS_PATH.read_text())
    return {}


def _save(orders: dict) -> None:
    ORDERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ORDERS_PATH.write_text(json.dumps(orders, indent=1, ensure_ascii=False))


def _public(o: dict) -> dict:
    return {k: v for k, v in o.items() if k not in ("confirmation_token", "token_expires")}


def draft_order(ticker: str, side: str, quantity: float, order_type: str = "market",
                limit_price: float | None = None) -> dict:
    """返回给模型的结果不包含 token。内部调用方用 draft_order_with_token 获取 token。"""
    return _public(draft_order_with_token(ticker, side, quantity, order_type, limit_price))


def draft_order_with_token(ticker: str, side: str, quantity: float, order_type: str = "market",
                           limit_price: float | None = None) -> dict:
    t = (ticker or "").upper()
    if t not in config.COMPANIES:
        raise ValueError(f"不支持的代码 {ticker}")
    side = (side or "").lower()
    if side not in ("buy", "sell"):
        raise ValueError("side 只能是 buy 或 sell")
    quantity = float(quantity)
    if quantity <= 0 or quantity != int(quantity):
        raise ValueError("quantity 必须是正整数")
    if order_type not in ("market", "limit"):
        raise ValueError("order_type 只能是 market 或 limit")
    if order_type == "limit" and (limit_price is None or float(limit_price) <= 0):
        raise ValueError("限价单需要正的 limit_price")
    ref_price = float(limit_price) if order_type == "limit" else load_prices(t)["rows"][-1]["close"]
    notional = round(ref_price * quantity, 2)
    if notional > MAX_NOTIONAL:
        raise ValueError(f"名义金额 {notional} 超过单笔上限 {MAX_NOTIONAL}，已拒绝")
    order = {
        "order_id": "SIM-" + uuid.uuid4().hex[:8].upper(),
        "ticker": t, "side": side, "quantity": int(quantity), "order_type": order_type,
        "limit_price": float(limit_price) if limit_price else None,
        "ref_price": round(ref_price, 4), "est_notional": notional,
        "status": "PENDING_CONFIRMATION",
        "simulated": True,
        "created_at": config.now_iso(),
        "requires_human_confirmation": True,
        "message": "模拟订单已生成，等待用户人工确认。本系统不会执行真实交易。",
        "confirmation_token": secrets.token_hex(8),
        "token_expires": time.time() + TOKEN_TTL_SECONDS,
    }
    orders = _load()
    orders[order["order_id"]] = order
    _save(orders)
    return order


def confirm_order(order_id: str, confirmation_token: str) -> dict:
    orders = _load()
    o = orders.get(order_id)
    if not o:
        raise ValueError(f"订单不存在: {order_id}")
    if o["status"] != "PENDING_CONFIRMATION":
        raise ValueError(f"订单状态为 {o['status']}，不能确认")
    if time.time() > o["token_expires"]:
        o["status"] = "EXPIRED"
        _save(orders)
        raise ValueError("确认 token 已过期")
    if not secrets.compare_digest(str(confirmation_token), o["confirmation_token"]):
        raise ValueError("确认 token 不正确")
    o["status"] = "SIMULATED_CONFIRMED"
    o["confirmed_at"] = config.now_iso()
    o["message"] = "用户已确认。订单仅在本地模拟记账，未发送到任何交易系统。"
    _save(orders)
    return _public(o)


def reject_order(order_id: str) -> dict:
    orders = _load()
    o = orders.get(order_id)
    if not o:
        raise ValueError(f"订单不存在: {order_id}")
    if o["status"] == "PENDING_CONFIRMATION":
        o["status"] = "REJECTED_BY_USER"
        o["message"] = "用户拒绝，订单已作废。"
        _save(orders)
    return _public(o)


def list_orders() -> list[dict]:
    return [_public(o) for o in _load().values()]
