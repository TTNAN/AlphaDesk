"""Agent 主循环：规划 → 工具调用 → 观察 → 回答。

- 工具层与 MCP server 共用 tools/registry.py。
- draft_order 经过人工确认闸门（HumanGate）：模型只能拿到不含 token 的待确认订单，
  是否确认由 confirm_fn（CLI 中为终端输入）决定，模型无法自行确认。
- 每次 run 生成完整 Trace（步骤、参数、耗时、token、估算成本）。
"""
from __future__ import annotations

import json
import re
import time
from typing import Callable

from ..tools import orders as order_tools
from ..tools.registry import TOOLS, call_tool, openai_tools
from .cost import estimate_cost
from .llm import LLM
from .memory import PROFILE_TOOL, ShortTermMemory, UserProfile
from .trace import Step, Trace

SYSTEM_PROMPT = """你是面向个人投资者和投顾的美股投研助手，覆盖 NVDA、MSFT、AAPL、TSLA、AMZN（QQQ 作为基准）。
工作方式：
1. 先用一两句话说明计划，再调用工具。数据必须来自工具结果，不要凭记忆给出价格或财务数字。
2. 财报相关问题先调用 search_filings（query 用英文关键词，带上 ticker），回答中用 [chunk_id] 标注引用，例如 [NVDA-10K-1A-063]。只引用工具真实返回过的 chunk_id。
3. 结构化财务数字优先用 get_key_financials；组合风险用 portfolio_risk。用户画像中有持仓时可直接使用。
4. 下单：只能调用 draft_order 生成模拟订单，系统会请用户人工确认。不得声称订单已成交，确认结果以工具返回的 status 为准。
5. 合规：拒绝承诺或暗示保证收益、拒绝利用内幕信息或操纵市场的请求，拒绝时说明原因，可以提供合规的替代帮助。
6. 效率：财报检索一次取 k=5 通常足够。结果中已有答案就直接回答，不要换关键词重复检索；同一问题最多检索 2 次。需要多个工具时在同一轮并行调用。
7. 不构成投资建议，必要时提示风险。用中文回答，简洁。"""

GUARD_PATTERNS = {
    "guaranteed_return": r"保证.{0,6}(收益|赚|回报|不亏)|稳赚|保本|guarantee[d]?\s+(return|profit)|零风险",
    "insider": r"内幕|未公开.{0,6}(消息|信息)|insider|提前知道.{0,10}(财报|消息)|操纵|拉盘",
}
CITATION_RE = re.compile(r"\[([A-Z]{2,5}-10[KQ]-[A-Z0-9-]+?-\d{3})\]")

ConfirmFn = Callable[[dict], bool]


def deny_all(_: dict) -> bool:
    return False


class FinAgent:
    def __init__(self, llm: LLM, profile: UserProfile | None = None, confirm_fn: ConfirmFn = deny_all,
                 max_steps: int = 8, memory_turns: int = 6, save_traces: bool = True):
        self.llm = llm
        self.profile = profile or UserProfile(data={"holdings": [], "risk_preference": None, "notes": ""})
        self.confirm_fn = confirm_fn
        self.max_steps = max_steps
        self.memory = ShortTermMemory(memory_turns)
        self.save_traces = save_traces
        self.tools = openai_tools() + [PROFILE_TOOL]

    # ---- 工具执行（含人工确认闸门）----
    def _exec_tool(self, name: str, raw_args: str, trace: Trace) -> dict:
        try:
            args = json.loads(raw_args or "{}")
        except json.JSONDecodeError as e:
            res = {"error": f"参数不是合法 JSON: {e}"}
            trace.add(Step(len(trace.steps), "tool", name, 0.0, None, json.dumps(res, ensure_ascii=False), error=res["error"]))
            return res
        t0 = time.perf_counter()
        if name == "update_user_profile":
            try:
                res = self.profile.update(**args)
            except Exception as e:  # noqa: BLE001
                res = {"error": str(e)}
        elif name == "draft_order":
            return self._order_with_gate(args, trace)
        elif name in TOOLS:
            res, _ = call_tool(name, args)
            if name == "search_filings" and isinstance(res, dict):
                trace.tags.setdefault("retrieved_chunks", []).extend(x["chunk_id"] for x in res.get("results", []))
        else:
            res = {"error": f"未知工具 {name}"}
        ms = (time.perf_counter() - t0) * 1000
        trace.add(Step(len(trace.steps), "tool", name, round(ms, 2), args,
                       json.dumps(res, ensure_ascii=False)[:600], error=res.get("error") if isinstance(res, dict) else None))
        return res

    def _order_with_gate(self, args: dict, trace: Trace) -> dict:
        t0 = time.perf_counter()
        try:
            order = order_tools.draft_order_with_token(**args)
        except Exception as e:  # noqa: BLE001
            res = {"error": f"{type(e).__name__}: {e}"}
            trace.add(Step(len(trace.steps), "tool", "draft_order", round((time.perf_counter() - t0) * 1000, 2),
                           args, json.dumps(res, ensure_ascii=False), error=res["error"]))
            return res
        public = order_tools._public(order)
        trace.add(Step(len(trace.steps), "tool", "draft_order", round((time.perf_counter() - t0) * 1000, 2),
                       args, json.dumps(public, ensure_ascii=False)[:600]))
        t1 = time.perf_counter()
        approved = bool(self.confirm_fn(public))
        if approved:
            res = order_tools.confirm_order(order["order_id"], order["confirmation_token"])
        else:
            res = order_tools.reject_order(order["order_id"])
        trace.add(Step(len(trace.steps), "confirmation", "human_gate", round((time.perf_counter() - t1) * 1000, 2),
                       {"order_id": order["order_id"]}, json.dumps({"approved": approved, "status": res["status"]})))
        trace.tags["confirmation_requested"] = True
        trace.tags.setdefault("order_status", []).append(res["status"])
        return res

    # ---- 主循环 ----
    def run(self, query: str, tags: dict | None = None) -> Trace:
        trace = Trace(query=query, model=self.llm.model, tags=dict(tags or {}))
        flags = [k for k, p in GUARD_PATTERNS.items() if re.search(p, query, re.I)]
        if flags:
            trace.tags["guard_flags"] = flags
        self.memory.start_turn(query)
        answer, reason = "", "max_steps"
        for _ in range(self.max_steps):
            sys_msgs = [{"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "system", "content": self.profile.as_prompt()}]
            if flags:
                sys_msgs.append({"role": "system", "content": f"合规提示：本条请求命中风险规则 {flags}，请按合规要求处理。"})
            t0 = time.perf_counter()
            try:
                msg, usage = self.llm.complete(sys_msgs + self.memory.messages(), self.tools)
            except Exception as e:  # noqa: BLE001
                trace.add(Step(len(trace.steps), "llm", self.llm.model, round((time.perf_counter() - t0) * 1000, 1),
                               error=f"{type(e).__name__}: {e}"))
                reason = "llm_error"
                break
            calls = msg.get("tool_calls") or []
            trace.add(Step(len(trace.steps), "llm", self.llm.model, round((time.perf_counter() - t0) * 1000, 1),
                           {"n_tool_calls": len(calls)}, (msg.get("content") or "")[:600],
                           usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)))
            self.memory.add(msg)
            if not calls:
                answer, reason = msg.get("content") or "", "answered"
                break
            for tc in calls:
                res = self._exec_tool(tc["function"]["name"], tc["function"].get("arguments", "{}"), trace)
                self.memory.add({"role": "tool", "tool_call_id": tc["id"],
                                 "content": json.dumps(res, ensure_ascii=False)[:6000]})
        trace.tags["citations"] = CITATION_RE.findall(answer)
        trace.finish(answer, reason, estimate_cost(self.llm.model, trace.prompt_tokens, trace.completion_tokens))
        if self.save_traces:
            trace.save()
        return trace
