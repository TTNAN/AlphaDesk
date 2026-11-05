"""通过官方 MCP 客户端以 stdio 启动 server，验证工具列表与调用。"""
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = {"get_quote", "get_price_history", "get_company_news", "search_filings",
            "get_key_financials", "portfolio_risk", "draft_order"}


async def _run():
    params = StdioServerParameters(command=sys.executable, args=["-m", "finagent.mcp_server"], cwd=str(ROOT))
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            q = json.loads((await s.call_tool("get_quote", {"ticker": "AAPL"})).content[0].text)
            sf = json.loads((await s.call_tool("search_filings", {"query": "cybersecurity", "ticker": "MSFT", "k": 2})).content[0].text)
            return names, q, sf


def test_mcp_stdio_roundtrip():
    names, q, sf = asyncio.run(_run())
    assert EXPECTED <= names
    assert q["ticker"] == "AAPL"
    assert len(sf["results"]) == 2
