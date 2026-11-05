"""在线拉取所有数据并写入 data/cache，之后演示与评测都可离线复现。

用法:
    SEC_USER_AGENT="your-name your@email.com" python scripts/fetch_data.py [--only prices,news,filings,facts]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import warnings  # noqa: E402

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning  # noqa: E402

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from finagent import config, data_sources as ds  # noqa: E402

FACT_CONCEPTS = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "rnd_expense": ["ResearchAndDevelopmentExpense"],
    "total_assets": ["Assets"],
    "total_liabilities": ["Liabilities"],
    "stockholders_equity": ["StockholdersEquity"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
}


def log(*a):
    print(*a, flush=True)


def do_prices():
    for t in config.PRICE_TICKERS:
        obj = ds.refresh_prices(t)
        log(f"[prices] {t}: {len(obj['rows'])} rows via {obj['source']}, last={obj['rows'][-1]['date']}")


def do_news():
    for t in config.COMPANIES:
        try:
            obj = ds.refresh_news(t)
            log(f"[news] {t}: {len(obj['items'])} items")
        except Exception as e:  # 新闻源失败不影响其他数据
            log(f"[news] {t}: FAILED {e}")


def html_to_text(html: bytes) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    # 隐藏的 XBRL 头部
    for tag in soup.find_all(style=re.compile(r"display:\s*none")):
        tag.decompose()
    text = soup.get_text("\n")
    text = text.replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    out, prev_blank = [], False
    for ln in lines:
        if not ln:
            if not prev_blank:
                out.append("")
            prev_blank = True
        else:
            out.append(ln)
            prev_blank = False
    return "\n".join(out)


def latest_filings(cik: str) -> dict:
    sub = ds.sec_get(f"https://data.sec.gov/submissions/CIK{cik}.json").json()
    r = sub["filings"]["recent"]
    found = {}
    for i, form in enumerate(r["form"]):
        if form in ("10-K", "10-Q") and form not in found:
            found[form] = {
                "form": form, "accession": r["accessionNumber"][i], "filing_date": r["filingDate"][i],
                "report_date": r["reportDate"][i], "primary_doc": r["primaryDocument"][i],
            }
        if len(found) == 2:
            break
    return found


def do_filings():
    for t, meta in config.COMPANIES.items():
        cik = meta["cik"]
        for form, f in latest_filings(cik).items():
            acc = f["accession"].replace("-", "")
            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{f['primary_doc']}"
            html = ds.sec_get(url).content
            text = html_to_text(html)
            f.update({"ticker": t, "company": meta["name"], "cik": cik, "url": url,
                      "fetched_at": config.now_iso()})
            out = config.FILINGS_DIR / f"{t}_{form}.txt"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
            (config.FILINGS_DIR / f"{t}_{form}.meta.json").write_text(json.dumps(f, indent=1))
            log(f"[filings] {t} {form} {f['report_date']} -> {len(text)//1000}k chars")


def do_facts():
    for t, meta in config.COMPANIES.items():
        raw = ds.sec_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{meta['cik']}.json").json()
        gaap = raw["facts"].get("us-gaap", {})
        out = {"ticker": t, "company": raw.get("entityName"), "cik": meta["cik"],
               "source": f"https://data.sec.gov/api/xbrl/companyfacts/CIK{meta['cik']}.json",
               "fetched_at": config.now_iso(), "metrics": {}}
        for key, concepts in FACT_CONCEPTS.items():
            best = None
            for c in concepts:
                if c not in gaap:
                    continue
                units = gaap[c]["units"]
                unit = "USD" if "USD" in units else next(iter(units))
                rows = [x for x in units[unit] if x.get("form") in ("10-K", "10-Q")]
                if not rows:
                    continue
                latest_end = max(x["end"] for x in rows)
                if best is None or latest_end > best[2]:
                    best = (c, unit, latest_end, rows)
            if not best:
                continue
            c, unit, _, rows = best
            dedup = {}
            for x in rows:  # 同一期间取最新提交
                k = (x.get("start"), x["end"])
                if k not in dedup or x["filed"] > dedup[k]["filed"]:
                    dedup[k] = x
            rows = sorted(dedup.values(), key=lambda x: (x["end"], x.get("start") or ""))[-24:]
            out["metrics"][key] = {"concept": c, "unit": unit, "values": [
                {k: x.get(k) for k in ("start", "end", "val", "fy", "fp", "form", "filed", "accn")} for x in rows]}
        ds._write_json(config.FACTS_DIR / f"{t}.json", out)
        log(f"[facts] {t}: {len(out['metrics'])} metrics")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="prices,news,filings,facts")
    args = ap.parse_args()
    steps = {"prices": do_prices, "news": do_news, "filings": do_filings, "facts": do_facts}
    for s in args.only.split(","):
        steps[s.strip()]()
