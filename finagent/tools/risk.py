"""组合风险指标：年化波动率、最大回撤、集中度（HHI）、相对 QQQ 的 beta。

口径：
- 使用复权收盘价的日收益率，按 252 个交易日年化。
- 组合收益按固定权重每日再平衡计算（简化假设）。
- 持仓可以给 weight，也可以给 shares（按最新收盘价折算市值权重）。
"""
from __future__ import annotations

import math

import numpy as np

from .. import config
from ..data_sources import load_prices


def _returns(ticker: str, lookback: int) -> tuple[list[str], np.ndarray]:
    rows = load_prices(ticker)["rows"][-(lookback + 1):]
    px = np.array([r["adj_close"] for r in rows], dtype=float)
    return [r["date"] for r in rows[1:]], px[1:] / px[:-1] - 1


def max_drawdown(returns: np.ndarray) -> float:
    nav = np.cumprod(1 + returns)
    peak = np.maximum.accumulate(np.concatenate([[1.0], nav]))[1:]
    return float(np.min(nav / peak - 1))


def portfolio_risk(holdings: list[dict], lookback_days: int = 252) -> dict:
    if not holdings:
        raise ValueError("holdings 不能为空")
    lookback = max(20, min(int(lookback_days), 480))
    tickers, raw = [], []
    for h in holdings:
        t = str(h.get("ticker", "")).upper()
        if t not in config.PRICE_TICKERS:
            raise ValueError(f"不支持的代码 {t}")
        if h.get("weight") is not None:
            raw.append(float(h["weight"]))
        elif h.get("shares") is not None:
            raw.append(float(h["shares"]) * load_prices(t)["rows"][-1]["close"])
        else:
            raise ValueError(f"{t} 需要提供 weight 或 shares")
        tickers.append(t)
    if any(w < 0 for w in raw) or sum(raw) <= 0:
        raise ValueError("权重必须为正")
    w = np.array(raw) / sum(raw)

    series = {t: dict(zip(*_returns(t, lookback))) for t in set(tickers) | {config.BENCHMARK}}
    common = sorted(set.intersection(*(set(s) for s in series.values())))
    R = np.array([[series[t][d] for d in common] for t in tickers])  # assets x days
    bench = np.array([series[config.BENCHMARK][d] for d in common])
    port = w @ R

    ann = math.sqrt(252)
    per_asset = []
    for i, t in enumerate(tickers):
        r = R[i]
        per_asset.append({
            "ticker": t, "weight": round(float(w[i]), 4),
            "ann_vol": round(float(r.std(ddof=1) * ann), 4),
            "max_drawdown": round(max_drawdown(r), 4),
            "beta": round(float(np.cov(r, bench, ddof=1)[0, 1] / bench.var(ddof=1)), 3),
        })
    hhi = float(np.sum(w ** 2))
    warnings = []
    if w.max() > 0.4:
        warnings.append(f"单一持仓权重 {w.max():.0%} 超过 40%")
    if hhi > 0.3:
        warnings.append(f"HHI={hhi:.2f}，集中度偏高")
    return {
        "start": common[0], "end": common[-1], "n_days": len(common),
        "portfolio": {
            "ann_vol": round(float(port.std(ddof=1) * ann), 4),
            "max_drawdown": round(max_drawdown(port), 4),
            "beta_vs_qqq": round(float(np.cov(port, bench, ddof=1)[0, 1] / bench.var(ddof=1)), 3),
            "period_return": round(float(np.prod(1 + port) - 1), 4),
            "hhi": round(hhi, 4), "max_weight": round(float(w.max()), 4),
        },
        "assets": per_asset,
        "warnings": warnings,
        "method": "日收益率，252 日年化，固定权重每日再平衡，基准 QQQ",
    }
