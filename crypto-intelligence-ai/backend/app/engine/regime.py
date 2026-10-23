"""Market-regime engine. Rule-based and fully vectorised so it can be replayed historically."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

REGIMES = ["STRONG BEAR", "BEAR", "BEARISH CONSOLIDATION", "NEUTRAL", "BULLISH CONSOLIDATION", "BULL",
           "STRONG BULL", "HIGH-VOLATILITY / UNSTABLE"]
UNSTABLE = 7
GROUPS = {"Bull": (4, 5, 6), "Neutral": (3,), "Bear": (0, 1, 2), "Unstable": (7,)}
VOTE_NAMES = ["price vs EMA200", "EMA200 slope", "EMA50 vs EMA200", "market structure", "20-bar momentum",
              "directional movement (DI/ADX)"]


def group_of(code: int) -> str:
    return next(g for g, codes in GROUPS.items() if code in codes)


def regime_frame(ind: pd.DataFrame) -> pd.DataFrame:
    """`ind` must already contain indicator, structure and volatility columns.

    Output columns: regime_score [-1, 1], regime_agree [0, 1], regime (code, NaN during warm-up),
    plus the individual votes v0..v5.
    """
    c = ind["close"]
    votes = pd.DataFrame(index=ind.index)
    votes["v0"] = np.sign(c - ind["ema_200"])
    votes["v1"] = np.sign(ind["ema_200"] - ind["ema_200"].shift(20))
    votes["v2"] = np.sign(ind["ema_50"] - ind["ema_200"])
    votes["v3"] = ind["struct_trend"].where(ind["last_sh"].notna() | ind["last_sl"].notna())
    z20 = (c / c.shift(20) - 1) / (ind["sigma_bar"] * np.sqrt(20))
    votes["v4"] = z20.clip(-1, 1)
    votes["v5"] = np.sign(ind["plus_di"] - ind["minus_di"]) * (ind["adx"] / 25).clip(upper=1)
    n_votes = votes.notna().sum(axis=1)
    score = votes.mean(axis=1, skipna=True).where(n_votes >= 3)
    sgn = np.sign(score)
    agree = (np.sign(votes).eq(sgn, axis=0) & votes.notna() & (votes != 0)).sum(axis=1) / n_votes.replace(0, np.nan)
    adx = ind["adx"].fillna(0)
    a = score.abs()
    level = np.select(
        [(a >= 0.6) & (adx >= 25), (a >= 0.3) & (adx >= 18), a >= 0.1],
        [3, 2, 1], default=0)
    code = (3 + np.sign(score.fillna(0)) * level).astype(float)
    code = np.where(ind["vol_state"] == 3, float(UNSTABLE), code)
    code = np.where(score.isna(), np.nan, code)
    out = votes.copy()
    out["regime_score"] = score
    out["regime_agree"] = agree.where(score.notna())
    out["regime"] = code
    return out


def transition_probabilities(regime: pd.Series, horizon: int = 10, min_n: int = 30) -> dict[str, Any]:
    """Empirical P(regime group `horizon` bars ahead | today's regime), estimated from this series' own history."""
    r = regime.to_numpy(float)
    cur = r[-1] if len(r) else np.nan
    if not np.isfinite(cur) or len(r) <= horizon + min_n:
        return {"horizon_bars": horizon, "n": 0, "probabilities": None, "basis": "insufficient history"}
    now, later = r[:-horizon], r[horizon:]
    ok = np.isfinite(now) & np.isfinite(later)
    mask = ok & (now == cur)
    basis = f"same regime ({REGIMES[int(cur)]})"
    if mask.sum() < min_n:  # too few exact matches: condition on the broader group instead
        grp = GROUPS[group_of(int(cur))]
        mask = ok & np.isin(now, grp)
        basis = f"same regime group ({group_of(int(cur))})"
    n = int(mask.sum())
    if n < min_n:
        return {"horizon_bars": horizon, "n": n, "probabilities": None, "basis": "insufficient history"}
    nxt = later[mask]
    probs = {g: float(np.isin(nxt, codes).mean()) for g, codes in GROUPS.items()}
    return {"horizon_bars": horizon, "n": n, "probabilities": probs, "basis": basis,
            "from_group": group_of(int(cur)), "stay_same_regime": float((nxt == cur).mean())}


def describe_regime(ind: pd.DataFrame, horizon: int = 10) -> dict[str, Any]:
    """Snapshot for the last bar of a frame produced by build_frame()."""
    last = ind.iloc[-1]
    code = last.get("regime")
    if code is None or not np.isfinite(code):
        return {"regime": "INSUFFICIENT DATA", "code": None, "confidence": None, "score": None}
    code = int(code)
    votes = []
    for i, name in enumerate(VOTE_NAMES):
        v = last.get(f"v{i}")
        if v is not None and np.isfinite(v):
            votes.append({"input": name, "vote": float(v),
                          "reads": "bullish" if v > 0.1 else ("bearish" if v < -0.1 else "neutral")})
    adx = float(last["adx"]) if np.isfinite(last["adx"]) else None
    strength = None if adx is None else ("Strong" if adx >= 30 else "Moderate" if adx >= 20 else "Weak")
    mom = last.get("v4")
    return {
        "regime": REGIMES[code], "code": code, "group": group_of(code),
        "score": float(last["regime_score"]),
        # share of regime inputs that agree with the classified direction (input agreement, not a probability)
        "confidence": float(last["regime_agree"]) if np.isfinite(last["regime_agree"]) else None,
        "confidence_basis": "share of regime inputs agreeing with the classified direction",
        "trend_strength": strength, "adx": adx,
        "momentum": None if mom is None or not np.isfinite(mom) else
        ("Positive" if mom > 0.2 else "Negative" if mom < -0.2 else "Flat"),
        "votes": votes,
        "transition": transition_probabilities(ind["regime"], horizon),
    }
