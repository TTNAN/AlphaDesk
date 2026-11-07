import os
from pathlib import Path

import pytest

from finagent import config


def test_checkout_runtime_state_defaults_to_private_home():
    if os.getenv("FINAGENT_HOME"):
        pytest.skip("FINAGENT_HOME 已显式设置")
    assert config._WORK == Path.home() / ".alphadesk"
    assert config.DATA_DIR == Path.home() / ".alphadesk" / "data"
    assert config.CACHE_DIR == config.ROOT / "data" / "cache"
