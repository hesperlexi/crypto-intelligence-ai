"""Adaptive risk management. Deliberately independent of every prediction model: it only sees prices,
volatility, correlations and the user's own limits."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from ..data.base import bars_per_year


@dataclass
class RiskProfile:
    portfolio: float = 25_000.0
    risk_per_trade_pct: float = 1.0        # % of portfolio lost if the stop is hit
    max_daily_loss_pct: float = 3.0
    max_exposure_pct: float = 100.0        # total notional across positions, % of portfolio
    max_position_pct: float = 50.0         # single-position notional cap, % of portfolio
    target_annual_vol_pct: float = 40.0    # used by the volatility-adjusted sizing figure

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "RiskProfile":
        base = asdict(cls())
        for k, v in (d or {}).items():
            if k in base and v is not None:
                base[k] = float(v)
        return cls(**base)


def atr_stop(entry: float, atr: float, side: int, mult: float = 2.0) -> float:
    return entry - side * mult * atr


def position_size(profile: RiskProfile, entry: float, stop: float, sigma_bar: float | None = None,
                  timeframe: str = "4h", open_exposure: float = 0.0, realised_today: float = 0.0,
                  correlated_exposure: float = 0.0) -> dict[str, Any]:
    """Units to trade so that hitting the stop loses `risk_per_trade_pct` of the portfolio, then capped by the
    position, exposure and volatility limits. `open_exposure` / `correlated_exposure` are notionals in quote."""
    risk_amount = profile.portfolio * profile.risk_per_trade_pct / 100
    per_unit = abs(entry - stop)
    notes: list[str] = []
    if per_unit <= 0 or entry <= 0:
        return {"allowed": False, "reason": "stop equals entry", "qty": 0.0, "notional": 0.0}
    daily_limit = profile.portfolio * profile.max_daily_loss_pct / 100
    if realised_today <= -daily_limit:
        return {"allowed": False, "qty": 0.0, "notional": 0.0, "max_loss": 0.0,
                "reason": f"daily loss limit reached ({realised_today:,.2f} vs -{daily_limit:,.2f})"}
    qty = risk_amount / per_unit
    binding = "risk per trade"
    caps = {"single-position cap": profile.portfolio * profile.max_position_pct / 100 / entry,
            "portfolio exposure cap": max(0.0, profile.portfolio * profile.max_exposure_pct / 100 - open_exposure) / entry}
    vol_qty = None
    if sigma_bar and np.isfinite(sigma_bar) and sigma_bar > 0:
        ann_vol = sigma_bar * np.sqrt(bars_per_year(timeframe))
        vol_qty = profile.portfolio * (profile.target_annual_vol_pct / 100) / ann_vol / entry
        caps["volatility target"] = vol_qty
    for name, cap in caps.items():
        if cap < qty:
            qty, binding = cap, name
    if binding != "risk per trade":
        notes.append(f"Size reduced by the {binding}")
    notional = qty * entry
    if correlated_exposure > 0:
        notes.append(f"{correlated_exposure:,.0f} of open exposure is highly correlated with this asset; "
                     f"combined correlated notional would be {correlated_exposure + notional:,.0f}")
    return {
        "allowed": qty > 0, "reason": None if qty > 0 else "no exposure budget left",
        "qty": float(qty), "notional": float(notional), "notional_pct": float(notional / profile.portfolio * 100),
        "risk_amount": float(risk_amount), "max_loss": float(qty * per_unit),
        "max_loss_pct": float(qty * per_unit / profile.portfolio * 100), "stop_distance_pct": float(per_unit / entry * 100),
        "binding_constraint": binding, "volatility_adjusted_qty": None if vol_qty is None else float(vol_qty),
        "daily_loss_limit": float(daily_limit), "daily_loss_remaining": float(daily_limit + min(realised_today, 0.0)),
        "notes": notes, "profile": asdict(profile),
    }


def correlated_notional(symbol: str, positions: dict[str, float], corr: dict[str, dict[str, float]],
                        threshold: float = 0.7) -> float:
    """Sum of open notionals in assets whose return correlation with `symbol` exceeds `threshold`."""
    return float(sum(abs(n) for s, n in positions.items()
                     if s != symbol and corr.get(symbol, {}).get(s, 0.0) >= threshold))


def portfolio_risk(positions: dict[str, float], corr: dict[str, dict[str, float]], vols: dict[str, float],
                   portfolio: float) -> dict[str, Any]:
    """Annualised portfolio volatility from position notionals, per-asset annual vols and the correlation matrix."""
    syms = [s for s in positions if s in vols]
    if not syms or portfolio <= 0:
        return {"portfolio_vol_pct": None, "gross_exposure_pct": 0.0, "diversification_ratio": None}
    w = np.array([positions[s] / portfolio for s in syms])
    v = np.array([vols[s] for s in syms])
    C = np.array([[1.0 if a == b else corr.get(a, {}).get(b, 0.0) for b in syms] for a in syms])
    var = float((w * v) @ C @ (w * v))
    undiv = float(np.abs(w * v).sum())
    return {"portfolio_vol_pct": float(np.sqrt(max(var, 0.0)) * 100),
            "gross_exposure_pct": float(np.abs(w).sum() * 100),
            "diversification_ratio": float(undiv / np.sqrt(var)) if var > 0 else None}
