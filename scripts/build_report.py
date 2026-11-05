"""把评测结果和运行轨迹汇总成一个静态 HTML：reports/eval_report.html

数据来源：eval/results/rag_eval.json、eval/results/agent_eval.json（有则展示）、eval/results/pytest.txt、traces/*.jsonl
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from finagent import config  # noqa: E402

RES = ROOT / "eval/results"


def esc(x) -> str:
    return html.escape(str(x))


def pct(x) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def table(headers, rows) -> str:
    h = "".join(f"<th>{esc(c)}</th>" for c in headers)
    b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>"


def section_tests() -> str:
    p = RES / "pytest.txt"
    if not p.exists():
        return "<p class=muted>待运行：python -m pytest -v</p>"
    txt = p.read_text()
    m = re.search(r"(\d+) passed", txt)
    f = re.search(r"(\d+) failed", txt)
    lines = [l for l in txt.splitlines() if "::" in l and ("PASSED" in l or "FAILED" in l)]
    rows = [[esc(l.split(" ")[0]), "<b class=ok>PASSED</b>" if "PASSED" in l else "<b class=bad>FAILED</b>"]
            for l in lines]
    return (f"<p><b>{m.group(1) if m else 0}</b> passed, <b>{f.group(1) if f else 0}</b> failed</p>"
            f"<details><summary>明细</summary>{table(['test', 'result'], rows)}</details>")


def section_rag() -> str:
    p = RES / "rag_eval.json"
    if not p.exists():
        return "<p class=muted>待运行：python eval/run_rag_eval.py</p>"
    d = json.loads(p.read_text())
    rows = []
    for stem, v in d.items():
        s = v["summary"]
        for setting, label in (("filtered_by_ticker", "按 ticker 过滤"), ("global", "全库")):
            m = s[setting]
            rows.append([esc(stem) + (" (默认)" if stem == "simple" else ""), label, pct(m["recall@1"]),
                         pct(m["recall@3"]), pct(m["recall@5"]), pct(m["recall@10"]), f"{m['mrr@10']:.3f}",
                         f"{m['avg_latency_ms']:.1f}"])
    main = d["simple"]
    miss = [p for p in main["per_question"] if not (p["filtered_rank"] and p["filtered_rank"] <= 5)]
    mrows = [[esc(p["id"]), esc(p["ticker"]), esc(p["question"]), esc(p["filtered_rank"] or ">10"),
              esc(", ".join(p["gold"][:2])), esc(", ".join(p["filtered_top3"]))] for p in miss]
    return (f"<p>{main['summary']['n_questions']} 道题，{main['summary']['n_chunks']} 个 chunk。</p>"
            + table(["分词", "设置", "R@1", "R@3", "R@5", "R@10", "MRR@10", "延迟 ms"], rows)
            + "<h3>未命中 top-5 的题目（默认配置，按 ticker 过滤）</h3>"
            + table(["id", "公司", "问题", "gold 排名", "gold chunk", "实际 top3"], mrows))


def section_agent() -> str:
    p = RES / "agent_eval.json"
    if not p.exists():
        return ("<p class=muted>待运行：需要设置 API_KEY / MODEL 后执行 python eval/agent_eval.py。"
                "评测集 32 个任务（事实问答+引用 10、多工具分析 10、下单确认 6、违规拒答 6）已就绪。</p>")
    d = json.loads(p.read_text())
    s = d["summary"]
    kv = [["模型", esc(s["model"])], ["任务数", s["n_tasks"]], ["任务成功率", pct(s["task_success_rate"])],
          ["工具选择准确率", pct(s["tool_selection_accuracy"]["rate"])],
          ["引用准确率", pct(s["citation_accuracy"]["rate"])],
          ["确认合规率", pct(s["confirmation_compliance"]["rate"])], ["拒答率", pct(s["refusal_rate"]["rate"])],
          ["平均延迟 ms", s["avg_latency_ms"]], ["平均 tokens (in/out)", f"{s['avg_prompt_tokens']} / {s['avg_completion_tokens']}"],
          ["平均成本 USD", s["avg_cost_usd"] if s["avg_cost_usd"] is not None else "未配置价格"]]
    cat = [[esc(k), pct(v["success_rate"]), v["n"]] for k, v in s["by_category"].items()]
    bc = [[esc(k), v] for k, v in sorted(s["badcase_counts"].items(), key=lambda x: -x[1])]
    bd = [[esc(b["id"]), esc(b["category"]), esc(b["query"]), esc(", ".join(b["labels"])), esc(", ".join(b["called"])),
           esc(b["answer"][:200])] for b in d["badcases"]]
    return (table(["指标", "值"], kv) + "<h3>分类别成功率</h3>" + table(["类别", "成功率", "n"], cat)
            + "<h3>Badcase 分类</h3>" + table(["标签", "次数"], bc)
            + "<h3>Badcase 明细</h3>" + table(["id", "类别", "问题", "标签", "调用工具", "回答片段"], bd))


def section_traces(limit: int = 8) -> str:
    files = sorted(config.TRACE_DIR.glob("*.jsonl"))
    traces = []
    for f in files:
        traces += [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l]
    if not traces:
        return "<p class=muted>暂无轨迹。运行 Agent（CLI 或 agent_eval）后会写入 traces/。</p>"
    out = ["<p class=muted>模型为 scripted 的轨迹来自 scripts/demo_scripted_trace.py：LLM 回复为预设脚本，"
           "工具调用与确认闸门为真实执行，仅用于展示轨迹格式，不代表模型表现。</p>"]
    for t in traces[-limit:]:
        steps = [[s["index"], esc(s["kind"]), esc(s["name"]), f"{s['latency_ms']:.1f}",
                  esc(json.dumps(s.get("args"), ensure_ascii=False)[:160]),
                  f"{s.get('prompt_tokens', 0)}/{s.get('completion_tokens', 0)}",
                  esc((s.get("output_preview") or s.get("error") or "")[:200])] for s in t["steps"]]
        out.append(f"<details><summary><code>{esc(t['run_id'])}</code> {esc(t['query'][:60])} · 模型 {esc(t['model'])} · "
                   f"{t['total_latency_ms']:.0f}ms · {esc(t['stop_reason'])}</summary>"
                   + table(["#", "类型", "名称", "ms", "参数", "tokens", "输出"], steps)
                   + f"<p><b>回答：</b>{esc(t['final_answer'][:800])}</p></details>")
    return "".join(out)


CSS = """body{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;max-width:1100px;margin:32px auto;
padding:0 16px;color:#222;line-height:1.5}h1{font-size:24px}h2{margin-top:36px;border-bottom:1px solid #ddd;padding-bottom:4px}
table{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0}th,td{border:1px solid #e3e3e3;padding:4px 6px;
text-align:left;vertical-align:top;word-break:break-word}th{background:#f6f6f6}.ok{color:#18794e}.bad{color:#c62828}
.muted{color:#777}td:first-child{white-space:nowrap}details{margin:6px 0}summary{cursor:pointer}code{font-size:12px}"""


def main() -> Path:
    body = (f"<h1>AlphaDesk 评测与轨迹报告</h1><p class=muted>由 scripts/build_report.py 生成，"
            f"生成时间 {config.now_iso()}。所有数字来自实际运行结果文件。</p>"
            f"<h2>1. 工具层单元测试 (pytest)</h2>{section_tests()}"
            f"<h2>2. RAG 检索评测</h2>{section_rag()}"
            f"<h2>3. Agent 级评测</h2>{section_agent()}"
            f"<h2>4. 最近运行轨迹</h2>{section_traces()}")
    out = config.REPORT_DIR / "eval_report.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"<!doctype html><html lang=zh><meta charset=utf-8><title>eval report</title>"
                   f"<style>{CSS}</style><body>{body}</body></html>", encoding="utf-8")
    print(out)
    return out


if __name__ == "__main__":
    main()
