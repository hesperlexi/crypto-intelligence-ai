"""V3.4 Stage 4D: strategy suitability and selection (advisory; ONE trade authority).

Strategies the engine has:
  main   the AI signal engine (the public record; per timeframe)
  fast   the isolated Fast Opportunity paper strategy (meme / alt momentum; services/fast_strategy)
Suitability is measured, never assumed: for every strategy x market regime (services/market_regime) cell, the closed
trades' net R after costs with a 95 % interval:
  suitable    >= MIN_N trades and the interval above 0
  unsuitable  >= MIN_N trades and the interval below 0
  unproven    otherwise (too few trades, or the interval spans 0)
`advise(analysis, table)` labels one analysis TRADE | WAIT | NO TRADE | STRATEGY UNSUITABLE | INSUFFICIENT DATA with the
reason. It NEVER changes the decision: the analysis decision stays the only trade authority, the portfolio controller still
checks every entry, and the fast strategy steps aside on a coin where the main record holds the opposite side
(`main_conflict`). Table: setting `strategy_suitability` (refreshed with the Performance Lab, every 2 h).
"""
from __future__ import annotations

import math
import time
from typing import Any

from ..db import loads

MIN_N = 30
TRADE = ("BUY", "BUY ON PULLBACK", "SELL")
WAIT_FLAGS = ("NEWS", "CALL RUNNING", "WAIT FOR ENTRY", "PORTFOLIO LIMIT", "TOO MANY SAME-SIDE CALLS", "COOLDOWN")


def _cell(rs: list[float]) -> dict[str, Any]:
    n = len(rs)
    if n == 0:
        return {"n": 0, "state": "unproven"}
    m = sum(rs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in rs) / (n - 1)) if n > 1 else 0.0
    h = 1.96 * sd / math.sqrt(n) if n > 1 else None
    ci = [round(m - h, 3), round(m + h, 3)] if h is not None else None
    state = "unproven"
    if n >= MIN_N and ci:
        state = "suitable" if ci[0] > 0 else "unsuitable" if ci[1] < 0 else "unproven"
    return {"n": n, "avg_r": round(m, 3), "ci95": ci, "state": state}


def table(rt: Any) -> dict[str, Any]:
    """Measured suitability of each strategy by market regime (main also by timeframe)."""
    from .. import views
    from . import tracking as T
    db = rt.db
    main: dict[str, list[float]] = {}
    try:
        rc, rp = views.record_clause(rt)
        rows = db.query(f"SELECT * FROM signals WHERE side != 0 AND status IN ('STOPPED','TP1','TP2','TP3','EXPIRED') AND {rc}", rp)
    except Exception:
        rows = []
    for r in rows:
        p = loads(r.get("payload"), {}) or {}
        reg = ((p.get("risk_shadow") or {}).get("regime") or {}).get("regime") or "not recorded"
        rk = abs(float(r["entry"]) - float(r["stop"])) / float(r["entry"]) * 100 if r.get("entry") and r.get("stop") else None
        n = T.net_pct(r)
        if not rk or n is None:
            continue
        for key in (f"{r['timeframe']}|{reg}", f"all|{reg}"):
            main.setdefault(key, []).append(n / rk)
    fast: dict[str, list[float]] = {}
    try:
        for r in db.query("SELECT category, regime, r FROM fast_trades WHERE status = 'CLOSED' AND r IS NOT NULL"):
            for key in (f"{r['category']}|{r['regime']}", f"all|{r['regime']}"):
                fast.setdefault(key, []).append(float(r["r"]))
    except Exception:
        pass
    return {"at": int(time.time() * 1000), "min_n": MIN_N,
            "main": {k: _cell(v) for k, v in sorted(main.items())},
            "fast": {k: _cell(v) for k, v in sorted(fast.items())},
            "basis": "closed trades, net R after costs, 95 % interval; regime = market regime at the trade's start"}


def refresh(rt: Any) -> dict[str, Any]:
    t = table(rt)
    rt.db.set_setting("strategy_suitability", t)
    return {"main_cells": len(t["main"]), "fast_cells": len(t["fast"])}


def advise(a: dict[str, Any], tbl: dict[str, Any] | None, regime: str | None) -> dict[str, Any]:
    """Advisory label for one analysis of the main strategy (pure)."""
    tf = a.get("timeframe") or "?"
    if not isinstance(a, dict) or a.get("status") not in (None, "OK") or a.get("stale"):
        return {"action": "INSUFFICIENT DATA", "strategy": "main", "reason": "analysis missing or stale"}
    if not (a.get("forecast") or {}).get("available", True):
        return {"action": "INSUFFICIENT DATA", "strategy": "main", "reason": "no validated model for this coin / timeframe"}
    if regime in (None, "uncertain"):
        fit = {"state": "unproven", "n": 0}
        note = "market regime uncertain"
    else:
        cells = (tbl or {}).get("main") or {}
        fit = cells.get(f"{tf}|{regime}") or cells.get(f"all|{regime}") or {"state": "unproven", "n": 0}
        note = f"{fit['n']} past trades in a {regime.replace('_', ' ')} market"
    decision = str(a.get("decision") or "")
    flags = [str(f) for f in (a.get("flags") or [])]
    if decision in TRADE:
        if fit["state"] == "unsuitable":
            return {"action": "STRATEGY UNSUITABLE", "strategy": "main", "fit": fit,
                    "reason": f"this strategy has lost in this market ({note}); the call stands, treat it with care"}
        return {"action": "TRADE", "strategy": "main", "fit": fit,
                "reason": ("measured as suitable here" if fit["state"] == "suitable" else f"not yet proven here ({note})")}
    if (a.get("setup") or {}).get("ideal_entry") and any(w in f for f in flags for w in WAIT_FLAGS):
        return {"action": "WAIT", "strategy": "main", "fit": fit,
                "reason": "a setup exists but timing / limits hold it back: " + ", ".join(f for f in flags if f != "NO TRADE")[:120]}
    return {"action": "NO TRADE", "strategy": "main", "fit": fit, "reason": a.get("decision_reason") or "no edge right now"}


def main_conflict(db: Any, symbol: str, side: int) -> bool:
    """True when the main record holds an OPEN / PENDING call on this coin on the other side (the main strategy has
    precedence; a second strategy never takes the opposite side of the same coin)."""
    try:
        from . import portfolio_risk as PR
        return any(p["symbol"] == symbol and p["side"] == -side for p in PR.record_positions(db))
    except Exception:
        return True                             # unreadable: step aside
