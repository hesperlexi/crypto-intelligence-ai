"""Data-quality checks for a candle series."""
from __future__ import annotations

import time
from typing import Any

import numpy as np
import pandas as pd

from .base import tf_ms


def check_candles(df: pd.DataFrame, timeframe: str, now_ms: int | None = None,
                  raw_rows: int | None = None) -> dict[str, Any]:
    """Returns counts of missing / duplicate / malformed candles and a 0-100 quality score."""
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    step = tf_ms(timeframe)
    if df is None or df.empty:
        return {"timeframe": timeframe, "candles": 0, "missing": 0, "duplicates": 0, "malformed": 0,
                "gaps": [], "quality_pct": None, "fresh": False, "age_s": None, "status": "NO DATA"}
    ts = df["ts"].to_numpy()
    diffs = np.diff(ts)
    gap_idx = np.where(diffs > step)[0]
    missing = int(((diffs[gap_idx] // step) - 1).sum()) if len(gap_idx) else 0
    misaligned = int((diffs % step != 0).sum()) if timeframe not in ("1w", "3d") else 0
    duplicates = int(raw_rows - len(df)) if raw_rows is not None else int((diffs == 0).sum())
    o, h, l, c, v = (df[k].to_numpy() for k in ("open", "high", "low", "close", "volume"))
    malformed = int(((h < np.maximum(o, c)) | (l > np.minimum(o, c)) | (l <= 0) | (v < 0)
                     | ~np.isfinite(o + h + l + c + v)).sum())
    expected = len(df) + missing
    quality = 100.0 * (1 - (missing + malformed + misaligned) / max(expected, 1))
    age_s = (now_ms - (int(ts[-1]) + step)) / 1000  # time since the last stored candle closed
    fresh = age_s <= 2 * step / 1000
    gaps = [{"from": int(ts[i]), "to": int(ts[i + 1]), "missing": int(diffs[i] // step - 1)} for i in gap_idx[-10:]]
    status = "OK" if fresh and quality >= 99 else ("STALE" if not fresh else "DEGRADED")
    return {"timeframe": timeframe, "candles": int(len(df)), "missing": missing, "duplicates": duplicates,
            "malformed": malformed, "misaligned": misaligned, "gaps": gaps,
            "quality_pct": round(float(quality), 3), "fresh": bool(fresh), "age_s": round(float(age_s), 1),
            "first_ts": int(ts[0]), "last_ts": int(ts[-1]), "status": status}
