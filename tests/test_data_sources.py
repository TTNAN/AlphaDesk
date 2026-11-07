import pytest

from finagent import config, data_sources


def test_online_price_fallback_discloses_refresh_failure(monkeypatch):
    monkeypatch.setattr(config, "OFFLINE", False)

    def fail_refresh(_ticker):
        raise TimeoutError("provider timed out")

    monkeypatch.setattr(data_sources, "refresh_prices", fail_refresh)
    result = data_sources.load_prices("AAPL")
    assert result["refresh_status"] == "cached_after_refresh_failure"
    assert result["refresh_error_type"] == "TimeoutError"


def test_sec_online_request_requires_real_user_agent(monkeypatch):
    monkeypatch.setattr(config, "SEC_USER_AGENT", "")
    with pytest.raises(ValueError, match="SEC_USER_AGENT"):
        data_sources.sec_get("https://www.sec.gov/Archives/example")
