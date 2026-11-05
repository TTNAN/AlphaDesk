"""不需要 API key 的流水线演示：LLM 回复由脚本预设（ScriptedLLM），工具调用、确认闸门、轨迹记录都是真实执行。

产出 traces/demo_scripted.jsonl，用于在 HTML 报告中展示轨迹格式。模型名记为 "scripted"，不代表任何真实模型的表现。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from finagent import config  # noqa: E402
from finagent.agent.llm import ScriptedLLM  # noqa: E402
from finagent.agent.loop import FinAgent  # noqa: E402
from finagent.agent.memory import UserProfile  # noqa: E402
from finagent.tools import orders  # noqa: E402


def tc(i, name, args):
    return {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def main():
    out = config.TRACE_DIR / "demo_scripted.jsonl"
    out.unlink(missing_ok=True)
    orders.ORDERS_PATH = config.DATA_DIR / "orders" / "demo_orders.json"
    profile = UserProfile(data={"holdings": [{"ticker": "NVDA", "shares": 100}, {"ticker": "AAPL", "shares": 50}],
                                "risk_preference": "balanced", "notes": ""})
    script = [
        {"role": "assistant", "content": "计划：先算组合风险，再检索英伟达客户集中度披露。", "tool_calls": [
            tc(1, "portfolio_risk", {"holdings": profile.data["holdings"]}),
            tc(2, "search_filings", {"query": "direct customer percentage of total revenue", "ticker": "NVDA", "k": 3})]},
        {"role": "assistant", "content": "（脚本回答）组合风险见工具结果；英伟达 2026 财年最大直接客户占营收 22% [NVDA-10K-7-016]。"},
        {"role": "assistant", "content": "计划：生成模拟订单，交给用户确认。", "tool_calls": [
            tc(3, "draft_order", {"ticker": "NVDA", "side": "sell", "quantity": 20})]},
        {"role": "assistant", "content": "（脚本回答）您拒绝了这张模拟订单，未执行任何交易。"},
    ]
    agent = FinAgent(ScriptedLLM(script), profile=profile, confirm_fn=lambda o: False, save_traces=False)
    for q in ["看看我组合的风险，另外英伟达客户集中度高吗？", "帮我卖 20 股 NVDA"]:
        tr = agent.run(q)
        tr.save(out)
        print(tr.run_id, tr.stop_reason, [s.name for s in tr.steps])
    print(out)


if __name__ == "__main__":
    main()
