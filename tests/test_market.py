import pytest

from finagent.data_sources import load_prices
from finagent.tools.market import get_company_news, get_price_history, get_quote


def test_quote_fields_and_consistency():
    q = get_quote("nvda")
    rows = load_prices("NVDA")["rows"]
    assert q["ticker"] == "NVDA"
    assert q["close"] == round(rows[-1]["close"], 4)
    assert q["change_pct"] == round((rows[-1]["close"] / rows[-2]["close"] - 1) * 100, 3)
    assert q["low_52w"] <= q["close"] <= q["high_52w"]


def test_price_history_length_and_return():
    h = get_price_history("AAPL", days=10)
    assert h["n"] == 10 and len(h["rows"]) == 10
    assert h["rows"][0]["date"] < h["rows"][-1]["date"]


def test_price_history_clamps_days():
    assert get_price_history("MSFT", days=10_000)["n"] <= 500


def test_unknown_ticker_rejected():
    with pytest.raises(ValueError):
        get_quote("GME")


def test_news_cached():
    n = get_company_news("TSLA", limit=3)
    assert 1 <= len(n["items"]) <= 3
    assert all(i["title"] for i in n["items"])
