"""两层记忆。

- 短期记忆 ShortTermMemory：本次会话的消息历史，按轮次滑动窗口截断，保证 tool 消息与其 assistant 调用成对保留。
- 用户画像 UserProfile：持仓、风险偏好、备注，持久化到 data/user_profile.json，每轮注入 system prompt。
  模型可通过 update_user_profile 工具更新画像（只允许白名单字段）。
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import config

RISK_LEVELS = ("conservative", "balanced", "aggressive")


class ShortTermMemory:
    def __init__(self, max_turns: int = 6):
        self.max_turns = max_turns
        self.turns: list[list[dict]] = []  # 每个 turn 是一组消息，以 user 消息开头

    def start_turn(self, user_msg: str) -> None:
        self.turns.append([{"role": "user", "content": user_msg}])
        self.turns = self.turns[-self.max_turns:]

    def add(self, msg: dict) -> None:
        self.turns[-1].append(msg)

    def messages(self) -> list[dict]:
        return [m for t in self.turns for m in t]


class UserProfile:
    FIELDS = ("holdings", "risk_preference", "notes")

    def __init__(self, path: Path | None = None, data: dict | None = None):
        self.path = path
        if data is not None:
            self.data = data
        elif path and path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
        else:
            self.data = {"holdings": [], "risk_preference": None, "notes": ""}

    def save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")

    def update(self, holdings: list[dict] | None = None, risk_preference: str | None = None,
               notes: str | None = None) -> dict:
        if holdings is not None:
            clean = []
            for h in holdings:
                t = str(h.get("ticker", "")).upper()
                if t not in config.PRICE_TICKERS:
                    raise ValueError(f"不支持的代码 {t}")
                item = {"ticker": t}
                for k in ("shares", "weight"):
                    if h.get(k) is not None:
                        item[k] = float(h[k])
                clean.append(item)
            self.data["holdings"] = clean
        if risk_preference is not None:
            if risk_preference not in RISK_LEVELS:
                raise ValueError(f"risk_preference 只能是 {RISK_LEVELS}")
            self.data["risk_preference"] = risk_preference
        if notes is not None:
            self.data["notes"] = str(notes)[:500]
        self.save()
        return {"ok": True, "profile": self.data}

    def as_prompt(self) -> str:
        return "用户画像（长期记忆）: " + json.dumps(self.data, ensure_ascii=False)


PROFILE_TOOL = {
    "type": "function",
    "function": {
        "name": "update_user_profile",
        "description": "当用户明确告知持仓或风险偏好时，更新用户画像。只记录用户亲口说明的信息。",
        "parameters": {"type": "object", "properties": {
            "holdings": {"type": "array", "items": {"type": "object", "properties": {
                "ticker": {"type": "string"}, "shares": {"type": "number"}, "weight": {"type": "number"}},
                "required": ["ticker"]}},
            "risk_preference": {"type": "string", "enum": list(RISK_LEVELS)},
            "notes": {"type": "string"}}},
    },
}


def default_profile() -> UserProfile:
    return UserProfile(config.PROFILE_PATH)
