"""工具注册表：一份定义，同时供 MCP server 与 Agent（OpenAI function calling）使用。"""
from __future__ import annotations

import json
import time
from typing import Any, Callable

from .filings import get_key_financials, search_filings
from .market import get_company_news, get_price_history, get_quote
from .orders import draft_order
from .risk import portfolio_risk

TICKER = {"type": "string", "description": "股票代码，支持 NVDA, MSFT, AAPL, TSLA, AMZN（行情另支持 QQQ）"}

TOOLS: dict[str, dict[str, Any]] = {
    "get_quote": {
        "fn": get_quote,
        "description": "查询最新日线收盘价、涨跌幅、52 周高低点（非实时）",
        "parameters": {"type": "object", "properties": {"ticker": TICKER}, "required": ["ticker"]},
    },
    "get_price_history": {
        "fn": get_price_history,
        "description": "查询最近 N 个交易日的收盘价序列和区间涨跌幅",
        "parameters": {"type": "object", "properties": {
            "ticker": TICKER, "days": {"type": "integer", "description": "交易日数，1-500，默认 30"}},
            "required": ["ticker"]},
    },
    "get_company_news": {
        "fn": get_company_news,
        "description": "查询公司近期新闻标题（Yahoo Finance RSS）",
        "parameters": {"type": "object", "properties": {
            "ticker": TICKER, "limit": {"type": "integer", "description": "条数，默认 5"}},
            "required": ["ticker"]},
    },
    "search_filings": {
        "fn": search_filings,
        "description": ("在最新 10-K / 10-Q 原文中检索（BM25），返回带 chunk_id 的段落。"
                        "回答财报相关问题必须先调用此工具，并在回答中用 [chunk_id] 引用。query 用英文关键词效果更好。"),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "检索语句，建议英文"},
            "ticker": TICKER,
            "form": {"type": "string", "enum": ["10-K", "10-Q"], "description": "可选，限定报告类型"},
            "k": {"type": "integer", "description": "返回条数，默认 5"}},
            "required": ["query"]},
    },
    "get_key_financials": {
        "fn": get_key_financials,
        "description": ("查询 SEC XBRL 结构化财务数据。可选指标: revenue, gross_profit, operating_income, net_income, "
                        "eps_diluted, rnd_expense, total_assets, total_liabilities, stockholders_equity, cash, "
                        "operating_cash_flow, capex"),
        "parameters": {"type": "object", "properties": {
            "ticker": TICKER,
            "metrics": {"type": "array", "items": {"type": "string"}, "description": "指标列表，不填返回全部"},
            "period": {"type": "string", "enum": ["annual", "quarterly"], "description": "默认 annual"},
            "limit": {"type": "integer", "description": "每个指标返回最近几期，默认 4"}},
            "required": ["ticker"]},
    },
    "portfolio_risk": {
        "fn": portfolio_risk,
        "description": "计算组合年化波动率、最大回撤、HHI 集中度、相对 QQQ 的 beta",
        "parameters": {"type": "object", "properties": {
            "holdings": {"type": "array", "description": "持仓列表，每项给 weight 或 shares", "items": {
                "type": "object", "properties": {
                    "ticker": {"type": "string"}, "weight": {"type": "number"}, "shares": {"type": "number"}},
                "required": ["ticker"]}},
            "lookback_days": {"type": "integer", "description": "回看交易日数，默认 252"}},
            "required": ["holdings"]},
    },
    "draft_order": {
        "fn": draft_order,
        "description": ("生成模拟订单草稿，状态为 PENDING_CONFIRMATION。不会执行真实交易。"
                        "订单必须经用户人工确认才生效，模型不能代替用户确认。"),
        "parameters": {"type": "object", "properties": {
            "ticker": TICKER,
            "side": {"type": "string", "enum": ["buy", "sell"]},
            "quantity": {"type": "integer", "description": "股数，正整数"},
            "order_type": {"type": "string", "enum": ["market", "limit"]},
            "limit_price": {"type": "number"}},
            "required": ["ticker", "side", "quantity"]},
    },
}


def openai_tools(names: list[str] | None = None) -> list[dict]:
    return [{"type": "function", "function": {"name": n, "description": t["description"],
                                              "parameters": t["parameters"]}}
            for n, t in TOOLS.items() if names is None or n in names]


def call_tool(name: str, args: dict | str | None) -> tuple[dict, float]:
    """执行工具，返回 (结果, 耗时毫秒)。错误以 {"error": ...} 返回，不抛出，便于模型自我纠正。"""
    t0 = time.perf_counter()
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except json.JSONDecodeError as e:
            return {"error": f"参数不是合法 JSON: {e}"}, (time.perf_counter() - t0) * 1000
    fn: Callable | None = TOOLS.get(name, {}).get("fn")
    if fn is None:
        return {"error": f"未知工具 {name}"}, (time.perf_counter() - t0) * 1000
    try:
        res = fn(**(args or {}))
    except TypeError as e:
        res = {"error": f"参数错误: {e}"}
    except Exception as e:  # noqa: BLE001
        res = {"error": f"{type(e).__name__}: {e}"}
    return res, (time.perf_counter() - t0) * 1000
