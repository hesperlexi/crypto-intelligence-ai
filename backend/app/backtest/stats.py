"""Performance statistics shared by the event-driven backtester, the vector benchmarks and paper trading."""
from __future__ import annotations

from typing import Any

import numpy as np

from ..data.base import bars_per_year


def max_drawdown(equity: np.ndarray) -> float:
    if len(equity) == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    return float((equity / peak - 1).min())


def equity_stats(equity: np.ndarray, timeframe: str) -> dict[str, float | None]:
    """Return / risk statistics of an equity curve sampled once per bar."""
    equity = np.asarray(equity, float)
    if len(equity) < 2 or equity[0] <= 0:
        return {"net_return": 0.0, "annualized_return": None, "sharpe": None, "sortino": None,
                "max_drawdown": 0.0, "calmar": None, "volatility": None}
    r = np.diff(equity) / equity[:-1]
    bpy = bars_per_year(timeframe)
    total = float(equity[-1] / equity[0] - 1)
    years = len(r) / bpy
    ann = float((1 + total) ** (1 / years) - 1) if years > 0 and total > -1 else None
    sd = r.std(ddof=1) if len(r) > 1 else 0.0
    down = r[r < 0]
    dd = np.sqrt((down ** 2).sum() / len(r)) if len(down) else 0.0
    mdd = max_drawdown(equity)
    return {
        "net_return": total,
        "annualized_return": ann,
        "sharpe": float(r.mean() / sd * np.sqrt(bpy)) if sd > 0 else None,
        "sortino": float(r.mean() / dd * np.sqrt(bpy)) if dd > 0 else None,
        "max_drawdown": mdd,
        "calmar": float(ann / abs(mdd)) if ann is not None and mdd < 0 else None,
        "volatility": float(sd * np.sqrt(bpy)),
    }


def trade_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {"trades": 0, "win_rate": None, "profit_factor": None, "avg_trade_pct": None, "best_trade_pct": None,
                "worst_trade_pct": None, "avg_holding_bars": None, "avg_win_pct": None, "avg_loss_pct": None}
    pnl = np.array([t["pnl"] for t in trades], float)
    pct = np.array([t["return_pct"] for t in trades], float)
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    gross_loss = -losses.sum()
    return {
        "trades": n,
        "win_rate": float(len(wins) / n),
        "profit_factor": float(wins.sum() / gross_loss) if gross_loss > 0 else None,
        "avg_trade_pct": float(pct.mean()), "best_trade_pct": float(pct.max()), "worst_trade_pct": float(pct.min()),
        "avg_win_pct": float(pct[pnl > 0].mean()) if len(wins) else None,
        "avg_loss_pct": float(pct[pnl <= 0].mean()) if len(losses) else None,
        "avg_holding_bars": float(np.mean([t["bars_held"] for t in trades])),
    }
