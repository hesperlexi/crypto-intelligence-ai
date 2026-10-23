"""Event-driven bar backtester.

Execution model (no look-ahead):
  * signal[i] is decided with information available at the CLOSE of bar i
  * it is executed at the OPEN of bar i+1, worsened by half the spread plus slippage
  * stops / targets are evaluated against bar highs and lows; if both are touched in the same bar the
    STOP is assumed to fill first (pessimistic); gaps through a stop fill at the open
  * fees are charged on entry and exit notional
Gross and net results are both reported - net is the only figure that should be read as performance.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from .stats import equity_stats, trade_stats


@dataclass
class BacktestConfig:
    initial_capital: float = 10_000.0
    fee_rate: float = 0.001            # per side, fraction of notional
    slippage_bps: float = 2.0          # per side
    spread_bps: float = 1.0            # full quoted spread; half is paid per side
    sizing: str = "fraction"           # "fraction" of equity | "risk" (risk_per_trade / stop distance)
    fraction: float = 1.0
    risk_per_trade: float = 0.01
    stop_atr: float | None = 2.0       # stop distance in ATRs (None = no stop)
    take_profit_atr: float | None = None
    stop_pct: float | None = None      # alternative fixed-percent stop / target
    take_profit_pct: float | None = None
    allow_short: bool = False
    max_hold_bars: int | None = None
    max_leverage: float = 1.0


def run_backtest(df: pd.DataFrame, signal: np.ndarray, cfg: BacktestConfig, timeframe: str,
                 atr: np.ndarray | None = None) -> dict[str, Any]:
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    ts = df["ts"].to_numpy()
    n = len(df)
    signal = np.nan_to_num(np.asarray(signal, float))
    if not cfg.allow_short:
        signal = np.clip(signal, 0, 1)
    atr = np.full(n, np.nan) if atr is None else np.asarray(atr, float)
    adverse = (cfg.slippage_bps + cfg.spread_bps / 2) / 1e4

    cash = cfg.initial_capital
    qty = 0.0            # signed position size
    entry_px = entry_raw = stop = target = np.nan
    entry_i = -1
    entry_fee = 0.0
    blocked = 0.0        # after a stop/target exit, wait for the signal to change before re-entering
    equity = np.empty(n)
    gross_equity = np.empty(n)
    gross_adj = 0.0      # cumulative fees + slippage, added back for the gross curve
    trades: list[dict[str, Any]] = []
    fees_total = slip_total = 0.0

    def close_position(i: int, raw_px: float, reason: str) -> None:
        nonlocal cash, qty, fees_total, slip_total, gross_adj, entry_px, stop, target
        side = np.sign(qty)
        fill = raw_px * (1 - side * adverse)
        notional = abs(qty) * fill
        fee = notional * cfg.fee_rate
        slip = abs(qty) * abs(raw_px - fill)
        cash += qty * fill - fee
        pnl = qty * (fill - entry_px) - fee - entry_fee
        gross = qty * (raw_px - entry_raw)
        fees_total += fee
        slip_total += slip
        gross_adj += fee + slip
        trades.append({
            "entry_ts": int(ts[entry_i]), "exit_ts": int(ts[i]), "side": "LONG" if side > 0 else "SHORT",
            "entry": float(entry_px), "exit": float(fill), "qty": float(abs(qty)), "pnl": float(pnl),
            "gross_pnl": float(gross), "return_pct": float(pnl / (abs(qty) * entry_px) * 100),
            "bars_held": int(i - entry_i), "reason": reason,
        })
        qty = 0.0
        entry_px = stop = target = np.nan

    for i in range(n):
        want = signal[i - 1] if i > 0 else 0.0
        if want != blocked:
            blocked = 0.0
        # 1) act on the previous bar's decision at this bar's open
        if qty != 0 and (np.sign(qty) != want or (cfg.max_hold_bars and i - entry_i >= cfg.max_hold_bars)):
            close_position(i, o[i], "signal" if np.sign(qty) != want else "max_hold")
        if qty == 0 and want != 0 and want != blocked and i > 0:
            eq = cash
            fill = o[i] * (1 + want * adverse)
            a = atr[i - 1]
            dist = None
            if cfg.stop_pct:
                dist = fill * cfg.stop_pct
            elif cfg.stop_atr and np.isfinite(a) and a > 0:
                dist = cfg.stop_atr * a
            if cfg.sizing == "risk" and dist:
                size = eq * cfg.risk_per_trade / dist
            else:
                size = eq * cfg.fraction / fill
            size = min(size, eq * cfg.max_leverage / (fill * (1 + cfg.fee_rate)))
            if size > 0 and eq > 0:
                fee = size * fill * cfg.fee_rate
                slip = size * abs(fill - o[i])
                qty = want * size
                cash -= qty * fill + fee
                entry_px, entry_raw, entry_i, entry_fee = fill, o[i], i, fee
                fees_total += fee
                slip_total += slip
                gross_adj += fee + slip
                stop = fill - want * dist if dist else np.nan
                tp = fill * cfg.take_profit_pct if cfg.take_profit_pct else \
                    (cfg.take_profit_atr * a if cfg.take_profit_atr and np.isfinite(a) and a > 0 else None)
                target = fill + want * tp if tp else np.nan
        # 2) intrabar stop / target (stop first)
        if qty != 0:
            side = np.sign(qty)
            if np.isfinite(stop) and ((side > 0 and l[i] <= stop) or (side < 0 and h[i] >= stop)):
                px = min(o[i], stop) if side > 0 else max(o[i], stop)
                close_position(i, px, "stop")
                blocked = side
            elif np.isfinite(target) and ((side > 0 and h[i] >= target) or (side < 0 and l[i] <= target)):
                px = max(o[i], target) if side > 0 else min(o[i], target)
                close_position(i, px, "target")
                blocked = side
        equity[i] = cash + qty * c[i]
        gross_equity[i] = equity[i] + gross_adj
    if qty != 0:   # mark the open position out at the last close so totals reconcile
        close_position(n - 1, c[-1], "end_of_test")
        equity[-1] = cash
        gross_equity[-1] = cash + gross_adj

    stats = equity_stats(np.concatenate([[cfg.initial_capital], equity]), timeframe)
    tstats = trade_stats(trades)
    exposure = float(np.mean(signal[:-1] != 0)) if n > 1 else 0.0
    step = max(1, n // 600)
    return {
        "config": asdict(cfg),
        "summary": {
            **stats, **tstats,
            "gross_return": float(gross_equity[-1] / cfg.initial_capital - 1) if n else 0.0,
            "fees": float(fees_total), "slippage": float(slip_total),
            "fees_pct": float(fees_total / cfg.initial_capital), "slippage_pct": float(slip_total / cfg.initial_capital),
            "final_equity": float(equity[-1]) if n else cfg.initial_capital,
            "exposure": exposure, "bars": int(n),
            "start_ts": int(ts[0]) if n else None, "end_ts": int(ts[-1]) if n else None,
        },
        "equity_curve": [{"ts": int(ts[i]), "equity": float(equity[i])} for i in range(0, n, step)],
        "trades": trades[-500:],
    }
