"""组合风险指标：年化波动率、最大回撤、集中度（HHI）、相对 QQQ 的 beta。

口径：
- 使用复权收盘价的日收益率，按 252 个交易日年化。
- 组合收益按固定权重每日再平衡计算（简化假设）。
- 持仓可以给 weight，也可以给 shares（按最新收盘价折算市值权重）。
- 重复标的会先合并；同一组合必须统一用 weight 或 shares。
"""
from __future__ import annotations

import math

import numpy as np

from .. import config
from ..data_sources import load_prices


def _returns(ticker: str, lookback: int) -> tuple[list[str], np.ndarray]:
    rows = load_prices(ticker)["rows"][-(lookback + 1):]
    if len(rows) < 3:
        raise ValueError(f"{ticker} 行情不足，至少需要三个复权收盘价")
    px = np.array([r["adj_close"] for r in rows], dtype=float)
    if not np.all(np.isfinite(px)) or np.any(px <= 0):
        raise ValueError(f"{ticker} 行情包含非有限值或非正复权价格")
    returns = px[1:] / px[:-1] - 1
    if not np.all(np.isfinite(returns)):
        raise ValueError(f"{ticker} 收益率包含非有限值")
    return [r["date"] for r in rows[1:]], returns


def max_drawdown(returns: np.ndarray) -> float:
    nav = np.cumprod(1 + returns)
    peak = np.maximum.accumulate(np.concatenate([[1.0], nav]))[1:]
    return float(np.min(nav / peak - 1))


def portfolio_risk(holdings: list[dict], lookback_days: int = 252) -> dict:
    if not holdings:
        raise ValueError("holdings 不能为空")
    lookback = max(20, min(int(lookback_days), 480))
    position_values: dict[str, float] = {}
    basis: str | None = None
    for holding in holdings:
        if not isinstance(holding, dict):
            raise ValueError("每项持仓必须是对象")
        ticker = str(holding.get("ticker", "")).strip().upper()
        if ticker not in config.PRICE_TICKERS:
            raise ValueError(f"不支持的代码 {ticker}")
        has_weight = holding.get("weight") is not None
        has_shares = holding.get("shares") is not None
        if has_weight == has_shares:
            raise ValueError(f"{ticker} 每项持仓需要且只能提供 weight 或 shares")
        this_basis = "weight" if has_weight else "shares"
        if basis is not None and this_basis != basis:
            raise ValueError("同一组合请统一使用 weight 或 shares，不能混用")
        basis = this_basis
        try:
            value = float(holding["weight"] if has_weight else holding["shares"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{ticker} 的 {this_basis} 必须是有限数字") from exc
        if not math.isfinite(value) or value < 0 or (this_basis == "shares" and value == 0):
            raise ValueError(f"{ticker} 的 {this_basis} 必须是有限且有效的非负值")
        if this_basis == "shares":
            try:
                price = float(load_prices(ticker)["rows"][-1]["close"])
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise ValueError(f"{ticker} 缺少可用的最新收盘价") from exc
            if not math.isfinite(price) or price <= 0:
                raise ValueError(f"{ticker} 最新收盘价无效")
            value *= price
        if not math.isfinite(value):
            raise ValueError(f"{ticker} 的持仓市值不是有限数字")
        position_values[ticker] = position_values.get(ticker, 0.0) + value
        if not math.isfinite(position_values[ticker]):
            raise ValueError(f"{ticker} 的合并持仓不是有限数字")

    tickers = list(position_values)
    raw = [position_values[ticker] for ticker in tickers]
    total = math.fsum(raw)
    if not math.isfinite(total) or total <= 0:
        raise ValueError("持仓权重总和必须是有限正数")
    w = np.array(raw, dtype=float) / total

    series = {ticker: dict(zip(*_returns(ticker, lookback)))
              for ticker in set(tickers) | {config.BENCHMARK}}
    common = sorted(set.intersection(*(set(values) for values in series.values())))
    if len(common) < 2:
        raise ValueError("标的与 QQQ 的共同历史数据不足，至少需要两个日收益率")
    R = np.array([[series[ticker][day] for day in common] for ticker in tickers])
    bench = np.array([series[config.BENCHMARK][day] for day in common])
    if not np.all(np.isfinite(R)) or not np.all(np.isfinite(bench)):
        raise ValueError("行情收益率包含非有限值")
    bench_var = float(bench.var(ddof=1))
    if not math.isfinite(bench_var) or bench_var <= 0:
        raise ValueError("QQQ 基准收益率方差无效，无法计算 beta")
    port = w @ R
    ann = math.sqrt(252)
    per_asset = []
    for index, ticker in enumerate(tickers):
        returns = R[index]
        per_asset.append({
            "ticker": ticker, "weight": round(float(w[index]), 4),
            "ann_vol": round(float(returns.std(ddof=1) * ann), 4),
            "max_drawdown": round(max_drawdown(returns), 4),
            "beta": round(float(np.cov(returns, bench, ddof=1)[0, 1] / bench_var), 3),
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
            "beta_vs_qqq": round(float(np.cov(port, bench, ddof=1)[0, 1] / bench_var), 3),
            "period_return": round(float(np.prod(1 + port) - 1), 4),
            "hhi": round(hhi, 4), "max_weight": round(float(w.max()), 4),
        },
        "assets": per_asset,
        "warnings": warnings,
        "method": "日收益率，252 日年化，固定权重每日再平衡，基准 QQQ",
    }
