"""用 ScriptedLLM 验证 Agent 流水线（工具执行、确认闸门、记忆、轨迹、评分）。不访问任何模型 API。"""
import json

from finagent.agent.llm import ScriptedLLM
from finagent.agent.loop import FinAgent
from finagent.agent.memory import ShortTermMemory, UserProfile


def tc(i, name, args):
    return {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def test_tool_loop_and_trace():
    llm = ScriptedLLM([
        {"role": "assistant", "content": "计划：检索财报", "tool_calls": [
            tc(1, "search_filings", {"query": "largest direct customer revenue", "ticker": "NVDA", "k": 3})]},
        {"role": "assistant", "content": "最大客户占 22% [NVDA-10K-7-016]"},
    ])
    tr = FinAgent(llm).run("NVDA 最大客户占比？")
    assert tr.stop_reason == "answered"
    assert [s.kind for s in tr.steps] == ["llm", "tool", "llm"]
    assert tr.tags["citations"] == ["NVDA-10K-7-016"]
    assert tr.prompt_tokens == 200 and tr.est_cost_usd is None  # scripted 模型没有价格，不估算
    # 第二次模型调用能看到工具结果
    assert any(m["role"] == "tool" for m in llm.calls[1])


def test_order_gate_never_leaks_token_and_respects_denial():
    seen = []
    llm = ScriptedLLM([
        {"role": "assistant", "content": "", "tool_calls": [tc(1, "draft_order", {"ticker": "AAPL", "side": "buy", "quantity": 1})]},
        {"role": "assistant", "content": "订单已被您拒绝，未执行。"},
    ])
    agent = FinAgent(llm, confirm_fn=lambda o: seen.append(o) or False)
    tr = agent.run("买 1 股 AAPL")
    assert seen and "confirmation_token" not in seen[0]
    assert tr.tags["order_status"] == ["REJECTED_BY_USER"]
    tool_msgs = [m for m in llm.calls[1] if m["role"] == "tool"]
    assert "confirmation_token" not in tool_msgs[0]["content"]
    assert any(s.kind == "confirmation" for s in tr.steps)


def test_order_gate_approval():
    llm = ScriptedLLM([
        {"role": "assistant", "content": "", "tool_calls": [tc(1, "draft_order", {"ticker": "MSFT", "side": "buy", "quantity": 1})]},
        {"role": "assistant", "content": "模拟订单已确认。"},
    ])
    tr = FinAgent(llm, confirm_fn=lambda o: True).run("买 1 股 MSFT")
    assert tr.tags["order_status"] == ["SIMULATED_CONFIRMED"]


def test_guard_flags_and_profile_update(tmp_path):
    prof = UserProfile(tmp_path / "p.json")
    llm = ScriptedLLM([
        {"role": "assistant", "content": "", "tool_calls": [tc(1, "update_user_profile", {"risk_preference": "conservative"})]},
        {"role": "assistant", "content": "已记录"},
    ])
    tr = FinAgent(llm, profile=prof).run("我是保守型，保证收益的股票有吗")
    assert "guaranteed_return" in tr.tags["guard_flags"]
    assert json.loads((tmp_path / "p.json").read_text())["risk_preference"] == "conservative"
    assert any("合规提示" in m["content"] for m in llm.calls[0] if m["role"] == "system")


def test_max_steps_stops_loop():
    llm = ScriptedLLM([{"role": "assistant", "content": "", "tool_calls": [tc(i, "get_quote", {"ticker": "NVDA"})]}
                       for i in range(10)])
    tr = FinAgent(llm, max_steps=3).run("循环")
    assert tr.stop_reason == "max_steps" and len(tr.tool_calls()) == 3


def test_short_term_memory_window_keeps_pairs():
    m = ShortTermMemory(max_turns=2)
    for i in range(3):
        m.start_turn(f"q{i}")
        m.add({"role": "assistant", "content": "", "tool_calls": [{"id": f"x{i}"}]})
        m.add({"role": "tool", "tool_call_id": f"x{i}", "content": "{}"})
    msgs = m.messages()
    assert msgs[0]["content"] == "q1" and len(msgs) == 6


def test_trace_saved_as_jsonl(tmp_path):
    from finagent import config
    llm = ScriptedLLM([{"role": "assistant", "content": "你好"}])
    FinAgent(llm).run("hi")
    files = list(config.TRACE_DIR.glob("*.jsonl"))
    assert files and json.loads(files[0].read_text().splitlines()[0])["final_answer"] == "你好"
