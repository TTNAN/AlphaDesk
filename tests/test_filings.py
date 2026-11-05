import re

import pytest

from finagent.rag.chunker import load_chunks, split_sections
from finagent.tools.filings import get_key_financials, search_filings
from finagent import config

CID = re.compile(r"^[A-Z]{4}-10[KQ]-(P\d-)?\d{1,2}[A-C]?-\d{3}$")


def test_chunk_ids_unique_and_well_formed():
    chunks = load_chunks()
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))
    assert all(CID.match(i) for i in ids)
    assert {c.ticker for c in chunks} == set(config.COMPANIES)


def test_every_filing_has_risk_factors_and_mdna():
    chunks = load_chunks()
    for t in config.COMPANIES:
        secs = {(c.form, c.section) for c in chunks if c.ticker == t}
        assert ("10-K", "Item 1A") in secs and ("10-K", "Item 7") in secs, t
        assert ("10-Q", "Part I Item 2") in secs, t


def test_split_sections_drops_table_of_contents():
    text = "Item 1.\nItem 1A.\n\nItem 1. Business\n" + "word " * 200 + "\nItem 1A. Risk Factors\n" + "risk " * 200
    secs = dict((k, b) for k, _, b in split_sections(text, "10-K"))
    assert set(secs) == {"Item 1", "Item 1A"}
    assert "risk" not in secs["Item 1"]


def test_search_filings_filter_and_citation():
    res = search_filings("export license H20 China", ticker="NVDA", k=3)
    assert len(res["results"]) == 3
    for r in res["results"]:
        assert r["ticker"] == "NVDA"
        assert r["citation"].startswith(f"[{r['chunk_id']}]")
    assert any("H20" in r["text"] for r in res["results"])


def test_search_filings_form_filter():
    res = search_filings("risk factors", ticker="AAPL", form="10-Q", k=5)
    assert all(r["form"] == "10-Q" for r in res["results"])


def test_search_filings_rejects_empty_and_unknown():
    with pytest.raises(ValueError):
        search_filings("  ")
    with pytest.raises(ValueError):
        search_filings("revenue", ticker="GOOG")


def test_key_financials_annual_durations():
    f = get_key_financials("NVDA", metrics=["revenue", "total_assets"], period="annual")
    rev = f["metrics"]["revenue"]["values"]
    assert rev and all(v["form"] == "10-K" for v in rev)
    assert f["metrics"]["total_assets"]["values"][0]["start"] is None


def test_key_financials_quarterly_and_unknown_metric():
    f = get_key_financials("MSFT", metrics=["revenue", "foo"], period="quarterly", limit=2)
    assert len(f["metrics"]["revenue"]["values"]) == 2
    assert f["unknown_metrics"] == ["foo"]
