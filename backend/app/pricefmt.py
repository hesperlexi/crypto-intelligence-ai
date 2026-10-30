"""Price formatting for posts and image cards: never scientific notation (1.23e-05 reads as nonsense to members)."""
from __future__ import annotations

import math


def fmt_price(v: float | None, sig: int = 6) -> str:
    """>= 100: 2 decimals with separators; >= 1: 4 decimals; below 1: plain decimals with `sig` significant digits."""
    if v is None:
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(v):
        return "—"
    a = abs(v)
    if a >= 100:
        return f"{v:,.2f}"
    if a >= 1:
        return f"{v:,.4f}"
    if a == 0:
        return "0"
    decimals = max(sig, sig - int(math.floor(math.log10(a))) - 1)
    s = f"{v:.{min(decimals, 20)}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s
