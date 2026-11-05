"""MCP server（stdio）。把 tools/registry.py 中的同一套工具暴露给 Claude Desktop、Cursor 等 MCP 客户端。

启动: python -m finagent.mcp_server
兼容 mcp 1.x（FastMCP）与 2.x（MCPServer）。
"""
from __future__ import annotations

import json
import logging
import sys
import warnings

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from .tools.registry import call_tool

warnings.filterwarnings("ignore")
logging.basicConfig(stream=sys.stderr, level=logging.WARNING)  # stdio 模式下 stdout 只能输出协议消息

mcp = _Server(
    "fin-advisor",
    instructions=(
        "美股投研工具集（NVDA/MSFT/AAPL/TSLA/AMZN）。行情为日线收盘价。财报问答请先调用 search_filings 并用 [chunk_id] 引用。"
        "draft_order 只生成模拟订单，必须由用户在本地运行 `python -m finagent.orders confirm <order_id>` 人工确认，"
        "模型不能代替用户确认，也不存在任何真实交易通道。"
    ),
)


def _run(name: str, **kwargs) -> str:
    args = {k: v for k, v in kwargs.items() if v is not None}
    res, _ = call_tool(name, args)
    return json.dumps(res, ensure_ascii=False)


@mcp.tool()
def get_quote(ticker: str) -> str:
    """查询最新日线收盘价、涨跌幅、52 周高低点（非实时）。ticker: NVDA/MSFT/AAPL/TSLA/AMZN/QQQ"""
    return _run("get_quote", ticker=ticker)


@mcp.tool()
def get_price_history(ticker: str, days: int = 30) -> str:
    """查询最近 N 个交易日收盘价和区间涨跌幅。"""
    return _run("get_price_history", ticker=ticker, days=days)


@mcp.tool()
def get_company_news(ticker: str, limit: int = 5) -> str:
    """查询公司近期新闻标题（Yahoo Finance RSS 缓存）。"""
    return _run("get_company_news", ticker=ticker, limit=limit)


@mcp.tool()
def search_filings(query: str, ticker: str | None = None, form: str | None = None, k: int = 5) -> str:
    """在最新 10-K/10-Q 原文中做 BM25 检索，返回带 chunk_id 的段落。回答时用 [chunk_id] 引用。query 建议用英文。"""
    return _run("search_filings", query=query, ticker=ticker, form=form, k=k)


@mcp.tool()
def get_key_financials(ticker: str, metrics: list[str] | None = None, period: str = "annual",
                       limit: int = 4) -> str:
    """查询 SEC XBRL 结构化财务数据（revenue, net_income, eps_diluted, operating_cash_flow, capex 等）。"""
    return _run("get_key_financials", ticker=ticker, metrics=metrics, period=period, limit=limit)


@mcp.tool()
def portfolio_risk(holdings: list[dict], lookback_days: int = 252) -> str:
    """计算组合年化波动率、最大回撤、HHI 集中度、相对 QQQ 的 beta。holdings 例: [{"ticker":"NVDA","weight":0.6}]"""
    return _run("portfolio_risk", holdings=holdings, lookback_days=lookback_days)


@mcp.tool()
def draft_order(ticker: str, side: str, quantity: int, order_type: str = "market",
                limit_price: float | None = None) -> str:
    """生成模拟订单（PENDING_CONFIRMATION）。不执行真实交易。需用户在本地 CLI 人工确认。"""
    return _run("draft_order", ticker=ticker, side=side, quantity=quantity, order_type=order_type,
                limit_price=limit_price)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
