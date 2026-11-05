"""运行轨迹记录。每次 run 输出一行 JSONL 到 traces/YYYYMMDD.jsonl，包含每一步的模型调用与工具调用。"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field

from .. import config


@dataclass
class Step:
    index: int
    kind: str                 # "llm" | "tool" | "confirmation"
    name: str
    latency_ms: float
    args: dict | None = None
    output_preview: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str | None = None


@dataclass
class Trace:
    query: str
    model: str
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: str = field(default_factory=config.now_iso)
    steps: list[Step] = field(default_factory=list)
    final_answer: str = ""
    stop_reason: str = ""
    total_latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    est_cost_usd: float | None = None
    tags: dict = field(default_factory=dict)
    _t0: float = field(default_factory=time.perf_counter, repr=False)

    def add(self, step: Step) -> None:
        self.steps.append(step)
        self.prompt_tokens += step.prompt_tokens
        self.completion_tokens += step.completion_tokens

    def tool_calls(self) -> list[Step]:
        return [s for s in self.steps if s.kind == "tool"]

    def finish(self, answer: str, reason: str, cost: float | None) -> None:
        self.final_answer = answer
        self.stop_reason = reason
        self.est_cost_usd = cost
        self.total_latency_ms = round((time.perf_counter() - self._t0) * 1000, 1)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("_t0", None)
        return d

    def save(self, path=None) -> str:
        path = path or config.TRACE_DIR / f"{self.started_at[:10].replace('-', '')}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(self.to_dict(), ensure_ascii=False) + "\n")
        return str(path)
