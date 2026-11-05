import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """订单与轨迹写到临时目录，不污染仓库。"""
    from finagent import config
    from finagent.tools import orders

    monkeypatch.setattr(orders, "ORDERS_PATH", tmp_path / "orders.json")
    monkeypatch.setattr(config, "TRACE_DIR", tmp_path / "traces")
    yield
