"""Multi-timeframe confirmation matrix."""
from __future__ import annotations

from typing import Any

import numpy as np

from ..config import MTF_TIMEFRAMES, MTF_WEIGHTS, TF_SECONDS
from .regime import REGIMES, group_of
from .signal import LABELS, label_for

DEADBAND = 0.10


def _direction(score: float | None) -> int:
    if score is None or not np.isfinite(score) or abs(score) < DEADBAND:
        return 0
    return int(np.sign(score))


def mtf_matrix(frames: dict[str, Any], unavailable: dict[str, str] | None = None) -> dict[str, Any]:
    """`frames`: timeframe -> Frame (already built on closed candles). Missing timeframes are listed, not guessed."""
    rows, dirs, wts = [], [], []
    for tf in MTF_TIMEFRAMES:
        fr = frames.get(tf)
        if fr is None:
            rows.append({"timeframe": tf, "available": False, "reason": (unavailable or {}).get(tf, "no data")})
            continue
        last = fr.ind.iloc[-1]
        code = last["regime"]
        score = float(last["regime_score"]) if np.isfinite(last["regime_score"]) else None
        tech = float(last["tech_score"]) if np.isfinite(last["tech_score"]) else None
        d = _direction(score)
        rows.append({
            "timeframe": tf, "available": True,
            "regime": REGIMES[int(code)] if np.isfinite(code) else "INSUFFICIENT DATA",
            "group": group_of(int(code)) if np.isfinite(code) else None,
            "direction": d, "direction_label": "BULL" if d > 0 else "BEAR" if d < 0 else "NEUTRAL",
            "regime_score": score, "tech_score": tech,
            "tech_signal": LABELS[label_for(tech)] if tech is not None else None,
            "rsi": float(last["rsi"]) if np.isfinite(last["rsi"]) else None,
            "adx": float(last["adx"]) if np.isfinite(last["adx"]) else None,
            "weight": MTF_WEIGHTS[tf],
        })
        if score is not None:
            dirs.append(d)
            wts.append(MTF_WEIGHTS[tf])
    if not dirs:
        return {"rows": rows, "alignment": None, "dominant": None, "conflict": False, "timeframes_used": 0}
    dirs_a, w = np.array(dirs, float), np.array(wts, float)
    w = w / w.sum()
    net = float((dirs_a * w).sum())
    dominant = int(np.sign(net)) if abs(net) >= 0.05 else 0
    # share of (weighted) timeframes pointing the dominant way; neutral timeframes count half
    if dominant == 0:
        alignment = float((w * (dirs_a == 0)).sum() + 0.5 * (w * (dirs_a != 0)).sum())
    else:
        alignment = float((w * (dirs_a == dominant)).sum() + 0.5 * (w * (dirs_a == 0)).sum())
    used = [r for r in rows if r.get("available") and r["regime_score"] is not None]
    short = [r["regime_score"] for r in used if TF_SECONDS[r["timeframe"]] <= 3600]
    long_ = [r["regime_score"] for r in used if TF_SECONDS[r["timeframe"]] >= 86400]
    conflict = bool(short and long_ and np.mean(short) * np.mean(long_) < 0
                    and abs(np.mean(short)) > 0.3 and abs(np.mean(long_)) > 0.3)
    return {"rows": rows, "alignment": alignment, "net": net, "dominant": dominant,
            "dominant_label": "BULL" if dominant > 0 else "BEAR" if dominant < 0 else "NEUTRAL",
            "conflict": conflict, "timeframes_used": len(used),
            "conflict_note": "Short and long timeframes point in opposite directions" if conflict else None}


def alignment_with(matrix: dict[str, Any], direction: int) -> float | None:
    """Weighted share of timeframes agreeing with `direction` (+1 / -1); neutral timeframes count half."""
    used = [r for r in matrix["rows"] if r.get("available") and r.get("regime_score") is not None]
    if not used or direction == 0:
        return matrix.get("alignment")
    w = np.array([r["weight"] for r in used])
    d = np.array([r["direction"] for r in used])
    w = w / w.sum()
    return float((w * (d == direction)).sum() + 0.5 * (w * (d == 0)).sum())


def higher_tf_score(matrix: dict[str, Any], timeframe: str) -> float | None:
    """Weighted mean regime score of the timeframes above `timeframe`."""
    hi = [r for r in matrix["rows"] if r.get("available") and r.get("regime_score") is not None
          and TF_SECONDS[r["timeframe"]] > TF_SECONDS[timeframe]]
    if not hi:
        return None
    w = np.array([r["weight"] for r in hi])
    return float((np.array([r["regime_score"] for r in hi]) * w).sum() / w.sum())
