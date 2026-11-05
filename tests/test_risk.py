import numpy as np
import pytest

from finagent.tools.risk import max_drawdown, portfolio_risk


def test_max_drawdown_known_series():
    r = np.array([0.10, -0.50, 0.20])  # nav 1.1 -> 0.55 -> 0.66
    assert max_drawdown(r) == pytest.approx(-0.5)


def test_single_asset_weights_and_beta_of_benchmark():
    res = portfolio_risk([{"ticker": "QQQ", "weight": 1}])
    assert res["portfolio"]["beta_vs_qqq"] == pytest.approx(1.0, abs=1e-6)
    assert res["portfolio"]["hhi"] == 1.0


def test_weights_normalised_and_concentration_warning():
    res = portfolio_risk([{"ticker": "NVDA", "weight": 3}, {"ticker": "AAPL", "weight": 1}])
    w = {a["ticker"]: a["weight"] for a in res["assets"]}
    assert w["NVDA"] == pytest.approx(0.75)
    assert res["warnings"]


def test_shares_converted_to_weights():
    res = portfolio_risk([{"ticker": "MSFT", "shares": 10}, {"ticker": "AMZN", "shares": 10}])
    assert sum(a["weight"] for a in res["assets"]) == pytest.approx(1.0, abs=1e-3)


def test_diversification_lowers_vol():
    a = portfolio_risk([{"ticker": "NVDA", "weight": 1}])["portfolio"]["ann_vol"]
    b = portfolio_risk([{"ticker": "NVDA", "weight": 1}, {"ticker": "AAPL", "weight": 1},
                        {"ticker": "MSFT", "weight": 1}])["portfolio"]["ann_vol"]
    assert b < a


def test_invalid_inputs():
    with pytest.raises(ValueError):
        portfolio_risk([])
    with pytest.raises(ValueError):
        portfolio_risk([{"ticker": "NVDA"}])
