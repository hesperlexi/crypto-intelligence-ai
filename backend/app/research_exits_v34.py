"""V3.4 Stage 3E: trade-management study - each idea tested on its own against the live exits, nothing changed live.

The same out-of-sample calls as research_exits (15m / 1h / 4h, live decision rules, 0.15 % costs + funding), followed with:

  trail_10 / trail_15   after TP1 the stop trails 1.0R / 1.5R behind the best price (stops are ATR-based, so an R trail is a
                        volatility-adjusted trail)
  split_33 / split_70   partial profit-taking 34/33/33 and 70/15/15 instead of 50/25/25
  h_half                time limit halved
  tp_wide / tp_tight    targets 1R / 2R / 3R and 1R / 1.5R / 2R (volatility-adjusted by construction: R = the ATR stop)
  be_lock_025           at TP1 the stop goes to +0.25R instead of break-even
  fail_bo               failed-breakout exit: within 8 candles, after +0.3R, a close back at -0.3R closes the trade
  trend_20              trend-deterioration exit: a close beyond the path's EMA20 with the EMA turning against the call

Every variant is registered before any outcome is seen (research_verdict.register) and judged by the standard verdict
with Holm correction over all of them (research_verdict.finalize). A historical PASS is at most PROVISIONAL: the live
exits change only after an owner-approved forward-holdout confirmation."""
from __future__ import annotations

from typing import Any

from . import research_exits as RX

VARIANTS: dict[str, dict[str, Any]] = {
    "base": {},
    "trail_10": {"trail_r": 1.0},
    "trail_15": {"trail_r": 1.5},
    "split_33": {"split": (0.34, 0.33, 0.33)},
    "split_70": {"split": (0.70, 0.15, 0.15)},
    "h_half": {"hmult": 0.5},
    "tp_wide": {"ladder": (1.0, 2.0, 3.0)},
    "tp_tight": {"ladder": (1.0, 1.5, 2.0)},
    "be_lock_025": {"tp1_lock": 0.25},
    "fail_bo": {"fail_n": 8, "fail_r": 0.3},
    "trend_20": {"trend_n": 20},
}


def run(db_url: str, budget_s: float) -> dict[str, Any]:
    from .research_verdict import register
    # every verdict is a test: one per variant for all timeframes together and one per timeframe (Holm over all of them)
    register("exits-v34", [f"{k}/{tf}" for k in VARIANTS if k != "base" for tf in ("all",) + RX.TFS])
    old = RX.VARIANTS
    RX.VARIANTS = VARIANTS
    try:
        out = RX.replay(db_url, budget_s)
    finally:
        RX.VARIANTS = old
    out["notes"] = [__doc__.split("\n\n")[0].replace("\n", " ")]
    return {"replay": out}
