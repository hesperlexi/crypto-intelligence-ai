"""V3.3 portfolio risk controller (Stage 2 phase A; Fable 5.2 audit R-08, F-new 1).

One controller, used before every NEW paper entry: the public record (`analysis.analyze`, so the record-mirror bots,
Hesper, Last Stand and members' auto-trade, which all follow the published call, inherit it), every bot book and both
challenge books (`book_check`). It never touches an open position: stops, targets, time limits and exits run as before.

Unit: R = the planned risk of one trade (entry to the original stop). At the reference size of
`RISK_PER_TRADE_PCT_REF` = 0.25 % of equity per trade, 1R = 0.25 % of equity, so the defaults below mean:

  limit (env)                       default   = equity at risk at 0.25 %/trade   why
  PORTFOLIO_MAX_OPEN_R              8 R       2.0 %   all open risk together (today the same-side cap alone allows 12)
  PORTFOLIO_MAX_SIDE_R              6 R       1.5 %   one direction (longs or shorts)
  PORTFOLIO_MAX_CORR_R              5 R       1.25 %  one direction in coins moving with BTC (1h corr >= 0.7)
  PORTFOLIO_MAX_COIN_R              1 R       0.25 %  one coin across all timeframes (no stacking one idea)
  PORTFOLIO_BLOCK_CONFLICT          on                no long and short on the same coin at once
  PORTFOLIO_DD_LIMIT_R              10 R      2.5 %   record drawdown from its peak (closed calls, net of costs)

Remaining risk of an open position = open share x (entry - stop in force) / original risk, never below 0: a position
whose stop sits at break-even or better (after TP1) carries no capital risk and frees its slot. A pending entry counts
as a full 1R (it may still fill). Coins whose correlation cannot be measured count as correlated (never "safe").

Drawdown and recovery (record): NORMAL -> HALT when the drawdown reaches DD_LIMIT_R (no new entries for HALT_H hours)
-> PROBATION (open / side / correlated limits halved; the per-coin rule stays) -> NORMAL when the drawdown is back to DD_RESUME_R or after PROBATION_D days;
a further drawdown of DD_RETRIGGER_R beyond the halt level during probation halts again. The existing capital-protection
veto (risk_shadow: -3R day, -6R week, resets at the next UTC day / week) stays the daily loss protection.

Missing data fails closed: if open positions, adjustments or the closed record cannot be read, the new entry is refused
with "CHECK UNAVAILABLE" (Health `gate_failures` portfolio). Mode `PORTFOLIO_GATE`: enforce (default) | shadow (assess
and record only) | off."""
from __future__ import annotations

import os
import time
from typing import Any, Callable

import numpy as np

H = 3_600_000
DAY = 24 * H


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return float(default)


MODE = os.environ.get("PORTFOLIO_GATE", "enforce").strip().lower()
RISK_PER_TRADE_PCT_REF = 0.25
LIMITS = {
    "max_open_r": _f("PORTFOLIO_MAX_OPEN_R", 8.0),
    "max_side_r": _f("PORTFOLIO_MAX_SIDE_R", 6.0),
    "max_corr_r": _f("PORTFOLIO_MAX_CORR_R", 5.0),
    "max_coin_r": _f("PORTFOLIO_MAX_COIN_R", 1.0),
    # V3.5 (owner, 27 Nov 2026: "a quota for each timeframe rather than limited signals on all timeframes"): record
    # calls are judged per timeframe - each timeframe may carry this much risk per direction, so 12h calls can never use
    # up the room of a rare 15m call. Replaces the shared open / direction / BTC-correlated limits for the record; the
    # per-coin rule, the long-and-short conflict rule and the drawdown brake stay shared. PORTFOLIO_TF_QUOTA=0 = old rules.
    "tf_quota": os.environ.get("PORTFOLIO_TF_QUOTA", "1") != "0",
    "max_tf_side_r": _f("PORTFOLIO_MAX_TF_SIDE_R", 3.0),
    "block_conflict": os.environ.get("PORTFOLIO_BLOCK_CONFLICT", "1") != "0",
    "corr_min": _f("PORTFOLIO_CORR_MIN", 0.7),
    "corr_bars": int(_f("PORTFOLIO_CORR_BARS", 72)),
    "dd_limit_r": _f("PORTFOLIO_DD_LIMIT_R", 10.0),
    "dd_resume_r": _f("PORTFOLIO_DD_RESUME_R", 6.0),
    "dd_retrigger_r": _f("PORTFOLIO_DD_RETRIGGER_R", 3.0),
    "halt_h": _f("PORTFOLIO_HALT_H", 24.0),
    "probation_d": _f("PORTFOLIO_PROBATION_D", 7.0),
    "probation_factor": _f("PORTFOLIO_PROBATION_FACTOR", 0.5),
}
FLAG = "PORTFOLIO LIMIT"
DD_FLAG = "PORTFOLIO DRAWDOWN"
EPS = 1e-9


class Unavailable(Exception):
    """Portfolio data could not be read: new entries fail closed."""


# ---- positions ------------------------------------------------------------------------------------------------------

def _payload(row: dict[str, Any]) -> dict[str, Any]:
    from ..db import loads
    p = row.get("payload")
    return (loads(p, {}) or {}) if isinstance(p, str) else (p or {})


def remaining_r(side: int, entry: float, stop_now: float, risk0: float, share: float) -> float:
    if risk0 <= 0:
        return 1.0                              # unknown original risk: count a full trade
    return max(0.0, side * (float(entry) - float(stop_now))) / risk0 * max(0.0, min(1.0, share))


def record_positions(db: Any) -> list[dict[str, Any]]:
    """Open and pending public record calls as positions {symbol, timeframe, side, risk_r, pending, id}."""
    from . import guardian, tracking
    try:
        rows = db.query("SELECT * FROM signals WHERE status = 'OPEN' AND side != 0 "
                        "AND (fill_status IS NULL OR fill_status IN ('PENDING', 'FILLED'))", ())
        adj = tracking.adjustments_for(db, [r["id"] for r in rows])
    except Exception as exc:
        raise Unavailable(f"open record calls unreadable ({type(exc).__name__}: {exc})"[:160]) from exc
    out = []
    for r in rows:
        side = 1 if int(r["side"]) > 0 else -1
        if r.get("fill_status") == "PENDING":
            out.append({"symbol": r["symbol"], "timeframe": r["timeframe"], "side": side, "risk_r": 1.0,
                        "pending": True, "id": r["id"]})
            continue
        try:
            entry, stop0 = float(r["entry"]), float(r["stop"])
            stop_now = guardian.stop_in_force(r, adj.get(r["id"], []))
        except Exception as exc:
            raise Unavailable(f"call {r.get('id')} levels unreadable ({type(exc).__name__})") from exc
        runner = bool((_payload(r).get("runner") or {}).get("on"))
        share = 1.0 if runner else 0.25 if r.get("tp2_hit") else 0.5 if r.get("tp1_hit") else 1.0
        out.append({"symbol": r["symbol"], "timeframe": r["timeframe"], "side": side, "pending": False, "id": r["id"],
                    "risk_r": round(remaining_r(side, entry, stop_now, abs(entry - stop0), share), 4)})
    return out


def book_positions(state: dict[str, Any], timeframe: str | None = None) -> list[dict[str, Any]]:
    """Positions and pending entries of a bot / challenge book (state of BotEngine / Hesper)."""
    out = []
    try:
        for p in state.get("positions") or []:
            side = 1 if int(p["side"]) > 0 else -1
            qty, qopen = float(p.get("qty") or 0), float(p.get("qty_open") or 0)
            risk0 = abs(float(p["entry"]) - float(p.get("stop0", p["stop"])))
            share = qopen / qty if qty > 0 else 0.0
            out.append({"symbol": p["symbol"], "side": side, "pending": False, "timeframe": timeframe,
                        "risk_r": round(remaining_r(side, p["entry"], p["stop"], risk0, share), 4)})
        for o in state.get("pending") or []:
            out.append({"symbol": o["symbol"], "side": 1 if int(o["side"]) > 0 else -1, "risk_r": 1.0, "pending": True,
                        "timeframe": timeframe})
    except Exception as exc:
        raise Unavailable(f"book positions unreadable ({type(exc).__name__}: {exc})"[:160]) from exc
    return out


# ---- correlation with BTC -------------------------------------------------------------------------------------------
_corr_cache: dict[str, Any] = {}


def btc_corr(rt: Any, symbol: str, bars: int | None = None) -> float | None:
    """Correlation of the coin's closed 1h log returns with BTC's over the last `bars` hours (None = cannot measure)."""
    bars = bars or LIMITS["corr_bars"]
    if symbol == "BTC/USDT":
        return 1.0
    try:
        a, b = rt.candles(symbol, "1h"), rt.candles("BTC/USDT", "1h")
    except Exception:
        return None
    if a is None or b is None or len(a) < bars + 1 or len(b) < bars + 1:
        return None
    key = f"{symbol}|{int(a['ts'].iloc[-1])}|{int(b['ts'].iloc[-1])}|{bars}"
    if key in _corr_cache:
        return _corr_cache[key]
    m = a[["ts", "close"]].merge(b[["ts", "close"]], on="ts", suffixes=("_a", "_b")).tail(bars + 1)
    out = None
    if len(m) >= bars * 0.9:
        ra, rb = np.diff(np.log(m["close_a"].to_numpy(float))), np.diff(np.log(m["close_b"].to_numpy(float)))
        if np.std(ra) > 0 and np.std(rb) > 0:
            out = float(np.corrcoef(ra, rb)[0, 1])
    if len(_corr_cache) > 2000:
        _corr_cache.clear()
    _corr_cache[key] = out
    return out


# ---- drawdown and recovery (record) ---------------------------------------------------------------------------------

_dd_cache: dict[str, Any] = {}
DD_CACHE_S = 60


def record_drawdown(rt: Any) -> dict[str, Any]:
    """Peak-to-now drawdown of the record's closed calls in net R (record_clause: what Results counts). Cached 60 s
    per database (a tick asks once per candidate call)."""
    hit = _dd_cache.get(id(rt.db))
    if hit and time.time() - hit[0] < DD_CACHE_S:
        return hit[1]
    out = _record_drawdown(rt)
    _dd_cache[id(rt.db)] = (time.time(), out)
    return out


def _record_drawdown(rt: Any) -> dict[str, Any]:
    from . import risk_shadow, tracking
    from ..views import record_clause
    try:
        sql, params = record_clause(rt)
        closed = tuple(tracking.CLOSED_STATUSES)
        rows = rt.db.query(f"SELECT * FROM signals WHERE {sql} AND status IN ({','.join('?' * len(closed))}) "
                           "AND closed_at IS NOT NULL ORDER BY closed_at", (*params, *closed))
    except Exception as exc:
        raise Unavailable(f"closed record unreadable ({type(exc).__name__}: {exc})"[:160]) from exc
    cum = peak = 0.0
    n = 0
    for r in rows:
        if r.get("fill_status") == "NOT_FILLED":
            continue
        x = risk_shadow._net_r(r)
        if x is None:
            continue
        n += 1
        cum += x
        peak = max(peak, cum)
    return {"n": n, "total_r": round(cum, 3), "peak_r": round(peak, 3), "dd_r": round(peak - cum, 3)}


def step_state(prev: dict[str, Any] | None, dd_r: float, now: int, lim: dict[str, Any] | None = None) -> dict[str, Any]:
    """Pure state machine NORMAL / HALT / PROBATION (see module doc)."""
    lim = lim or LIMITS
    p = dict(prev or {})
    st = p.get("state") or "NORMAL"
    if st == "NORMAL":
        if dd_r >= lim["dd_limit_r"] - EPS:
            return {"state": "HALT", "since": now, "until": now + int(lim["halt_h"] * H), "dd_at_halt": dd_r,
                    "why": f"record drawdown {dd_r:.1f}R reached the {lim['dd_limit_r']:g}R limit"}
        return {"state": "NORMAL", "since": p.get("since") or now}
    if st == "HALT":
        if now < int(p.get("until") or 0):
            return p
        return {"state": "PROBATION", "since": now, "until": now + int(lim["probation_d"] * DAY),
                "dd_at_halt": p.get("dd_at_halt", dd_r), "why": "after a drawdown halt: limits halved until recovery"}
    # PROBATION
    if dd_r >= float(p.get("dd_at_halt") or lim["dd_limit_r"]) + lim["dd_retrigger_r"] - EPS:
        return {"state": "HALT", "since": now, "until": now + int(lim["halt_h"] * H), "dd_at_halt": dd_r,
                "why": f"drawdown deepened to {dd_r:.1f}R during probation"}
    if dd_r <= lim["dd_resume_r"] + EPS or now >= int(p.get("until") or 0):
        return {"state": "NORMAL", "since": now}
    return p


def record_state(rt: Any, now: int | None = None) -> dict[str, Any]:
    """Current drawdown state of the record (stored in setting `portfolio_state`, transitions logged)."""
    now = int(time.time() * 1000) if now is None else int(now)
    dd = record_drawdown(rt)
    prev = rt.db.get_setting("portfolio_state", None)
    st = step_state(prev, dd["dd_r"], now)
    st["drawdown"] = dd
    if (prev or {}).get("state") != st["state"]:
        log = rt.db.get_setting("portfolio_state_log", []) or []
        log.append({"at": now, "from": (prev or {}).get("state"), "to": st["state"], "dd_r": dd["dd_r"], "why": st.get("why")})
        rt.db.set_setting("portfolio_state_log", log[-200:])
    if prev != st:
        rt.db.set_setting("portfolio_state", st)
    return st


# ---- the check --------------------------------------------------------------------------------------------------------

def check(positions: list[dict[str, Any]], symbol: str, side: int, corr: Callable[[str], float | None],
          new_risk: float = 1.0, factor: float = 1.0, lim: dict[str, Any] | None = None,
          timeframe: str | None = None) -> dict[str, Any]:
    """Would one more position (symbol, side, new_risk R) stay inside the limits? Pure; `factor` scales the R limits.
    With `timeframe` (record calls) and the timeframe quota on, the shared open / direction / correlated limits are
    replaced by one budget per timeframe and direction (`max_tf_side_r`)."""
    lim = lim or LIMITS
    if timeframe and lim.get("tf_quota"):
        return _check_tf(positions, symbol, side, timeframe, new_risk, factor, lim)
    side = 1 if side > 0 else -1
    cmemo: dict[str, float | None] = {}

    def correlated(s: str) -> bool:
        if s not in cmemo:
            cmemo[s] = corr(s)
        c = cmemo[s]
        return c is None or c >= lim["corr_min"]          # unknown = correlated (never "safe")
    open_r = sum(p["risk_r"] for p in positions)
    side_r = sum(p["risk_r"] for p in positions if p["side"] == side)
    coin_r = sum(p["risk_r"] for p in positions if p["symbol"] == symbol and p["side"] == side)
    new_corr = correlated(symbol)
    corr_r = sum(p["risk_r"] for p in positions if p["side"] == side and correlated(p["symbol"])) if new_corr else None
    m = {"open_r": round(open_r, 3), "side_r": round(side_r, 3), "coin_r": round(coin_r, 3),
         "corr_r": round(corr_r, 3) if corr_r is not None else None, "new_r": new_risk, "factor": factor,
         "corr": cmemo.get(symbol), "n_positions": len(positions),
         "unknown_corr": sorted(s for s, c in cmemo.items() if c is None)}
    why = None
    conflict = [p for p in positions if p["symbol"] == symbol and p["side"] == -side]
    if lim["block_conflict"] and conflict:
        why = (f"conflicting position: a {'short' if side > 0 else 'long'} on {symbol.split('/')[0]} is open "
               f"({', '.join(sorted({str(p.get('timeframe') or '?') for p in conflict}))})")
    elif coin_r + new_risk > lim["max_coin_r"] + EPS:          # structural (one trade per coin): never scaled
        why = (f"{symbol.split('/')[0]} already carries {coin_r:.2f}R on this side (limit {lim['max_coin_r']:g}R "
               "per coin across timeframes)")
    elif open_r + new_risk > lim["max_open_r"] * factor + EPS:
        why = f"open risk {open_r:.2f}R + {new_risk:g}R would pass the portfolio limit of {lim['max_open_r'] * factor:g}R"
    elif side_r + new_risk > lim["max_side_r"] * factor + EPS:
        why = (f"{'long' if side > 0 else 'short'} risk {side_r:.2f}R + {new_risk:g}R would pass the "
               f"{lim['max_side_r'] * factor:g}R limit per direction")
    elif corr_r is not None and corr_r + new_risk > lim["max_corr_r"] * factor + EPS:
        why = (f"BTC-correlated {'long' if side > 0 else 'short'} risk {corr_r:.2f}R + {new_risk:g}R would pass the "
               f"{lim['max_corr_r'] * factor:g}R limit (coins moving with BTC fall together)")
    return {"allowed": why is None, "reason": why, "metrics": m}


def _check_tf(positions: list[dict[str, Any]], symbol: str, side: int, timeframe: str, new_risk: float,
              factor: float, lim: dict[str, Any]) -> dict[str, Any]:
    side = 1 if side > 0 else -1
    tf_r = sum(p["risk_r"] for p in positions if p["side"] == side and p.get("timeframe") == timeframe)
    coin_r = sum(p["risk_r"] for p in positions if p["symbol"] == symbol and p["side"] == side)
    m = {"tf_r": round(tf_r, 3), "coin_r": round(coin_r, 3), "new_r": new_risk, "factor": factor, "timeframe": timeframe,
         "open_r": round(sum(p["risk_r"] for p in positions), 3), "n_positions": len(positions), "quota": True}
    why = None
    conflict = [p for p in positions if p["symbol"] == symbol and p["side"] == -side]
    if lim["block_conflict"] and conflict:
        why = (f"conflicting position: a {'short' if side > 0 else 'long'} on {symbol.split('/')[0]} is open "
               f"({', '.join(sorted({str(p.get('timeframe') or '?') for p in conflict}))})")
    elif coin_r + new_risk > lim["max_coin_r"] + EPS:
        why = (f"{symbol.split('/')[0]} already carries {coin_r:.2f}R on this side (limit {lim['max_coin_r']:g}R "
               "per coin across timeframes)")
    elif tf_r + new_risk > lim["max_tf_side_r"] * factor + EPS:
        why = (f"{timeframe} {'long' if side > 0 else 'short'} risk {tf_r:.2f}R + {new_risk:g}R would pass this "
               f"timeframe's quota of {lim['max_tf_side_r'] * factor:g}R per direction")
    return {"allowed": why is None, "reason": why, "metrics": m}


def record_gate(rt: Any, symbol: str, timeframe: str, side: int, now: int | None = None) -> dict[str, Any]:
    """{'state': 'clear' | 'block' | 'unavailable', 'flag', 'reason', 'metrics', 'drawdown', 'mode'} for a new record call.
    The record's own running call on this coin and timeframe is the same call, not a new entry, so it is left out."""
    out: dict[str, Any] = {"mode": MODE}
    if MODE == "off":
        return {**out, "state": "clear", "reason": None}
    try:
        pos = [p for p in record_positions(rt.db) if not (p["symbol"] == symbol and p["timeframe"] == timeframe)]
        st = record_state(rt, now)
    except Unavailable as exc:
        return {**out, "state": "unavailable", "reason": str(exc)}
    except Exception as exc:
        return {**out, "state": "unavailable", "reason": f"{type(exc).__name__}: {exc}"[:160]}
    out["drawdown"] = {k: st.get(k) for k in ("state", "until", "why")} | {"dd_r": st["drawdown"]["dd_r"]}
    if st["state"] == "HALT":
        return {**out, "state": "block", "flag": DD_FLAG,
                "reason": f"portfolio drawdown halt: {st.get('why')} (new entries resume after the cooling-off period)"}
    factor = LIMITS["probation_factor"] if st["state"] == "PROBATION" else 1.0
    try:
        r = check(pos, symbol, side, lambda s: btc_corr(rt, s), factor=factor, timeframe=timeframe)
    except Exception as exc:
        return {**out, "state": "unavailable", "reason": f"portfolio check failed ({type(exc).__name__}: {exc})"[:160]}
    out["metrics"] = r["metrics"]
    if not r["allowed"]:
        return {**out, "state": "block", "flag": FLAG,
                "reason": r["reason"] + (" (probation after a drawdown: limits halved)" if factor < 1 else "")}
    return {**out, "state": "clear", "reason": None}


def book_check(rt: Any, state: dict[str, Any], symbol: str, side: int, new_risk: float = 1.0) -> dict[str, Any]:
    """The same exposure limits on a bot / challenge book. {'allowed', 'reason', 'metrics'}; unreadable = refused."""
    if MODE == "off":
        return {"allowed": True, "reason": None, "metrics": {}}
    try:
        pos = book_positions(state)
        r = check(pos, symbol, side, lambda s: btc_corr(rt, s), new_risk=new_risk)
    except Exception as exc:
        return {"allowed": False, "reason": f"portfolio check unavailable ({type(exc).__name__}: {exc})"[:160],
                "metrics": {}, "unavailable": True}
    if MODE == "shadow":
        return {**r, "allowed": True, "would_block": not r["allowed"]}
    return r


def summary(rt: Any) -> dict[str, Any]:
    """Aggregate open risk of the record for reports (never raises)."""
    try:
        pos = record_positions(rt.db)
    except Exception as exc:
        return {"available": False, "reason": str(exc)[:160]}
    by_side = {s: round(sum(p["risk_r"] for p in pos if p["side"] == v), 3) for s, v in (("long", 1), ("short", -1))}
    corr = {}
    for side, v in (("long", 1), ("short", -1)):
        corr[side] = round(sum(p["risk_r"] for p in pos if p["side"] == v
                               and (btc_corr(rt, p["symbol"]) is None or btc_corr(rt, p["symbol"]) >= LIMITS["corr_min"])), 3)
    coins: dict[str, float] = {}
    for p in pos:
        coins[p["symbol"]] = round(coins.get(p["symbol"], 0.0) + p["risk_r"] * p["side"], 3)
    st = rt.db.get_setting("portfolio_state", None) or {}
    return {"available": True, "mode": MODE, "positions": len(pos), "pending": sum(p["pending"] for p in pos),
            "open_r": round(sum(p["risk_r"] for p in pos), 3), "by_side_r": by_side, "btc_correlated_r": corr,
            "net_by_coin_r": coins, "limits": LIMITS, "risk_per_trade_pct_ref": RISK_PER_TRADE_PCT_REF,
            "equity_at_risk_pct_ref": round(sum(p["risk_r"] for p in pos) * RISK_PER_TRADE_PCT_REF, 3),
            "drawdown_state": {k: st.get(k) for k in ("state", "since", "until", "why")},
            "drawdown": st.get("drawdown")}
