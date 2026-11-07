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
import math
import os
import secrets
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator

from .. import config
from ..data_sources import load_prices

ORDERS_PATH = config.DATA_DIR / "orders" / "orders.json"
MAX_NOTIONAL = 100_000  # 单笔模拟订单名义金额上限（美元），超过直接拒绝
TOKEN_TTL_SECONDS = 600


def _load() -> dict:
    if not ORDERS_PATH.exists():
        return {}
    orders = json.loads(ORDERS_PATH.read_text(encoding="utf-8"))
    if not isinstance(orders, dict):
        raise ValueError("订单记录格式无效；为避免丢失数据，已停止操作")
    return orders


@contextmanager
def _ledger_lock() -> Iterator[None]:
    """跨进程锁住订单读-改-写事务（POSIX/Windows）。"""
    ORDERS_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = ORDERS_PATH.with_name(ORDERS_PATH.name + ".lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, "r+b") as lock_file:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _save(orders: dict) -> None:
    ORDERS_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp_path = ORDERS_PATH.with_name(f".{ORDERS_PATH.name}.{uuid.uuid4().hex}.tmp")
    fd = os.open(temp_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(orders, stream, indent=1, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, ORDERS_PATH)
        if os.name != "nt":
            os.chmod(ORDERS_PATH, 0o600)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _market_reference_price(ticker: str) -> float:
    data = load_prices(ticker)
    rows = data.get("rows") or []
    if not rows:
        raise ValueError(f"{ticker} 没有可用的行情数据，无法生成市价模拟订单")
    try:
        as_of = date.fromisoformat(str(rows[-1]["date"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{ticker} 行情日期无效，无法生成市价模拟订单") from exc
    age_days = (_utc_today() - as_of).days
    if age_days < 0:
        raise ValueError(f"{ticker} 行情日期 {as_of} 晚于当前日期，无法生成市价模拟订单")
    if age_days > config.MAX_MARKET_DATA_AGE_DAYS:
        raise ValueError(
            f"{ticker} 最新收盘价日期为 {as_of}，已过旧（{age_days} 天）；"
            f"市价模拟订单要求行情不超过 {config.MAX_MARKET_DATA_AGE_DAYS} 天。"
            "请联网刷新行情后重试，或改用明确限价。"
        )
    try:
        price = float(rows[-1]["close"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{ticker} 最新收盘价无效，无法生成市价模拟订单") from exc
    if not math.isfinite(price) or price <= 0:
        raise ValueError(f"{ticker} 最新收盘价必须是大于零的有限数值")
    return price


def _recent_notional(ticker: str, side: str) -> float:
    """10 分钟内同一标的、同方向、未作废订单的名义金额合计，用来阻止拆单绕过单笔上限。"""
    cutoff = time.time() - TOKEN_TTL_SECONDS
    total = 0.0
    for order in _load().values():
        if order.get("ticker") != ticker or order.get("side") != side:
            continue
        if order.get("status") not in ("PENDING_CONFIRMATION", "SIMULATED_CONFIRMED"):
            continue
        try:
            notional = float(order.get("est_notional", 0))
            created = float(order.get("token_expires", 0)) - TOKEN_TTL_SECONDS
        except (TypeError, ValueError) as exc:
            raise ValueError("订单记录包含无效金额或时间；为安全起见已停止新增订单") from exc
        if not math.isfinite(notional) or not math.isfinite(created) or notional < 0:
            raise ValueError("订单记录包含无效金额或时间；为安全起见已停止新增订单")
        if created >= cutoff:
            total += notional
    return total


def _public(order: dict) -> dict:
    return {k: v for k, v in order.items() if k not in ("confirmation_token", "token_expires")}


def draft_order(ticker: str, side: str, quantity: float, order_type: str = "market",
                limit_price: float | None = None) -> dict:
    """返回给模型的结果不包含 token。内部调用方用 draft_order_with_token 获取 token。"""
    return _public(draft_order_with_token(ticker, side, quantity, order_type, limit_price))


def draft_order_with_token(ticker: str, side: str, quantity: float, order_type: str = "market",
                           limit_price: float | None = None) -> dict:
    t = (ticker or "").strip().upper()
    if t not in config.COMPANIES:
        raise ValueError(f"不支持的代码 {ticker}")
    side = (side or "").strip().lower()
    if side not in ("buy", "sell"):
        raise ValueError("side 只能是 buy 或 sell")
    try:
        quantity = float(quantity)
    except (TypeError, ValueError) as exc:
        raise ValueError("quantity 必须是正整数") from exc
    if not math.isfinite(quantity) or quantity <= 0 or not quantity.is_integer():
        raise ValueError("quantity 必须是正整数")
    order_type = str(order_type or "").strip().lower()
    if order_type not in ("market", "limit"):
        raise ValueError("order_type 只能是 market 或 limit")
    if order_type == "limit":
        try:
            price = float(limit_price)
        except (TypeError, ValueError) as exc:
            raise ValueError("限价单需要大于零的有限 limit_price") from exc
        if not math.isfinite(price) or price <= 0:
            raise ValueError("限价单需要大于零的有限 limit_price")
        limit_price = price
        ref_price = price
    else:
        ref_price = _market_reference_price(t)
    raw_notional = ref_price * quantity
    if not math.isfinite(raw_notional):
        raise ValueError("订单名义金额不是有限数值，已拒绝")
    notional = round(raw_notional, 2)
    if notional > MAX_NOTIONAL:
        raise ValueError(f"名义金额 {notional} 超过单笔上限 {MAX_NOTIONAL}，已拒绝")

    order = {
        "order_id": "SIM-" + uuid.uuid4().hex[:8].upper(),
        "ticker": t, "side": side, "quantity": int(quantity), "order_type": order_type,
        "limit_price": limit_price, "ref_price": round(ref_price, 4), "est_notional": notional,
        "status": "PENDING_CONFIRMATION",
        "simulated": True,
        "created_at": config.now_iso(),
        "requires_human_confirmation": True,
        "message": "模拟订单已生成，等待用户人工确认。本系统不会执行真实交易。",
        "confirmation_token": secrets.token_hex(8),
        "token_expires": time.time() + TOKEN_TTL_SECONDS,
    }
    # 限额检查与落盘必须处于同一互斥事务中，防止并发请求同时绕过累计上限。
    with _ledger_lock():
        recent = _recent_notional(t, side)
        if recent + notional > MAX_NOTIONAL:
            raise ValueError(f"10 分钟内同一标的同方向订单累计 {round(recent + notional, 2)} 美元，超过上限 {MAX_NOTIONAL}。"
                             "疑似拆单绕过单笔上限，已拒绝。不要继续拆单，请告知用户上限。")
        orders = _load()
        orders[order["order_id"]] = order
        _save(orders)
    return order


def confirm_order(order_id: str, confirmation_token: str) -> dict:
    with _ledger_lock():
        orders = _load()
        order = orders.get(order_id)
        if not order:
            raise ValueError(f"订单不存在: {order_id}")
        if order["status"] != "PENDING_CONFIRMATION":
            raise ValueError(f"订单状态为 {order['status']}，不能确认")
        if time.time() > order["token_expires"]:
            order["status"] = "EXPIRED"
            _save(orders)
            raise ValueError("确认 token 已过期")
        if not secrets.compare_digest(str(confirmation_token), order["confirmation_token"]):
            raise ValueError("确认 token 不正确")
        order["status"] = "SIMULATED_CONFIRMED"
        order["confirmed_at"] = config.now_iso()
        order["message"] = "用户已确认。订单仅在本地模拟记账，未发送到任何交易系统。"
        _save(orders)
        return _public(order)


def reject_order(order_id: str) -> dict:
    with _ledger_lock():
        orders = _load()
        order = orders.get(order_id)
        if not order:
            raise ValueError(f"订单不存在: {order_id}")
        if order["status"] == "PENDING_CONFIRMATION":
            order["status"] = "REJECTED_BY_USER"
            order["message"] = "用户拒绝，订单已作废。"
            _save(orders)
        return _public(order)


def list_orders() -> list[dict]:
    with _ledger_lock():
        return [_public(order) for order in _load().values()]
