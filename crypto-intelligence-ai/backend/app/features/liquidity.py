"""Volume & liquidity engine: candle-based pressure, order-book analytics, OI/price interpretation."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def volume_frame(df: pd.DataFrame, ind: pd.DataFrame) -> pd.DataFrame:
    """Candle-derived volume features (causal). `ind` is the output of compute_indicators."""
    out = pd.DataFrame(index=df.index)
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    # close location value: +1 close at high (buyers in control), -1 close at low
    out["clv"] = (((df["close"] - df["low"]) - (df["high"] - df["close"])) / rng).fillna(0.0)
    out["buy_pressure"] = (out["clv"] * df["volume"]).rolling(20).sum() / df["volume"].rolling(20).sum()
    out["volume_spike"] = (ind["rel_volume"] > 2.0).astype(int)
    ret = df["close"].pct_change()
    # volume confirmation: direction of the bar weighted by how unusual its volume is
    out["vol_confirm"] = (np.sign(ret) * np.clip(ind["rel_volume"] - 1.0, -1, 2)).rolling(5).mean()
    obv = ind["obv"]
    scale = df["volume"].rolling(20).mean().replace(0, np.nan)
    out["obv_slope"] = (obv - obv.shift(10)) / (10 * scale)
    # price up while volume trend falls (or vice versa) = volume divergence
    price_tr = np.sign(df["close"] - df["close"].shift(10))
    vol_tr = np.sign(ind["vol_sma"] - ind["vol_sma"].shift(10))
    out["volume_divergence"] = ((price_tr != 0) & (vol_tr < 0)).astype(int) * price_tr
    return out


def order_book_metrics(book: dict[str, Any], depth_pct: float = 1.0, wall_mult: float = 5.0) -> dict[str, Any] | None:
    """Imbalance, spread and large resting orders from an L2 snapshot ({'bids': [[p, q]..], 'asks': ...})."""
    bids = np.array([[b[0], b[1]] for b in book.get("bids") or []], float)
    asks = np.array([[a[0], a[1]] for a in book.get("asks") or []], float)
    if len(bids) == 0 or len(asks) == 0:
        return None
    best_bid, best_ask = bids[0, 0], asks[0, 0]
    mid = (best_bid + best_ask) / 2
    lo, hi = mid * (1 - depth_pct / 100), mid * (1 + depth_pct / 100)
    b_in, a_in = bids[bids[:, 0] >= lo], asks[asks[:, 0] <= hi]
    bid_val, ask_val = float((b_in[:, 0] * b_in[:, 1]).sum()), float((a_in[:, 0] * a_in[:, 1]).sum())
    tot = bid_val + ask_val
    imbalance = (bid_val - ask_val) / tot if tot > 0 else 0.0
    top = min(10, len(bids), len(asks))
    tb, ta = float(bids[:top, 1].sum()), float(asks[:top, 1].sum())

    def walls(side: np.ndarray, name: str) -> list[dict[str, float]]:
        med = np.median(side[:, 1])
        idx = np.where(side[:, 1] > wall_mult * med)[0][:5]
        return [{"side": name, "price": float(side[i, 0]), "size": float(side[i, 1]),
                 "distance_pct": float((side[i, 0] / mid - 1) * 100)} for i in idx]

    # liquidity concentration: share of in-band depth sitting in the 3 largest levels
    def conc(side: np.ndarray) -> float:
        v = side[:, 0] * side[:, 1]
        return float(np.sort(v)[-3:].sum() / v.sum()) if v.sum() > 0 else 0.0

    return {
        "mid": float(mid), "best_bid": float(best_bid), "best_ask": float(best_ask),
        "spread": float(best_ask - best_bid), "spread_bps": float((best_ask - best_bid) / mid * 1e4),
        "depth_pct": depth_pct, "bid_value": bid_val, "ask_value": ask_val,
        "imbalance": float(imbalance),                       # +1 all bids, -1 all asks (within depth band)
        "top10_bid_ask_ratio": float(tb / ta) if ta > 0 else None,
        "concentration": {"bids": conc(b_in) if len(b_in) else 0.0, "asks": conc(a_in) if len(a_in) else 0.0},
        "walls": walls(bids, "bid") + walls(asks, "ask"),
    }


def trade_flow(trades: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Aggressor-side imbalance from recent public trades."""
    buy = sum((t.get("amount") or 0) * (t.get("price") or 0) for t in trades if t.get("side") == "buy")
    sell = sum((t.get("amount") or 0) * (t.get("price") or 0) for t in trades if t.get("side") == "sell")
    if buy + sell <= 0:
        return None
    return {"buy_value": float(buy), "sell_value": float(sell), "imbalance": float((buy - sell) / (buy + sell)),
            "trades": len(trades)}


OI_PRICE_MATRIX = {
    (1, 1): ("Price ↑ + OI ↑", "New positions are opening in the direction of the rise: fresh longs are "
                               "supporting the move. Trend-confirming, but leverage is building."),
    (1, -1): ("Price ↑ + OI ↓", "Positions are closing as price rises: the move is likely driven by short "
                                "covering rather than new demand, which tends to be less durable."),
    (-1, 1): ("Price ↓ + OI ↑", "New positions are opening as price falls: fresh shorts are pressing the "
                                "move. Trend-confirming to the downside; squeeze risk rises if it stalls."),
    (-1, -1): ("Price ↓ + OI ↓", "Positions are closing as price falls: long liquidation / de-leveraging. "
                                 "Often seen late in a decline rather than at its start."),
}


def oi_price_state(price_change: float, oi_change: float, eps: float = 1e-4) -> dict[str, Any]:
    """Classify the price/open-interest quadrant. These are interpretations, not predictions."""
    if abs(price_change) < eps or abs(oi_change) < eps:
        return {"label": "Flat", "meaning": "Price or open interest is essentially unchanged over the window.",
                "price_change": price_change, "oi_change": oi_change}
    label, meaning = OI_PRICE_MATRIX[(1 if price_change > 0 else -1, 1 if oi_change > 0 else -1)]
    return {"label": label, "meaning": meaning, "price_change": price_change, "oi_change": oi_change}
