"""Cross-asset analysis computed from the tracked universe's own candles."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def cross_asset_report(closes: dict[str, pd.Series], ema50_above: dict[str, bool] | None = None,
                       window: int = 30, rs_window: int = 20) -> dict[str, Any]:
    """`closes`: symbol -> close series (same timeframe, DatetimeIndex). Needs at least two assets."""
    df = pd.DataFrame(closes).sort_index().dropna(how="all")
    if df.shape[1] < 2 or len(df) < window + 5:
        return {"available": False, "reason": "need at least two assets with overlapping history"}
    ret = np.log(df).diff()
    recent = ret.iloc[-window:]
    corr = recent.corr(min_periods=max(10, window // 2))
    out: dict[str, Any] = {"available": True, "window_bars": window, "symbols": list(df.columns),
                           "correlation": {a: {b: (None if not np.isfinite(corr.loc[a, b]) else float(corr.loc[a, b]))
                                               for b in df.columns} for a in df.columns}}
    perf = (df.iloc[-1] / df.shift(rs_window).iloc[-1] - 1)
    btc = next((s for s in df.columns if s.startswith("BTC/")), None)
    eth = next((s for s in df.columns if s.startswith("ETH/")), None)
    rows = []
    for s in df.columns:
        r = {"symbol": s, "return": None if not np.isfinite(perf[s]) else float(perf[s])}
        if btc and s != btc:
            rc = ret[s].rolling(window).corr(ret[btc])
            r["corr_btc"] = None if not np.isfinite(rc.iloc[-1]) else float(rc.iloc[-1])
            r["corr_btc_prev"] = None if len(rc) <= window or not np.isfinite(rc.iloc[-window]) else float(rc.iloc[-window])
            r["vs_btc"] = None if not (np.isfinite(perf[s]) and np.isfinite(perf[btc])) else float(perf[s] - perf[btc])
        rows.append(r)
    rows.sort(key=lambda r: -(r["return"] if r["return"] is not None else -9))
    out["relative_strength"] = {"window_bars": rs_window, "rows": rows}
    # equal-weight basket of the tracked universe: a proxy for the broad market (NOT total crypto market cap)
    basket = ret.mean(axis=1, skipna=True).cumsum()
    b_now, b_prev = basket.iloc[-1], basket.iloc[-rs_window - 1]
    out["basket"] = {"label": "Equal-weight basket of tracked assets (market proxy)",
                     "return": float(np.exp(b_now - b_prev) - 1), "members": int(df.shape[1])}
    obs: list[str] = []
    if btc:
        alts = [s for s in df.columns if s != btc]
        vs = [perf[s] - perf[btc] for s in alts if np.isfinite(perf[s]) and np.isfinite(perf[btc])]
        if vs:
            share = float(np.mean(np.array(vs) > 0))
            out["alt_outperformance_share"] = share
            if share >= 0.7:
                obs.append(f"Altcoin rotation: {share:.0%} of tracked alts outperformed BTC over {rs_window} bars")
            elif share <= 0.3:
                obs.append(f"BTC leading: only {share:.0%} of tracked alts outperformed BTC over {rs_window} bars")
        # lead/lag: does yesterday's BTC move correlate with today's alt moves more than the reverse?
        alt_ret = ret[alts].mean(axis=1)
        lead = alt_ret.iloc[-window * 3:].corr(ret[btc].shift(1).iloc[-window * 3:])
        lag = ret[btc].iloc[-window * 3:].corr(alt_ret.shift(1).iloc[-window * 3:])
        if np.isfinite(lead) and np.isfinite(lag):
            out["btc_lead_lag"] = {"btc_leads": float(lead), "alts_lead": float(lag)}
            if lead - lag > 0.1 and lead > 0.1:
                obs.append("BTC moves have tended to precede altcoin moves by one bar")
    if btc and eth:
        ratio = df[eth] / df[btc]
        ch = float(ratio.iloc[-1] / ratio.iloc[-rs_window - 1] - 1)
        out["eth_btc"] = {"ratio": float(ratio.iloc[-1]), "change": ch}
        if abs(ch) >= 0.03:
            obs.append(f"ETH {'outperforming' if ch > 0 else 'underperforming'} BTC ({ch:+.1%} on the ratio)")
    if ema50_above:
        breadth = float(np.mean(list(ema50_above.values())))
        out["breadth_above_ema50"] = breadth
        mean_corr = float(np.nanmean(corr.to_numpy()[np.triu_indices(len(corr), 1)]))
        out["mean_pairwise_correlation"] = mean_corr
        if breadth <= 0.3 and out["basket"]["return"] < 0 and mean_corr > 0.7:
            obs.append("Risk-off conditions: most assets below EMA 50, basket falling, correlations high")
        elif breadth >= 0.7 and out["basket"]["return"] > 0:
            obs.append("Risk-on conditions: most assets above EMA 50 and the basket is rising")
    out["observations"] = obs
    return out
