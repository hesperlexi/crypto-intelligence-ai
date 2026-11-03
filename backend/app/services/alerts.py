"""Alert rules with debounce + cooldown.

An alert fires only when its condition turns from false to true (edge-triggered) AND its cooldown has
elapsed. A condition that simply stays true never re-fires, so alerts cannot spam.
"""
from __future__ import annotations

from typing import Any

from ..db import Database, dumps, loads, new_id, now_ms
from .runtime import USER

ALERT_TYPES = {
    "TRADE_SETUP": "Trade signal with entry, stop-loss and take-profits (params: side, market, min_confidence, confident_only, grade A|any)",
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
    # v2.16 smarter alerts: events of the PUBLIC calls (the record), one per call per event; symbol ALL/USDT = every
    # coin, timeframe "all" = every timeframe. MOOD_CHANGE = the watchlist's 4H breadth flips bullish <-> bearish.
    "ENTRY_REACHED": "Entry reached: a pullback call's limit price traded (the trade is now live)",
    "TP2_REACHED": "A call reaches take-profit 2",
    "TP3_REACHED": "A call reaches take-profit 3 (all targets)",
    "SIGNAL_CLOSED": "A call ends early: stopped out, time limit, closed by the admin, or entry never reached",
    "SIGNAL_UPDATES": "My signals: entry, TP1, TP2, TP3 and stop / early close of each call (param: events)",
    "MOOD_CHANGE": "Market mood flips between bullish and bearish (4H regimes across the watchlist)",
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


def _fmt(v: float | None) -> str:
    return "—" if v is None else f"{v:,.6g}"


def trade_message(a: dict[str, Any], market: str = "spot") -> str:
    """One readable line with everything needed to act on (or paper-trade) the call."""
    sym, tf = a["symbol"], a["timeframe"]
    st = a.get("setup") or {}
    side = "LONG" if st.get("side_int", 1) > 0 else "SHORT"
    if a.get("decision") == "BUY ON PULLBACK":
        side = "LONG on pullback"
    entry = st.get("ideal_entry") or a.get("price")
    zone = st.get("entry_zone") or [entry, entry]
    tps = " · ".join(f"TP{i + 1} {_fmt(t['price'])}" for i, t in enumerate(st.get("targets") or []))
    probs = (a.get("forecast") or {}).get("probabilities") or {}
    p_dir = probs.get("up") if st.get("side_int", 1) > 0 else probs.get("down")
    grade = f" [grade {a['grade']}]" if a.get("grade") else ""
    msg = (f"{sym} {tf} {side}{' (futures)' if market == 'futures' else ''}{grade}: entry {_fmt(zone[0])}–{_fmt(zone[1])} "
           f"(ideal {_fmt(entry)}), stop-loss {_fmt(st.get('stop'))} ({st.get('risk_pct', 0):.1f}%), {tps}, "
           f"R:R 1:{st.get('risk_reward', 0):.1f}, confidence {(a.get('confidence') or 0):.0%}")
    if p_dir is not None:
        msg += f", P({'up' if st.get('side_int', 1) > 0 else 'down'}) {p_dir:.0%}"
    if market == "futures" and st.get("stop") and entry:
        from ..engine import futures as F

        tf_ = a.get("timeframe")
        lev = F.signal_leverage(entry, st["stop"], a.get("symbol"), a.get("grade"), tf_)
        liq = (lambda L: _fmt(F.liquidation_price(entry, st.get('side_int', 1), L, symbol=a.get('symbol'))))
        if lev and F.in_policy(tf_):
            msg += f", leverage {lev}x chosen by engine (liquidation {liq(lev)})"
        elif lev:
            msg += f", suggested leverage {lev}x (liquidation {liq(lev)})"         # v2.13 (non-15m)
        else:
            msg += f", futures: {F.TOO_WIDE_REASON}"
    return msg


def _condition(alert: dict[str, Any], a: dict[str, Any], db: Database) -> tuple[bool, str]:
    t, p = alert["type"], alert["params"]
    sym, tf = a["symbol"], a["timeframe"]
    price = a.get("price")
    reg = a.get("regime") or {}
    if t == "TRADE_SETUP":
        st = a.get("setup") or {}
        if a.get("decision") not in ("BUY", "BUY ON PULLBACK", "SELL") or not st.get("valid"):
            return False, ""
        side = st.get("side_int", 1)
        want = str(p.get("side", "any")).lower()
        if (want == "long" and side < 0) or (want == "short" and side > 0):
            return False, ""
        if (a.get("confidence") or 0) < float(p.get("min_confidence", 0) or 0):
            return False, ""
        if p.get("confident_only") and not ((a.get("forecast") or {}).get("confident_call") or {}).get("is_confident"):
            return False, ""
        if str(p.get("grade", "any")).upper() == "A" and a.get("grade") != "A":
            return False, ""
        return True, trade_message(a, "futures" if p.get("market") == "futures" else "spot")
    if t == "BUY_SIGNAL":
        ok = a.get("decision") in ("BUY", "BUY ON PULLBACK")
        return ok, (trade_message(a) if ok and (a.get("setup") or {}).get("valid") else f"{sym} {tf}: decision {a.get('decision')} at {price:,.6g}")
    if t == "SELL_SIGNAL":
        ok = a.get("decision") == "SELL"
        return ok, (trade_message(a) if ok and (a.get("setup") or {}).get("valid") else f"{sym} {tf}: decision SELL at {price:,.6g}")
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
        if r["type"] in EVENT_TYPES:          # v2.16: judged on the record's events / the market mood (lifecycle(), mood())
            continue
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


# ---- v2.16 smarter alerts: call events (record) and market-mood flips -----------------------------------------
# Delivered like every other alert: an alert_events row (shown on the member's Alerts page through alerts_u_{uid},
# which the engine already writes when it changes) + the existing push. One event per rule per call per event kind
# (alert_marks), a member gets at most MAX_EVENTS_PER_DAY of these a day (Firestore free plan: each event can change
# the member's alerts document once), and a new rule never fires for events that had already happened ("primed").
EVENT_TYPES = ("ENTRY_REACHED", "TP2_REACHED", "TP3_REACHED", "SIGNAL_CLOSED", "SIGNAL_UPDATES", "MOOD_CHANGE")
CALL_EVENTS = ("entry", "tp1", "tp2", "tp3", "closed")
TYPE_EVENTS = {"ENTRY_REACHED": ("entry",), "TP2_REACHED": ("tp2",), "TP3_REACHED": ("tp3",), "SIGNAL_CLOSED": ("closed",)}
EVENT_TYPE_OF = {"entry": "ENTRY_REACHED", "tp1": "TARGET_REACHED", "tp2": "TP2_REACHED", "tp3": "TP3_REACHED",
                 "closed": "SIGNAL_CLOSED"}
ALL_SYMBOLS = "ALL/USDT"            # "every coin" (the rules' symbol pattern needs a pair)
ALL_TFS = "all"
MAX_EVENTS_PER_DAY = 30
SCAN_DAYS = 3                       # calls followed for events: every open one and those closed in the last 3 days
MOOD_TF = "4h"
MOOD_SHARE = 0.6                    # same 60 % rule as the Home page's market mood (scanner.dashboard)
DAY_MS = 86_400_000
SCHEMA = ("CREATE TABLE IF NOT EXISTS alert_marks (alert_id TEXT NOT NULL, mark TEXT NOT NULL, created_at BIGINT NOT NULL, "
          "PRIMARY KEY (alert_id, mark))",)


def ensure(db: Database) -> None:
    for s in SCHEMA:
        db.execute(s)


def _coin(sym: str) -> str:
    b = str(sym).split("/")[0]
    return "GOLD" if b == "PAXG" else b


def _px(v: Any) -> str:
    from ..pricefmt import fmt_price
    return fmt_price(v)


def call_events(r: dict[str, Any]) -> list[str]:
    """Events a call has reached so far: entry (a pending limit / confirmation filled after publication), tp1-3, closed
    (any end that is not take-profit 3: stop, break-even after TP1, time limit, admin close, entry never reached)."""
    out = []
    if r.get("fill_status") == "FILLED" and r.get("filled_at") and int(r["filled_at"]) > int(r.get("created_at") or 0):
        out.append("entry")
    for i in (1, 2, 3):
        if r.get(f"tp{i}_hit"):
            out.append(f"tp{i}")
    if r.get("status") not in ("OPEN", "INFO", "TP3", None) or (r.get("status") == "TP3" and r.get("exit_reason") == "admin_close"):
        out.append("closed")
    return out


def call_message(r: dict[str, Any], ev: str) -> str:
    """One plain line per event, from the record's own numbers (results after fees)."""
    from .tracking import result_fields
    side = "LONG" if int(r.get("side") or 0) > 0 else "SHORT"
    head = f"{_coin(r['symbol'])} {str(r['timeframe']).upper()} {side}"
    if ev == "entry":
        return f"{head}: entry reached at {_px(r.get('entry'))}, the trade is live. Stop {_px(r.get('stop'))} · TP1 {_px(r.get('tp1'))}"
    if ev in ("tp1", "tp2", "tp3"):
        i = int(ev[2])
        after = {1: "stop moves to break-even", 2: "stop moves to TP1", 3: "all targets hit"}[i]
        return f"{head}: TP{i} {_px(r.get(f'tp{i}'))} hit, {after}"
    res = result_fields(r).get("return_pct") if r.get("return_pct") is not None else None
    why = {"STOPPED": "stopped out", "EXPIRED": "closed at its time limit", "NOT_FILLED": "entry never reached, cancelled (not counted)",
           "VOID": "no market data, void (not counted)", "TP1": "closed after TP1 (rest at break-even or time limit)",
           "TP2": "closed after TP2 (rest at TP1 or time limit)", "TP3": "closed"}.get(str(r.get("status")), "closed")
    if r.get("exit_reason") == "admin_close":
        why = "closed by the admin at the market price"
    return f"{head}: {why}" + (f" · {res:+.2f}% after fees" if res is not None else "")


def _wants(rule: dict[str, Any]) -> tuple[str, ...]:
    if rule["type"] == "SIGNAL_UPDATES":
        ev = rule["params"].get("events") if isinstance(rule.get("params"), dict) else None
        ev = tuple(e for e in (ev or CALL_EVENTS) if e in CALL_EVENTS) if isinstance(ev, list) else CALL_EVENTS
        return ev or CALL_EVENTS
    return TYPE_EVENTS.get(rule["type"], ())


def _matches(rule: dict[str, Any], r: dict[str, Any]) -> bool:
    return (rule["symbol"] in (ALL_SYMBOLS, r["symbol"])) and (rule["timeframe"] in (ALL_TFS, r["timeframe"]))


def _mark(db: Database, alert_id: str, mark: str, now: int) -> bool:
    """True the first time (alert, mark) is seen."""
    return db.execute("INSERT INTO alert_marks (alert_id, mark, created_at) VALUES (?, ?, ?) ON CONFLICT (alert_id, mark) DO NOTHING",
                      (alert_id, mark, now)) > 0


def _used_today(db: Database, user_id: str, now: int) -> int:
    start = now - now % DAY_MS
    marks = ",".join("?" * len(EVENT_TYPES) + "?" * 2)
    row = db.one(f"SELECT COUNT(*) AS n FROM alert_events e JOIN alerts a ON a.id = e.alert_id WHERE a.user_id = ? "
                 f"AND e.created_at >= ? AND e.type IN ({marks})",
                 (user_id, start, *EVENT_TYPES, "TARGET_REACHED", "STOP_REACHED"))
    return int((row or {}).get("n") or 0)


def _fire(db: Database, rule: dict[str, Any], symbol: str, type_: str, msg: str, now: int,
          budget: dict[str, int]) -> dict[str, Any] | None:
    uid = rule["user_id"]
    if uid not in budget:
        budget[uid] = MAX_EVENTS_PER_DAY - _used_today(db, uid, now)
    if budget[uid] <= 0:
        return None                                   # daily cap reached: seen (marked), not delivered
    budget[uid] -= 1
    ev = {"id": new_id(), "alert_id": rule["id"], "created_at": now, "symbol": symbol, "type": type_, "message": msg}
    db.execute("INSERT INTO alert_events (id, alert_id, created_at, symbol, type, message) VALUES (?, ?, ?, ?, ?, ?)",
               list(ev.values()))
    db.execute("UPDATE alerts SET last_fired_at = ? WHERE id = ?", (now, rule["id"]))
    return ev


def _rules(db: Database, types: tuple[str, ...]) -> list[dict[str, Any]]:
    rows = db.query(f"SELECT * FROM alerts WHERE enabled = 1 AND type IN ({','.join('?' * len(types))})", types)
    for r in rows:
        r["params"] = loads(r["params"], {}) or {}
    return rows


def lifecycle(db: Database, now: int | None = None) -> list[dict[str, Any]]:
    """Events of the public calls (signals) for the member rules ENTRY_REACHED / TP2_REACHED / TP3_REACHED /
    SIGNAL_CLOSED / SIGNAL_UPDATES. Returns the events that fired (for the push). Never changes the record."""
    ensure(db)
    now = now_ms() if now is None else now
    rules = _rules(db, ("ENTRY_REACHED", "TP2_REACHED", "TP3_REACHED", "SIGNAL_CLOSED", "SIGNAL_UPDATES"))
    if not rules:
        return []
    # every open call (a 3D call can run for 90 days) and the calls closed in the last SCAN_DAYS days
    calls = db.query("SELECT * FROM signals WHERE side != 0 AND status != 'INFO' AND (status = 'OPEN' OR closed_at >= ?) "
                     "ORDER BY created_at", (now - SCAN_DAYS * DAY_MS,))
    fired: list[dict[str, Any]] = []
    budget: dict[str, int] = {}
    for rule in rules:
        primed = rule.get("last_state") == "primed"
        want = _wants(rule)
        for r in calls:
            if not _matches(rule, r):
                continue
            for ev in call_events(r):
                if ev not in want or not _mark(db, rule["id"], f"{r['id']}:{ev}", now) or not primed:
                    continue
                e = _fire(db, rule, r["symbol"], EVENT_TYPE_OF[ev] if rule["type"] == "SIGNAL_UPDATES" else rule["type"],
                          call_message(r, ev), now, budget)
                if e:
                    fired.append(e)
        if not primed:            # a new rule: what already happened is marked as seen, never sent
            db.execute("UPDATE alerts SET last_state = 'primed' WHERE id = ?", (rule["id"],))
    return fired


def mood_of(analyses: dict[tuple[str, str], dict[str, Any]], tf: str = MOOD_TF) -> dict[str, Any] | None:
    """Watchlist breadth on `tf`: how many coins sit in a bullish / bearish regime (60 % rule, as on Home)."""
    groups = [((a.get("regime") or {}).get("group")) for (s, t), a in analyses.items() if t == tf and a.get("status") == "OK"]
    groups = [g for g in groups if g]
    if not groups:
        return None
    n, bull, bear = len(groups), groups.count("Bull"), groups.count("Bear")
    status = "BULL" if bull / n >= MOOD_SHARE else "BEAR" if bear / n >= MOOD_SHARE else "NEUTRAL"
    return {"status": status, "bull": bull, "bear": bear, "neutral": n - bull - bear, "assets": n, "timeframe": tf}


def mood(db: Database, analyses: dict[tuple[str, str], dict[str, Any]], now: int | None = None) -> list[dict[str, Any]]:
    """MOOD_CHANGE: fires when the watchlist's 4H mood flips from bullish to bearish or back (a neutral spell in between
    is fine; neutral itself never fires). The last side is kept in the engine's settings."""
    ensure(db)
    now = now_ms() if now is None else now
    m = mood_of(analyses)
    if not m:
        return []
    st = db.get_setting("market_mood", None) or {}
    flip = None
    if m["status"] in ("BULL", "BEAR"):
        if st.get("side") in ("BULL", "BEAR") and st["side"] != m["status"]:
            flip = {"from": st["side"], "to": m["status"], "at": now}
        if st.get("side") != m["status"]:
            st = {**st, "side": m["status"], "since": now}
    st = {**st, "status": m["status"], "checked_at": now, **({"last_flip": flip} if flip else {})}
    db.set_setting("market_mood", st)
    if not flip:
        return []
    word = {"BULL": "bullish", "BEAR": "bearish"}
    msg = (f"Market mood turned {word[flip['to']]} (was {word[flip['from']]}): {m['bull']} of {m['assets']} coins in a bullish "
           f"4H regime, {m['bear']} bearish")
    fired, budget = [], {}
    for rule in _rules(db, ("MOOD_CHANGE",)):
        cooled = rule["last_fired_at"] is None or now - rule["last_fired_at"] >= rule["cooldown_s"] * 1000
        if not cooled or not _mark(db, rule["id"], f"mood:{now}", now):
            continue
        e = _fire(db, rule, ALL_SYMBOLS, "MOOD_CHANGE", msg, now, budget)
        if e:
            fired.append(e)
    return fired
