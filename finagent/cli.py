"""命令行入口。

    python -m finagent.cli chat                 # 交互式对话（需要 API_KEY / MODEL）
    python -m finagent.cli ask "NVDA 最大客户占比多少？"
    python -m finagent.cli tools                # 不需要 API key，演示只读工具层
"""
from __future__ import annotations

import argparse
import json
import sys

from .tools.registry import call_tool


def cli_confirm(order: dict) -> bool:
    print("\n" + "=" * 60)
    print("需要人工确认的模拟订单（不会执行真实交易）:")
    for k in ("order_id", "ticker", "side", "quantity", "order_type", "limit_price", "ref_price", "est_notional"):
        print(f"  {k:14s} {order.get(k)}")
    ans = input("确认请输入 yes，其他输入视为拒绝: ").strip().lower()
    print("=" * 60)
    return ans == "yes"


def print_trace(tr) -> None:
    for s in tr.steps:
        if s.kind == "llm":
            plan = (s.output_preview or "").replace("\n", " ")
            print(f"  [llm   {s.latency_ms:7.0f}ms] tokens {s.prompt_tokens}/{s.completion_tokens}"
                  + (f"  {plan[:120]}" if plan and s.args and s.args.get("n_tool_calls") else ""))
        else:
            print(f"  [{s.kind[:5]:5s} {s.latency_ms:7.1f}ms] {s.name} {json.dumps(s.args, ensure_ascii=False)[:120]}")
    cost = f"${tr.est_cost_usd:.5f}" if tr.est_cost_usd is not None else "未配置价格"
    print(f"  total {tr.total_latency_ms:.0f}ms, tokens {tr.prompt_tokens}+{tr.completion_tokens}, cost {cost}, "
          f"stop={tr.stop_reason}")


def make_agent():
    from .agent.llm import OpenAICompatLLM
    from .agent.loop import FinAgent
    from .agent.memory import default_profile

    return FinAgent(OpenAICompatLLM(), profile=default_profile(), confirm_fn=cli_confirm)


def tools_demo() -> None:
    demos = [
        ("get_quote", {"ticker": "NVDA"}),
        ("search_filings", {"query": "largest direct customer percentage of revenue", "ticker": "NVDA", "k": 2}),
        ("get_key_financials", {"ticker": "MSFT", "metrics": ["revenue", "net_income"], "period": "annual", "limit": 2}),
        ("portfolio_risk", {"holdings": [{"ticker": "NVDA", "weight": 0.5}, {"ticker": "TSLA", "weight": 0.3},
                                         {"ticker": "AAPL", "weight": 0.2}]}),
    ]
    for name, args in demos:
        res, ms = call_tool(name, args)
        print(f"\n### {name} {json.dumps(args, ensure_ascii=False)}  ({ms:.1f}ms)")
        print(json.dumps(res, ensure_ascii=False, indent=1)[:1500])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="finagent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("chat")
    a = sub.add_parser("ask")
    a.add_argument("query")
    sub.add_parser("tools")
    args = ap.parse_args(argv)

    if args.cmd == "tools":
        tools_demo()
        return 0
    try:
        agent = make_agent()
    except RuntimeError as e:
        print(f"{e}\n不需要 API key 的演示: python -m finagent.cli tools")
        return 2
    if args.cmd == "ask":
        tr = agent.run(args.query)
        print_trace(tr)
        if tr.stop_reason == "llm_error":
            detail = next((s.error for s in reversed(tr.steps) if s.error), "模型服务请求失败")
            print(f"模型请求失败: {detail}", file=sys.stderr)
            return 1
        print("\n" + tr.final_answer)
        return 0
    print("输入问题，Ctrl-D 退出。")
    while True:
        try:
            q = input("\n你> ").strip()
        except EOFError:
            return 0
        if not q:
            continue
        tr = agent.run(q)
        print_trace(tr)
        if tr.stop_reason == "llm_error":
            detail = next((s.error for s in reversed(tr.steps) if s.error), "模型服务请求失败")
            print(f"模型请求失败: {detail}", file=sys.stderr)
            continue
        print("\n助手> " + tr.final_answer)


if __name__ == "__main__":
    sys.exit(main())
