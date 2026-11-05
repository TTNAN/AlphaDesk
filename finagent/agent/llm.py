"""LLM 适配层。任何 OpenAI 兼容接口都可用（DeepSeek / Qwen / Kimi / OpenAI）。

环境变量:
    BASE_URL   例 https://api.deepseek.com 、https://dashscope.aliyuncs.com/compatible-mode/v1 、https://api.moonshot.cn/v1
    API_KEY
    MODEL      例 deepseek-flash 、qwen-plus 、kimi-k2 、gpt-4o-mini
也兼容 OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL。
"""
from __future__ import annotations

import os
from typing import Protocol


class LLM(Protocol):
    model: str

    def complete(self, messages: list[dict], tools: list[dict]) -> tuple[dict, dict]:
        """返回 (assistant_message, usage)。assistant_message 为 OpenAI 格式的 dict。"""
        ...


def env_config() -> dict:
    return {
        "base_url": os.getenv("BASE_URL") or os.getenv("OPENAI_BASE_URL"),
        "api_key": os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY"),
        "model": os.getenv("MODEL") or os.getenv("OPENAI_MODEL"),
    }


class OpenAICompatLLM:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None,
                 temperature: float = 0.0, timeout: float = 60.0):
        from openai import OpenAI

        cfg = env_config()
        self.model = model or cfg["model"]
        key = api_key or cfg["api_key"]
        if not key or not self.model:
            raise RuntimeError("缺少 API_KEY 或 MODEL 环境变量，见 README 快速开始")
        self.client = OpenAI(base_url=base_url or cfg["base_url"], api_key=key, timeout=timeout)
        self.temperature = temperature
        # 推理型模型（如智谱 GLM-5.x）默认开启思考，延迟高。设置 FINAGENT_THINKING=disabled 关闭。
        self.extra_body = None
        if os.getenv("FINAGENT_THINKING", "").lower() == "disabled":
            self.extra_body = {"thinking": {"type": "disabled"}}

    def complete(self, messages: list[dict], tools: list[dict]) -> tuple[dict, dict]:
        resp = self.client.chat.completions.create(
            model=self.model, messages=messages, tools=tools or None, temperature=self.temperature,
            extra_body=self.extra_body)
        m = resp.choices[0].message
        msg: dict = {"role": "assistant", "content": m.content or ""}
        if m.tool_calls:
            msg["tool_calls"] = [{"id": tc.id, "type": "function",
                                  "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                                 for tc in m.tool_calls]
        u = resp.usage
        usage = {"prompt_tokens": getattr(u, "prompt_tokens", 0) or 0,
                 "completion_tokens": getattr(u, "completion_tokens", 0) or 0}
        return msg, usage


class ScriptedLLM:
    """测试用：按脚本依次返回预设的 assistant 消息，不访问网络。只用于验证 Agent 流水线，不产生模型指标。"""

    def __init__(self, script: list[dict], model: str = "scripted"):
        self.script = list(script)
        self.model = model
        self.calls: list[list[dict]] = []

    def complete(self, messages: list[dict], tools: list[dict]) -> tuple[dict, dict]:
        self.calls.append(list(messages))
        if not self.script:
            return {"role": "assistant", "content": "（脚本结束）"}, {"prompt_tokens": 0, "completion_tokens": 0}
        return self.script.pop(0), {"prompt_tokens": 100, "completion_tokens": 20}
