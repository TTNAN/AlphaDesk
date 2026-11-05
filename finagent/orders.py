"""人工确认 CLI。MCP 客户端（Claude Desktop / Cursor）下单只会生成待确认订单，确认在这里完成。

    python -m finagent.orders list
    python -m finagent.orders confirm SIM-XXXXXXXX
    python -m finagent.orders reject  SIM-XXXXXXXX
"""
from __future__ import annotations

import json
import sys

from .tools import orders as o


def main(argv: list[str]) -> int:
    if not argv or argv[0] == "list":
        for x in o.list_orders():
            print(json.dumps(x, ensure_ascii=False))
        return 0
    cmd, oid = argv[0], argv[1]
    if cmd == "reject":
        print(json.dumps(o.reject_order(oid), ensure_ascii=False))
        return 0
    if cmd == "confirm":
        raw = o._load().get(oid)
        if not raw:
            print("订单不存在")
            return 1
        print(json.dumps(o._public(raw), ensure_ascii=False, indent=1))
        ans = input(f"确认这张模拟订单？请输入订单号 {oid} 以确认，其他输入视为拒绝: ").strip()
        if ans == oid:
            print(json.dumps(o.confirm_order(oid, raw["confirmation_token"]), ensure_ascii=False))
        else:
            print(json.dumps(o.reject_order(oid), ensure_ascii=False))
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
