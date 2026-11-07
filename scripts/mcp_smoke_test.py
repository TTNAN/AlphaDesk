"""用官方 MCP Python 客户端通过 stdio 连接本项目的 MCP server，列出工具并逐个调用一次。

用法: python scripts/mcp_smoke_test.py
测试订单会写入临时目录，不会污染用户的模拟订单账本。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent

CALLS = [
    ("get_quote", {"ticker": "NVDA"}),
    ("get_price_history", {"ticker": "MSFT", "days": 5}),
    ("get_company_news", {"ticker": "AAPL", "limit": 2}),
    ("search_filings", {"query": "export license H20 China", "ticker": "NVDA", "k": 2}),
    ("get_key_financials", {"ticker": "AMZN", "metrics": ["revenue"], "period": "annual", "limit": 2}),
    ("portfolio_risk", {"holdings": [{"ticker": "NVDA", "weight": 0.6}, {"ticker": "AAPL", "weight": 0.4}]}),
    ("draft_order", {"ticker": "AAPL", "side": "buy", "quantity": 1,
                     "order_type": "limit", "limit_price": 100.0}),
]


async def main() -> int:
    with tempfile.TemporaryDirectory(prefix="alphadesk-smoke-") as state_dir:
        env = {**os.environ, "FINAGENT_HOME": state_dir, "FINAGENT_OFFLINE": "1"}
        params = StdioServerParameters(command=sys.executable, args=["-m", "finagent.mcp_server"],
                                       cwd=str(ROOT), env=env)
        ok = 0
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = [tool.name for tool in tools.tools]
                print("tools:", names)
                for name, args in CALLS:
                    started = time.perf_counter()
                    response = await session.call_tool(name, args)
                    text = response.content[0].text
                    data = json.loads(text)
                    status = "error" if "error" in data else "ok"
                    ok += status == "ok"
                    print(f"{name:20s} {status:5s} {(time.perf_counter()-started)*1000:7.1f}ms  {text[:110]}")
                    if name == "draft_order":
                        assert "confirmation_token" not in data, "token 不应返回给模型"
        print(f"{ok}/{len(CALLS)} calls ok")
        return 0 if ok == len(CALLS) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
