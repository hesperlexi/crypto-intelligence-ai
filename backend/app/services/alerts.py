"""Alert rules with debounce + cooldown.

An alert fires only when its condition turns from false to true (edge-triggered) AND its cooldown has
elapsed. A condition that simply stays true never re-fires, so alerts cannot spam.
"""
from __future__ import annotations

from typing import Any

from ..db import Database, dumps, loads, new_id, now_ms
from .runtime import USER

ALERT_TYPES = {
    "BUY_SIGNAL": "Decision turns BUY / BUY ON PULLBACK",
    "SELL_SIGNAL": "Decision turns SELL",
    "BULLISH_REGIME": "Regime changes to a bullish regime",
    "BEARISH_REGIME": "Regime changes to a bearish regime",
    "BREAKOUT": "Close above the 20-bar range on above-average volume",
    "BREAKDOWN": "Close below the 20-bar range on above-average volume",
    "TARGET_REACHED": "Latest tracked signal reaches TP1",
    "STOP_REACHED": "Latest tracked signal hits its stop",
    "CONFIDENCE_ABOVE": "Signal confidence rises above a threshold (param: threshold, 0-1)",
    "VOLATILITY_SPIKE": "Volatility state becomes HIGH or EXTREME",
    "PRICE_ABOVE": "Price rises above a level (param: level)",
    "PRICE_BELOW": "Price falls below a level (param: level)",
}


def create_alert(db: Database, type_: str, symbol: str, timeframe: str = "4h", params: dict[str, Any] | None = None,
                 cooldown_s: int = 3600) -> dict[str, Any]:
    if type_ not in ALERT_TYPES:
        raise ValueError(f"unknown alert type {type_}")
    row = {"id": new_id(), "user_id": USER, "type": type_, "symbol": symbol, "timeframe": timeframe,
           "params": dumps(params or {}), "cooldown_s": int(cooldown_s), "created_at": now_ms()}
    db.execute("INSERT INTO alerts (id, user_id, type, symbol, timeframe, params, cooldown_s, enabled, created_at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)", list(row.values()))
    return {**row, "params": params or {}, "enabled": 1}


def list_alerts(db: Database) -> list[dict[str, Any]]:
    rows = db.query("SELECT * FROM alerts WHERE user_id = ? ORDER BY created_at DESC", (USER,))
    for r in rows:
        r["params"] = loads(r["params"], {})
    return rows


def delete_alert(db: Database, alert_id: str) -> None:
    db.execute("DELETE FROM alerts WHERE id = ? AND user_id = ?", (alert_id, USER))


def set_enabled(db: Database, alert_id: str, enabled: bool) -> None:
    db.execute("UPDATE alerts SET enabled = ?, last_state = NULL WHERE id = ?", (int(enabled), alert_id))


def events(db: Database, limit: int = 100) -> list[dict[str, Any]]:
    return db.query("SELECT * FROM alert_events ORDER BY created_at DESC LIMIT ?", (limit,))


def mark_read(db: Database) -> None:
    db.execute("UPDATE alert_events SET is_read = 1 WHERE is_read = 0")


def _condition(alert: dict[str, Any], a: dict[str, Any], db: Database) -> tuple[bool, str]:
    t, p = alert["type"], alert["params"]
    sym, tf = a["symbol"], a["timeframe"]
    price = a.get("price")
    reg = a.get("regime") or {}
    if t == "BUY_SIGNAL":
        return a.get("decision") in ("BUY", "BUY ON PULLBACK"), f"{sym} {tf}: decision {a.get('decision')} at {price:,.6g}"
    if t == "SELL_SIGNAL":
        return a.get("decision") == "SELL", f"{sym} {tf}: decision SELL at {price:,.6g}"
    if t == "BULLISH_REGIME":
        return reg.get("group") == "Bull", f"{sym} {tf}: regime is now {reg.get('regime')}"
    if t == "BEARISH_REGIME":
        return reg.get("group") == "Bear", f"{sym} {tf}: regime is now {reg.get('regime')}"
    if t == "BREAKOUT":
        return (a.get("now") or {}).get("breakout") == 1, f"{sym} {tf}: breakout above the 20-bar range at {price:,.6g}"
    if t == "BREAKDOWN":
        return (a.get("now") or {}).get("breakout") == -1, f"{sym} {tf}: breakdown below the 20-bar range at {price:,.6g}"
    if t in ("TARGET_REACHED", "STOP_REACHED"):
        s = db.one("SELECT * FROM signals WHERE symbol = ? AND timeframe = ? AND side != 0 ORDER BY created_at DESC LIMIT 1",
                   (sym, tf))
        if not s:
            return False, ""
        if t == "TARGET_REACHED":
            return bool(s["tp1_hit"]), f"{sym} {tf}: TP1 {s['tp1']:,.6g} reached on the {s['signal']} signal"
        return bool(s["stop_hit"]), f"{sym} {tf}: stop {s['stop']:,.6g} hit on the {s['signal']} signal"
    if t == "CONFIDENCE_ABOVE":
        c, thr = a.get("confidence"), float(p.get("threshold", 0.6))
        return c is not None and c >= thr, f"{sym} {tf}: confidence {0 if c is None else c:.0%} ≥ {thr:.0%}"
    if t == "VOLATILITY_SPIKE":
        st = (a.get("volatility") or {}).get("state")
        return st in ("HIGH", "EXTREME"), f"{sym} {tf}: volatility is {st}"
    if t in ("PRICE_ABOVE", "PRICE_BELOW"):
        if price is None or p.get("level") is None:
            return False, ""
        lvl = float(p["level"])
        ok = price > lvl if t == "PRICE_ABOVE" else price < lvl
        return ok, f"{sym}: price {price:,.6g} {'above' if t == 'PRICE_ABOVE' else 'below'} {lvl:,.6g}"
    return False, ""


def evaluate(db: Database, a: dict[str, Any], now: int | None = None) -> list[dict[str, Any]]:
    """Check every enabled alert for this analysis; returns the events that fired."""
    now = now_ms() if now is None else now
    fired = []
    if a.get("status") != "OK":
        return fired
    rows = db.query("SELECT * FROM alerts WHERE enabled = 1 AND symbol = ? AND timeframe = ?", (a["symbol"], a["timeframe"]))
    for r in rows:
        r["params"] = loads(r["params"], {})
        ok, msg = _condition(r, a, db)
        was = r["last_state"] == "1"
        first_seen = r["last_state"] is None     # a rule created while its condition is already true does not fire
        cooled = r["last_fired_at"] is None or now - r["last_fired_at"] >= r["cooldown_s"] * 1000
        if ok and not was and not first_seen and cooled:
            ev = {"id": new_id(), "alert_id": r["id"], "created_at": now, "symbol": a["symbol"], "type": r["type"],
                  "message": msg}
            db.execute("INSERT INTO alert_events (id, alert_id, created_at, symbol, type, message) VALUES (?, ?, ?, ?, ?, ?)",
                       list(ev.values()))
            db.execute("UPDATE alerts SET last_state = '1', last_fired_at = ? WHERE id = ?", (now, r["id"]))
            fired.append(ev)
        elif ok and not was and not first_seen and not cooled:
            pass   # still cooling down: keep last_state false so it can fire once the cooldown ends
        else:
            db.execute("UPDATE alerts SET last_state = ? WHERE id = ?", ("1" if ok else "0", r["id"]))
    return fired
