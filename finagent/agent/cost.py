"""成本估算。价格表只收录核对过官方页面的模型，其他模型通过环境变量自行配置。

环境变量（优先级最高，单位：美元 / 百万 tokens）:
    FINAGENT_PRICE_INPUT_PER_M, FINAGENT_PRICE_OUTPUT_PER_M
"""
from __future__ import annotations

import os

# 来源: https://api-docs.deepseek.com/quick_start/pricing （2026-11-05 查阅）
# 取高峰时段、缓存未命中的输入价格，作为保守估计。
PRICING = {
    "deepseek-flash": {"input": 0.30, "output": 1.20, "source": "https://api-docs.deepseek.com/quick_start/pricing",
                       "checked": "2026-11-05", "note": "peak, cache miss"},
    "deepseek-v4-pro": {"input": 1.32, "output": 3.96, "source": "https://api-docs.deepseek.com/quick_start/pricing",
                        "checked": "2026-11-05", "note": "peak, cache miss"},
}


def price_for(model: str) -> dict | None:
    pin, pout = os.getenv("FINAGENT_PRICE_INPUT_PER_M"), os.getenv("FINAGENT_PRICE_OUTPUT_PER_M")
    if pin and pout:
        return {"input": float(pin), "output": float(pout), "source": "env"}
    return PRICING.get(model)


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    p = price_for(model)
    if not p:
        return None  # 未配置价格时不估算，避免编造
    return round(prompt_tokens / 1e6 * p["input"] + completion_tokens / 1e6 * p["output"], 6)
