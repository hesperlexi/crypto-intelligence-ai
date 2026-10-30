"""Live prediction tracking: every forecast is stored when made and scored once its outcome is known.

Nothing here is back-filled: the live statistics only contain predictions that were actually issued by
this installation, in real time, before the outcome existed.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np

from ..data.base import tf_ms

PATH_TF = "15m"           # live record follows every signal on 15-minute candles (same as the bots)
from ..db import Database, dumps, loads, new_id, now_ms
from ..ml.metrics import brier, calibration_label, ece, reliability_table, wilson

DAY = 86_400_000


def log_prediction(db: Database, symbol: str, timeframe: str, fc: dict[str, Any]) -> None:
    """Idempotent per (symbol, timeframe, bar, model version)."""
    p = fc["probabilities"]
    detail = {"per_model": [{k: m.get(k) for k in ("name", "calibrated", "weight")} for m in fc["per_model"]
                            if "calibrated" in m],
              "intervals": (fc.get("distribution") or {}).get("intervals"),
              "agreement": fc.get("model_agreement")}
    db.execute(
        "INSERT INTO predictions (id, created_at, symbol, timeframe, bar_ts, target_ts, model_version_id, price, "
        "p_down, p_neutral, p_up, predicted_class, neutral_band, expected_return, confidence, detail) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (symbol, timeframe, bar_ts, model_version_id) DO NOTHING",
        (new_id(), now_ms(), symbol, timeframe, fc["bar_ts"], fc["bar_ts"] + 2 * tf_ms(timeframe), fc["model_version"],
         fc["price"], p["down"], p["neutral"], p["up"], fc["predicted_class"], fc["neutral_band"],
         fc.get("expected_return"), (fc.get("confidence") or {}).get("confidence"), dumps(detail)))


def resolve_outcomes(rt: Any) -> int:
    """Score predictions whose target candle has closed. Returns how many were resolved."""
    db = rt.db
    rows = db.query(
        "SELECT p.* FROM predictions p LEFT JOIN prediction_outcomes o ON o.prediction_id = p.id "
        "WHERE o.prediction_id IS NULL AND p.target_ts <= ? ORDER BY p.bar_ts LIMIT 2000", (now_ms(),))
    done = 0
    for r in rows:
        df = rt.candles(r["symbol"], r["timeframe"])
        nxt = df[df["ts"] == r["bar_ts"] + tf_ms(r["timeframe"])]
        if nxt.empty:
            continue  # candle not stored (yet): try again on the next pass
        ret = float(nxt["close"].iloc[0] / r["price"] - 1)
        cls = 2 if ret > r["neutral_band"] else 0 if ret < -r["neutral_band"] else 1
        db.execute("INSERT INTO prediction_outcomes (prediction_id, resolved_at, actual_return, actual_class, correct) "
                   "VALUES (?, ?, ?, ?, ?) ON CONFLICT (prediction_id) DO NOTHING",
                   (r["id"], now_ms(), ret, cls, int(cls == r["predicted_class"])))
        done += 1
    return done


def _resolved(db: Database, symbol: str | None, timeframe: str | None, since: int = 0, version: str | None = None,
              limit: int = 5000) -> list[dict[str, Any]]:
    sql = ("SELECT p.id, p.created_at, p.symbol, p.timeframe, p.bar_ts, p.price, p.p_down, p.p_neutral, p.p_up, "
           "p.predicted_class, p.expected_return, p.confidence, p.model_version_id, p.detail, "
           "o.actual_return, o.actual_class, o.correct FROM predictions p "
           "JOIN prediction_outcomes o ON o.prediction_id = p.id WHERE p.created_at >= ?")
    args: list[Any] = [since]
    for col, val in (("p.symbol", symbol), ("p.timeframe", timeframe), ("p.model_version_id", version)):
        if val:
            sql += f" AND {col} = ?"
            args.append(val)
    return db.query(sql + " ORDER BY p.bar_ts DESC LIMIT ?", args + [limit])


def _acc(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"n": 0, "accuracy": None, "ci95": None}
    k = sum(r["correct"] for r in rows)
    lo, hi = wilson(k, n)
    return {"n": n, "accuracy": k / n, "ci95": [lo, hi]}


def live_stats(db: Database, symbol: str | None = None, timeframe: str | None = None, last: int = 100) -> dict[str, Any]:
    now = now_ms()
    rows = _resolved(db, symbol, timeframe)
    pending = db.one(
        "SELECT COUNT(*) AS n FROM predictions p LEFT JOIN prediction_outcomes o ON o.prediction_id = p.id "
        "WHERE o.prediction_id IS NULL" + (" AND p.symbol = ?" if symbol else "") + (" AND p.timeframe = ?" if timeframe else ""),
        [v for v in (symbol, timeframe) if v])
    out: dict[str, Any] = {
        "symbol": symbol, "timeframe": timeframe, "resolved": len(rows), "pending": int(pending["n"]) if pending else 0,
        "overall": _acc(rows), "last_n": {"window": last, **_acc(rows[:last])},
        "rolling": {f"{d}d": _acc([r for r in rows if r["created_at"] >= now - d * DAY]) for d in (7, 30, 90)},
    }
    if len(rows) >= 20:
        P = np.array([[r["p_down"], r["p_neutral"], r["p_up"]] for r in rows], float)
        y = np.array([r["actual_class"] for r in rows], int)
        e = ece(P, y)
        calls = [r for r in rows if r["predicted_class"] != 1]
        out.update({
            "brier": brier(P, y), "ece": e, "calibration": calibration_label(e),
            "reliability": reliability_table(P, y),
            "directional": {"n": len(calls), "accuracy": float(np.mean([
                (r["actual_return"] > 0) == (r["predicted_class"] == 2) for r in calls])) if calls else None},
            "mean_abs_error": float(np.mean([abs((r["expected_return"] or 0) - r["actual_return"]) for r in rows])),
        })
    else:
        out["note"] = (f"{len(rows)} live predictions have been scored so far; calibration and Brier are shown once "
                       "at least 20 have resolved.")
    out["recent"] = [{"ts": r["bar_ts"], "symbol": r["symbol"], "timeframe": r["timeframe"], "price": r["price"],
                      "predicted": ["DOWN", "NEUTRAL", "UP"][r["predicted_class"]],
                      "probability": max(r["p_down"], r["p_neutral"], r["p_up"]),
                      "actual": ["DOWN", "NEUTRAL", "UP"][r["actual_class"]], "actual_return": r["actual_return"],
                      "correct": bool(r["correct"]), "model_version": r["model_version_id"]} for r in rows[:last]]
    return out


def live_multipliers(db: Database, bundle: dict[str, Any], min_n: int = 50) -> dict[str, float]:
    """Halve the ensemble weight of any model whose LIVE Brier score is worse than the class-prior forecast
    (needs >= `min_n` scored live predictions for this model version)."""
    rows = _resolved(db, bundle["symbol"], bundle["timeframe"], version=bundle["version"], limit=300)
    if len(rows) < min_n:
        return {}
    y = np.array([r["actual_class"] for r in rows], int)
    base = brier(np.tile(bundle["prior"], (len(y), 1)), y)
    per: dict[str, list[list[float]]] = {}
    for r in rows:
        for m in loads(r["detail"], {}).get("per_model", []):
            per.setdefault(m["name"], []).append(m["calibrated"])
    return {name: 0.5 for name, ps in per.items() if len(ps) == len(y) and brier(np.array(ps, float), y) > base}


def performance_windows(db: Database, bundle: dict[str, Any], recent_days: int = 30) -> dict[str, int] | None:
    """Recent live hits vs the model's own out-of-sample record, for the drift test."""
    rows = _resolved(db, bundle["symbol"], bundle["timeframe"], since=now_ms() - recent_days * DAY)
    oos = bundle["oos"]
    return {"recent_hits": int(sum(r["correct"] for r in rows)), "recent_n": len(rows),
            "ref_hits": int(oos["hit"].sum()), "ref_n": int(len(oos["hit"]))}


# ---- signal history ---------------------------------------------------------------------------------------
#
# v2.5 (audit v1):
#   * entry = the plan's ideal entry (the price the signal card shows, the one stop and targets are built from);
#     BUY / SELL are market entries (fill_status FILLED at creation), BUY ON PULLBACK waits for the price to trade
#     through the entry (PENDING -> FILLED, or NOT_FILLED after FILL_WINDOW_BARS bars: never entered, no return,
#     not counted in any statistic - but listed);
#   * a call is followed only on candles that OPEN after it was published (no look-ahead into the forming candle);
#   * at most one OPEN / PENDING call per coin and timeframe; re-entry cooldown and cap after a close;
#   * calls whose candles never arrive expire on the wall clock (EXPIRED at the last known close, or VOID - no
#     market data at all after publication - with no return, not counted, shown as a 'void' number);
#   * every trade-management step is written to the `decisions` table.

TRADE_DECISIONS = ("BUY", "BUY ON PULLBACK", "SELL")
CLOSED_STATUSES = ("STOPPED", "TP1", "TP2", "TP3", "EXPIRED")     # count in statistics (with a return)
NO_RESULT_STATUSES = ("NOT_FILLED", "VOID")                       # listed, never counted
UNSTABLE_REGIMES = ("HIGH-VOLATILITY / UNSTABLE",)
DECISIONS_KEEP_DAYS = 120


def versions() -> tuple[str, str]:
    from ..brand import APP_VERSION
    from ..config import ENGINE_VERSION
    return APP_VERSION, ENGINE_VERSION


def log_decision(db: Database, rule: str, symbol: str | None, timeframe: str | None, signal_id: str | None = None,
                 inputs: dict[str, Any] | None = None, ai_rationale: str | None = None, ts: int | None = None,
                 dedupe: bool = False) -> bool:
    """One row in `decisions`. With dedupe, a rule repeated with the same inputs for the same pair is not stored again."""
    app_v, eng_v = versions()
    text = dumps(inputs or {})
    if dedupe:
        recent = db.query("SELECT rule, inputs FROM decisions WHERE symbol = ? AND timeframe = ? ORDER BY ts DESC LIMIT 6",
                          (symbol, timeframe))
        if any(r["rule"] == rule and r["inputs"] == text for r in recent):
            return False
    db.execute("INSERT INTO decisions (id, ts, symbol, timeframe, signal_id, rule, inputs, ai_rationale, engine_version, "
               "app_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
               (new_id(), ts or now_ms(), symbol, timeframe, signal_id, rule, text, ai_rationale, eng_v, app_v))
    return True


def recent_decisions(db: Database, limit: int = 100) -> dict[str, Any]:
    newest = db.one("SELECT MAX(ts) AS t FROM decisions")
    if newest and newest["t"]:
        db.execute("DELETE FROM decisions WHERE ts < ?", (int(newest["t"]) - DECISIONS_KEEP_DAYS * DAY,))
    rows = db.query("SELECT * FROM decisions ORDER BY ts DESC, id DESC LIMIT ?", (limit,))
    return {"decisions": [{"ts": r["ts"], "symbol": r["symbol"], "timeframe": r["timeframe"], "signal_id": r["signal_id"],
                           "rule": r["rule"], "inputs": loads(r["inputs"], {}), "ai_rationale": r["ai_rationale"],
                           "engine_version": r["engine_version"], "app_version": r["app_version"]} for r in rows]}


def manage_params(db: Database | None = None) -> dict[str, Any]:
    """Current trade-management parameters (settings; AI-suggested give-back / trail values only with AI_PARAMS=1)."""
    from ..config import LIMITS, settings
    p = settings.manage_params()
    if settings.ai_params and db is not None:
        ai = db.get_setting("ai_manage_params", {}) or {}
        for k in ("giveback_arm_r", "giveback_frac", "trail_atr_k"):
            if isinstance(ai.get(k), (int, float)):
                lo, hi = LIMITS[k]
                p[k] = float(min(hi, max(lo, ai[k])))
    return p


def _side_of(decision: str) -> int:
    return 1 if decision in ("BUY", "BUY ON PULLBACK") else -1 if decision == "SELL" else 0


def open_call(db: Database, symbol: str, timeframe: str, table: str = "signals") -> dict[str, Any] | None:
    return db.one(f"SELECT * FROM {table} WHERE symbol = ? AND timeframe = ? AND status = 'OPEN' AND side != 0 "
                  "ORDER BY created_at DESC LIMIT 1", (symbol, timeframe))


def margin_fields(r: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """`leverage` (the card's suggested leverage: stored at log time, else derived from the row's entry and stop
    with the same function) and `roi_pct` = return_pct x leverage, the result on margin."""
    from ..engine import futures as F
    p = payload if payload is not None else r.get("payload")
    if isinstance(p, str):
        p = loads(p, {})
    lev = (p or {}).get("leverage") if isinstance(p, dict) else None
    if not lev:
        lev = F.signal_leverage(r.get("entry"), r.get("stop")) if r.get("side") else None
    return {"leverage": int(lev) if lev else None, "roi_pct": F.roi_on_margin(r.get("return_pct"), lev)}


def call_view(r: dict[str, Any] | None) -> dict[str, Any] | None:
    """The contract's `call` object for analysis / futures rows."""
    if not r:
        return None
    return {"id": r["id"], "status": r["status"], "fill_status": r.get("fill_status") or ("FILLED" if r["side"] else None),
            "side": "LONG" if r["side"] > 0 else "SHORT", "entry": r["entry"], "stop": r["stop"], "tp1": r["tp1"],
            "tp2": r["tp2"], "tp3": r["tp3"], "peak_r": r.get("peak_r"), "peak_pct": r.get("peak_pct"),
            "exit_reason": r.get("exit_reason"), "managed": r.get("managed") or 0, "created_at": r["created_at"],
            "return_pct": r.get("return_pct"), "closed_at": r.get("closed_at"), **margin_fields(r)}


def current_call(db: Database, symbol: str, timeframe: str) -> dict[str, Any] | None:
    """The call being tracked for this coin/timeframe: the open one, else the latest closed one from the last day."""
    r = open_call(db, symbol, timeframe)
    if r is None:
        r = db.one("SELECT * FROM signals WHERE symbol = ? AND timeframe = ? AND side != 0 AND status != 'OPEN' "
                   "AND closed_at >= ? ORDER BY created_at DESC LIMIT 1", (symbol, timeframe, now_ms() - DAY))
    return call_view(r)


def latest_ai(db: Database, symbol: str, timeframe: str) -> dict[str, Any] | None:
    """The advisor note of the latest call on this coin/timeframe (contract: analysis row `ai`), if any."""
    r = db.one("SELECT payload FROM signals WHERE symbol = ? AND timeframe = ? AND side != 0 ORDER BY created_at DESC LIMIT 1",
               (symbol, timeframe))
    ai = (loads(r["payload"], {}) or {}).get("ai") if r else None
    if not ai:
        return None
    return {k: ai.get(k) for k in ("rationale", "regime", "model", "at") if k in ai}


def entry_gate(db: Database, a: dict[str, Any], table: str = "signals", now: int | None = None) -> tuple[str, str | None, dict]:
    """('ok' | 'already_open' | 'cooldown' | 'reentry_cap' | 'reentry_regime', reason, inputs) for a tradable decision."""
    from ..config import settings
    now = now or now_ms()
    sym, tf = a["symbol"], a["timeframe"]
    side = _side_of(a["decision"])
    step = tf_ms(tf)
    cur = open_call(db, sym, tf, table)
    if cur:
        return ("already_open", f"a {tf} {'long' if cur['side'] > 0 else 'short'} call on this coin is still "
                f"{'waiting for its entry' if cur.get('fill_status') == 'PENDING' else 'running'}; no new call until it closes",
                {"open_id": cur["id"], "decision": a["decision"]})
    last = db.one(f"SELECT * FROM {table} WHERE symbol = ? AND timeframe = ? AND side != 0 AND status != 'OPEN' "
                  "AND status != 'VOID' AND closed_at IS NOT NULL ORDER BY closed_at DESC LIMIT 1", (sym, tf))
    if last:
        ends = int(last["closed_at"]) + tf_ms(PATH_TF)
        cool = settings.reentry_cooldown_bars * step
        if now < ends + cool:
            return ("cooldown", f"the last {tf} call on this coin closed {max(0, (now - ends) // 60_000)} min ago; "
                    f"waiting {settings.reentry_cooldown_bars} bars before a new call",
                    {"last_id": last["id"], "closed_at": last["closed_at"], "cooldown_bars": settings.reentry_cooldown_bars})
    # re-entries in the same direction after a give-back / stop exit within the window
    window = settings.reentry_window_bars * step
    exits = db.query(f"SELECT * FROM {table} WHERE symbol = ? AND timeframe = ? AND side = ? AND closed_at >= ? "
                     "AND exit_reason IN ('giveback', 'stop') ORDER BY closed_at", (sym, tf, side, now - window))
    if exits:
        first = exits[0]
        regime = (a.get("regime") or {}).get("regime")
        vol = (a.get("volatility") or {}).get("state")
        if regime in UNSTABLE_REGIMES or vol == "EXTREME":
            return ("reentry_regime", "no re-entry while volatility is extreme",
                    {"after_id": first["id"], "regime": regime, "volatility": vol})
        n = db.one(f"SELECT COUNT(*) AS n FROM {table} WHERE symbol = ? AND timeframe = ? AND side = ? AND created_at > ?",
                   (sym, tf, side, int(first["closed_at"])))["n"]
        if n >= settings.reentry_max:
            return ("reentry_cap", f"already {n} re-entries in this direction since a {first['exit_reason']} exit "
                    f"(limit {settings.reentry_max} within {settings.reentry_window_bars} bars)",
                    {"after_id": first["id"], "reentries": n, "max": settings.reentry_max})
    return ("ok", None, {})


def _plan(a: dict[str, Any], db: Database | None = None) -> dict[str, Any]:
    """Entry, stop, targets and fill state of a tradable decision. Entry = the plan's ideal entry (what the card shows).
    v2.6 (ENTRY_RULES, per timeframe where proven): 'confirm' waits for a candle closing beyond price + k ATR in the trade
    direction, 'pullback' places a limit at price - k ATR; both are PENDING until filled within the fill window, and the
    recorded entry / targets are set at the fill (targets in R from the actual entry)."""
    setup = a.get("setup") or {}
    tps = [t["price"] for t in setup.get("targets", [])] + [None, None, None]
    entry = setup.get("ideal_entry") or a.get("price")
    pending = a["decision"] == "BUY ON PULLBACK"
    rule = None
    if db is not None and a.get("timeframe"):
        from .series_nightly import entry_rule
        mode, k = entry_rule(db, a["timeframe"])
        rr = [float(t.get("rr") or m) for t, m in zip(setup.get("targets", []), (1.0, 1.75, 2.5))] or [1.0, 1.75, 2.5]
        if mode == "market":                      # proven for this timeframe: enter at the decision price, no limit
            side = int(setup.get("side_int") or _side_of(a["decision"]))
            px = float(a.get("price") or entry)
            if setup.get("stop") is not None and side * (px - float(setup["stop"])) > 0:
                d = abs(px - float(setup["stop"]))
                entry, pending = px, False
                tps = [px + side * m * d for m in rr] + [None, None, None]
                rule = {"mode": "market", "k": 0.0, "rr": rr}
        elif mode in ("confirm", "pullback") and setup.get("atr"):
            side = int(setup.get("side_int") or _side_of(a["decision"]))
            price = float(a.get("last_close") or a.get("price"))
            rule = {"mode": mode, "k": k, "price": price, "atr": float(setup["atr"]), "rr": rr,
                    "level": price + side * k * float(setup["atr"]) * (1 if mode == "confirm" else -1)}
            pending = True
            if mode == "pullback":
                entry = rule["level"]
    return {"side": int(setup.get("side_int") or _side_of(a["decision"])), "entry": entry, "stop": setup.get("stop"),
            "tps": tps[:3], "rr": setup.get("risk_reward"), "atr": setup.get("atr"),
            "fill_status": "PENDING" if pending else "FILLED", "entry_rule": rule}


def record_call(db: Database, a: dict[str, Any], now: int | None = None) -> dict[str, Any]:
    """Store the analysis in the signal history. Returns {'status': 'logged' | 'already_open' | 'not_logged' | None,
    'reason', 'id'} (None: not a tradable decision; an INFO row may still be written)."""
    sig = a.get("signal") or {}
    res: dict[str, Any] = {"status": None, "reason": None, "id": None, "written": False}
    if not sig.get("signal") or a.get("bar_ts") is None:
        return res
    from ..config import MODEL_TIMEFRAMES
    if a.get("timeframe") not in MODEL_TIMEFRAMES:      # daily charts are context only, never a signal
        return res
    now = now or now_ms()
    sym, tf = a["symbol"], a["timeframe"]
    setup = a.get("setup") or {}
    tradable = a["decision"] in TRADE_DECISIONS and bool(setup.get("valid"))
    if tradable:
        gate, why, inputs = entry_gate(db, a, now=now)
        if gate != "ok":
            st = "already_open" if gate == "already_open" else "not_logged"
            log_decision(db, f"skip_{gate}", sym, tf, inputs.get("open_id") or inputs.get("last_id") or inputs.get("after_id"),
                         {**inputs, "decision": a["decision"], "reason": why}, ts=now, dedupe=True)
            return {"status": st, "reason": why, "id": inputs.get("open_id"), "written": False}
    else:
        prev = db.one("SELECT signal, decision FROM signals WHERE symbol = ? AND timeframe = ? ORDER BY bar_ts DESC LIMIT 1",
                      (sym, tf))
        if prev and prev["signal"] == sig["signal"] and prev["decision"] == a["decision"]:
            return res
    fc = a.get("forecast") or {}
    pl = _plan(a, db) if tradable else None
    app_v, eng_v = versions()
    payload = {"reasons": sig.get("reasons"), "warnings": sig.get("warnings"), "flags": a.get("flags"),
               "decision_reason": a.get("decision_reason"), "grade": a.get("grade"),
               "runner": setup.get("runner") if tradable else None,
               "entry_rule": pl.get("entry_rule") if pl else None}
    if tradable:
        from ..engine.futures import signal_leverage
        payload.update({"manage": manage_params(db), "live_price": a.get("price"),
                        "leverage": signal_leverage(pl["entry"], pl["stop"]),
                        "decision_basis": a.get("decision_basis"),
                        "ai_inputs": {"confidence": a.get("confidence"), "regime": (a.get("regime") or {}).get("regime"),
                                      "trend": _comp(sig, "trend"), "momentum": _comp(sig, "momentum"),
                                      "risk_reward": setup.get("risk_reward"), "risk_pct": setup.get("risk_pct"),
                                      "targets_r": [t.get("rr") for t in setup.get("targets", [])],
                                      "volatility": (a.get("volatility") or {}).get("state"),
                                      "warnings": (sig.get("warnings") or [])[:4]}})
    sid = new_id()
    vals = (sid, now, sym, tf, a["bar_ts"], sig["signal"], a["decision"], sig.get("score"), a.get("confidence"),
            (a.get("regime") or {}).get("regime"), a["price"], pl["side"] if pl else 0, pl["entry"] if pl else None,
            pl["stop"] if pl else None, *(pl["tps"] if pl else [None, None, None]), pl["rr"] if pl else None,
            "OPEN" if tradable else "INFO", fc.get("model_version"), dumps(payload),
            pl["fill_status"] if pl else None, now if pl and pl["fill_status"] == "FILLED" else None,
            0.0 if pl else None, 0.0 if pl else None, 0 if pl else None, pl["atr"] if pl else None, app_v, eng_v)
    cols = ("id, created_at, symbol, timeframe, bar_ts, signal, decision, score, confidence, regime, price, side, entry, "
            "stop, tp1, tp2, tp3, rr, status, model_version_id, payload, fill_status, filled_at, peak_r, peak_pct, managed, "
            "atr, app_version, engine_version")
    n = db.execute(f"INSERT INTO signals ({cols}) VALUES ({', '.join('?' * len(vals))}) "
                   "ON CONFLICT (symbol, timeframe, bar_ts) DO NOTHING", vals)
    if n == 0 and tradable:
        # one row per candle: an INFO row on this candle becomes the call (a mid-candle decision change is not lost);
        # a call already recorded on this candle is reported, not silently dropped
        row = db.one("SELECT id, status FROM signals WHERE symbol = ? AND timeframe = ? AND bar_ts = ?", (sym, tf, a["bar_ts"]))
        if row and row["status"] == "INFO":
            sets = ", ".join(f"{c.strip()} = ?" for c in cols.split(",")[1:])
            n = db.execute(f"UPDATE signals SET {sets} WHERE id = ? AND status = 'INFO'", (*vals[1:], row["id"]))
            sid = row["id"]
        else:
            why = "a call was already recorded on this candle"
            log_decision(db, "skip_same_candle", sym, tf, row["id"] if row else None,
                         {"decision": a["decision"], "reason": why}, ts=now, dedupe=True)
            return {"status": "not_logged", "reason": why, "id": row["id"] if row else None, "written": False}
    if n > 0 and tradable:
        log_decision(db, "logged", sym, tf, sid, {"decision": a["decision"], "grade": a.get("grade"), "entry": pl["entry"],
                                                  "stop": pl["stop"], "tps": pl["tps"], "fill_status": pl["fill_status"],
                                                  "live_price": a.get("price"), "manage": payload.get("manage")}, ts=now)
        return {"status": "logged", "reason": None, "id": sid, "written": True}
    if not tradable:
        return {**res, "written": n > 0, "id": sid if n > 0 else None}
    return {"status": "not_logged", "reason": "not stored", "id": None, "written": False}


def _comp(sig: dict[str, Any], key: str) -> float | None:
    for c in sig.get("components") or []:
        if c.get("key") == key:
            return c.get("score")
    return None


def log_signal(db: Database, a: dict[str, Any], now: int | None = None) -> bool:
    """Store a signal; True when a row was written (see record_call for the reason when not)."""
    res = record_call(db, a, now)
    a["record_status"] = res["status"]
    if res["reason"]:
        a["record_reason"] = res["reason"]
    return bool(res.get("written"))


def log_shadow(db: Database, a: dict[str, Any], decision: str, setup: dict[str, Any]) -> bool:
    """A trade the safety switch held back: tracked to the end like a signal, so the switch knows when the
    coin/timeframe has recovered. Never shown as a signal. Same entry / fill / one-open rules as the record."""
    if open_call(db, a["symbol"], a["timeframe"], "shadow_signals"):
        return False
    pl = _plan({**a, "decision": decision, "setup": setup})
    fc = a.get("forecast") or {}
    app_v, eng_v = versions()
    now = now_ms()
    n = db.execute(
        "INSERT INTO shadow_signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, score, confidence, "
        "regime, price, side, entry, stop, tp1, tp2, tp3, rr, status, model_version_id, payload, fill_status, filled_at, "
        "peak_r, peak_pct, managed, atr, app_version, engine_version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, ?, 0, 0, 0, ?, ?, ?) "
        "ON CONFLICT (symbol, timeframe, bar_ts) DO NOTHING",
        (new_id(), now, a["symbol"], a["timeframe"], a["bar_ts"], (a.get("signal") or {}).get("signal", ""), decision,
         (a.get("signal") or {}).get("score"), a.get("confidence"), (a.get("regime") or {}).get("regime"), a["price"],
         pl["side"], pl["entry"], pl["stop"], *pl["tps"], pl["rr"], fc.get("model_version"),
         dumps({"shadow": True, "runner": setup.get("runner"), "manage": manage_params(db)}),
         pl["fill_status"], now if pl["fill_status"] == "FILLED" else None, pl["atr"], app_v, eng_v))
    return n > 0


def _bar_ms(tf: str) -> int:
    try:
        return tf_ms(tf)
    except Exception:
        return tf_ms(PATH_TF)


def evaluate_signal(s: dict[str, Any], p15: Any, own: Any, now: int, horizon_bars: int = 30,
                    params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Pure: the tracked state of one OPEN signal row given its 15m path (`p15`) and own-timeframe candles (`own`).
    Returns the columns to store plus 'events' (decisions to log)."""
    from ..config import settings
    from ..engine import manage as M

    step = _bar_ms(s["timeframe"])
    created = int(s["created_at"])
    end = created + step * horizon_bars
    path_ms = tf_ms(PATH_TF)
    pay = loads(s.get("payload"), {}) or {}
    # each call keeps the management rules it was published with (rows from before v2.5: standard rules)
    p = pay.get("manage") or {"managed": False}
    # A1: only candles that open at/after publication (the forming candle at publication is never used)
    after = p15[(p15["ts"] >= created) & (p15["ts"] < end)] if p15 is not None and len(p15) else None
    pms = path_ms
    covered = after is not None and not after.empty and int(after["ts"].iloc[-1]) + path_ms >= end
    if after is None or after.empty:                    # no 15m data: the signal's own candles (also after publication)
        after = own[own["ts"] >= created].iloc[:horizon_bars] if own is not None and len(own) else None
        pms = step
        covered = after is not None and len(after) >= horizon_bars
    wall_over = now >= end + 2 * path_ms                # A7: the horizon is over on the wall clock (+30 min for late data)
    out: dict[str, Any] = {"events": []}
    fill_status = s.get("fill_status") or "FILLED"
    side, entry = int(s["side"]), float(s["entry"])
    if after is None or after.empty:
        if wall_over:
            out.update(status="VOID", closed_at=end, return_pct=None, exit_reason=None, managed=0,
                       fill_status=fill_status if fill_status == "FILLED" else "NOT_FILLED")
            out["events"].append({"rule": "void", "inputs": {"reason": "no market data after publication"}})
        return out
    path = after
    first_is_fill = False
    rule = pay.get("entry_rule") or None
    if fill_status == "PENDING" and rule and rule.get("mode") == "confirm":
        # v2.6 confirmation entry: the first candle in the window closing beyond the level (cancelled if the stop
        # trades first); the call is entered at that close and followed from the next candle
        win_end = created + settings.fill_window_bars * step
        w = after[after["ts"] < win_end]
        cl, hi_, lo_ = w["close"].to_numpy(float), w["high"].to_numpy(float), w["low"].to_numpy(float)
        lvl, stp = float(rule["level"]), float(s["stop"])
        conf = (cl > lvl) if side > 0 else (cl < lvl)
        bad = (lo_ <= stp) if side > 0 else (hi_ >= stp)
        ci = int(conf.argmax()) if conf.any() else None
        bi = int(bad.argmax()) if bad.any() else None
        if ci is None or (bi is not None and bi <= ci):
            win_covered = len(after) and int(after["ts"].iloc[-1]) + pms >= win_end
            if bi is not None or win_covered or (wall_over and len(after)):
                out.update(status="NOT_FILLED", fill_status="NOT_FILLED", closed_at=win_end, return_pct=None,
                           exit_reason=None, managed=0, peak_r=None, peak_pct=None)
                out["events"].append({"rule": "not_confirmed", "inputs": {"level": lvl, "window_bars": settings.fill_window_bars}})
            return out
        new_entry = float(cl[ci])
        d = new_entry - stp
        tps_new = [new_entry + m * d for m in (rule.get("rr") or (1.0, 1.75, 2.5))]
        out.update(fill_status="FILLED", filled_at=int(w["ts"].iloc[ci]) + pms, entry=new_entry,
                   tp1=tps_new[0], tp2=tps_new[1], tp3=tps_new[2])
        out["events"].append({"rule": "confirmed", "inputs": {"level": lvl, "entry": new_entry, "candle_ts": int(w["ts"].iloc[ci])}})
        s = {**s, "entry": new_entry, "tp1": tps_new[0], "tp2": tps_new[1], "tp3": tps_new[2],
             "fill_status": "FILLED", "filled_at": out["filled_at"], "decision": "CONFIRMED"}
        entry = new_entry
        path = after[after["ts"] >= out["filled_at"]]
        if path.empty:
            return out
    elif fill_status == "PENDING":
        win_end = created + settings.fill_window_bars * step
        idx = M.find_fill(side, entry, after, until_ts=win_end)
        if idx is None:
            win_covered = int(after["ts"].iloc[-1]) + pms >= win_end
            if win_covered or (wall_over and len(after)):
                out.update(status="NOT_FILLED", fill_status="NOT_FILLED", closed_at=win_end, return_pct=None,
                           exit_reason=None, managed=0, peak_r=None, peak_pct=None)
                out["events"].append({"rule": "not_filled", "inputs": {"entry": entry, "window_bars": settings.fill_window_bars}})
            return out
        path = after.iloc[idx:]
        first_is_fill = True
        out["fill_status"], out["filled_at"] = "FILLED", int(path["ts"].iloc[0])
        out["events"].append({"rule": "fill", "inputs": {"entry": entry, "candle_ts": out["filled_at"]}})
    elif s.get("fill_status") is None:                  # rows from before v2.5: market entries
        out["fill_status"] = "FILLED"
    if rule and rule.get("mode") == "confirm" and s.get("fill_status") == "FILLED" and s.get("filled_at"):
        path = after[after["ts"] >= int(s["filled_at"])]   # entered at a close: followed from the next candle
    elif s.get("fill_status") == "FILLED" and s.get("filled_at") and (s.get("decision") == "BUY ON PULLBACK" or rule):
        fts = int(s["filled_at"])                       # a pullback filled earlier: follow from its fill candle
        path = after[after["ts"] >= fts]
        first_is_fill = not path.empty and int(path["ts"].iloc[0]) == fts
    run = pay.get("runner") or {}
    res = M.follow(side, entry, float(s["stop"]), [s["tp1"], s["tp2"], s["tp3"]], path,
                   runner_target=run.get("target") if run.get("on") else None, atr=s.get("atr"), params=p,
                   complete=covered or wall_over, first_is_fill=first_is_fill,
                   start_ts=int(path["ts"].iloc[0]) if len(path) else None, bar_ms=step, path_ms=pms)
    out.update(status=res["status"], tp1_hit=int(res["hits"][0]), tp2_hit=int(res["hits"][1]), tp3_hit=int(res["hits"][2]),
               stop_hit=int(res["stop_hit"]), closed_at=res["closed_ts"], return_pct=res["return_pct"],
               peak_r=res["peak_r"], peak_pct=res["peak_pct"], exit_reason=res["exit_reason"], managed=res["managed"])
    if res["status"] != "OPEN":
        out["events"].append({"rule": f"exit_{res['exit_reason'] or res['status'].lower()}",
                              "inputs": {"status": res["status"], "exit_price": res["exit_price"],
                                         "return_pct": res["return_pct"], "return_r": res["return_r"],
                                         "peak_r": res["peak_r"], "managed": res["managed"],
                                         "wall_clock_expiry": bool(wall_over and not covered)}})
    return out


TRACKED = ("status", "tp1_hit", "tp2_hit", "tp3_hit", "stop_hit", "closed_at", "return_pct", "fill_status", "filled_at",
           "peak_r", "peak_pct", "exit_reason", "managed",
           "entry", "tp1", "tp2", "tp3")       # v2.6: set once, at a confirmation fill (the actual entry)


def update_signal_outcomes(rt: Any, horizon_bars: int = 30, table: str = "signals", now: int | None = None) -> int:
    """Follow OPEN signals (v2.5: engine/manage.py) on 15-minute candles that opened after publication. Standard
    rules: 50% / 25% / 25% at the targets, stop first within a candle, break-even after TP1, TP1 after TP2, expiry at
    the last close; managed exits only when MANAGED_EXITS is on. Pullback entries wait for their fill."""
    if table not in ("signals", "shadow_signals"):
        raise ValueError(table)
    db = rt.db
    now = now or now_ms()
    params = manage_params(db)
    changed = 0
    paths: dict[str, Any] = {}
    for s in db.query(f"SELECT * FROM {table} WHERE status = 'OPEN' AND side != 0"):
        if s["symbol"] not in paths:
            try:
                paths[s["symbol"]] = rt.candles(s["symbol"], PATH_TF)
            except Exception:
                paths[s["symbol"]] = None
        try:
            own = rt.candles(s["symbol"], s["timeframe"])
        except Exception:
            own = None
        res = evaluate_signal(s, paths[s["symbol"]], own, now, horizon_bars, params)
        events = res.pop("events")
        upd = {k: v for k, v in res.items() if k in TRACKED}
        if upd.get("status") == "OPEN":
            upd["closed_at"] = None
        diff = {k: v for k, v in upd.items() if not _same(s.get(k), v)}
        if not diff:
            continue
        sets = ", ".join(f"{k} = ?" for k in diff)
        changed += db.execute(f"UPDATE {table} SET {sets} WHERE id = ?", (*diff.values(), s["id"]))
        if table == "signals":
            for ev in events:
                log_decision(db, ev["rule"], s["symbol"], s["timeframe"], s["id"], ev["inputs"], ts=now)
    return changed


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and a is not None and b is not None:
        return abs(float(a) - float(b)) < 1e-12
    return a == b


def signal_history(db: Database, symbol: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    sql, args = "SELECT * FROM signals", []
    if symbol:
        sql, args = sql + " WHERE symbol = ?", [symbol]
    rows = db.query(sql + " ORDER BY created_at DESC LIMIT ?", args + [limit])
    for r in rows:
        r["payload"] = loads(r["payload"], {})
        r.update(margin_fields(r, r["payload"]))
    return rows


def signal_summary(db: Database) -> dict[str, Any]:
    """Closed calls with a result; never-filled and void calls are counted separately (visible, not in the rates)."""
    marks = ",".join("?" * len(CLOSED_STATUSES))
    rows = db.query(f"SELECT status, return_pct, side, entry, stop, payload FROM signals WHERE status IN ({marks}) "
                    "AND return_pct IS NOT NULL",
                    CLOSED_STATUSES)
    other = {r["status"]: int(r["n"]) for r in db.query(
        "SELECT status, COUNT(*) AS n FROM signals WHERE status IN ('NOT_FILLED', 'VOID') GROUP BY status")}
    extra = {"not_filled": other.get("NOT_FILLED", 0), "void": other.get("VOID", 0)}
    if not rows:
        return {"closed": 0, **extra, "note": "No tracked trade signals have closed yet."}
    rets = np.array([r["return_pct"] for r in rows], float)
    rois = np.array([v if (v := margin_fields(r)["roi_pct"]) is not None else np.nan for r in rows], float)
    rois = rois[np.isfinite(rois)]
    return {"closed": len(rows), **extra, "win_rate": float((rets > 0).mean()) if len(rets) else None,
            "avg_return_pct": float(rets.mean()) if len(rets) else None,
            "avg_roi_pct": float(rois.mean()) if len(rois) else None,
            "by_status": {s: sum(r["status"] == s for r in rows) for s in CLOSED_STATUSES},
            "generated_at": int(time.time() * 1000)}


def reopen_for_break_even(db: Database, since: int = 0) -> int:
    """v2.3 one-time correction: signals that reached TP1 were closed with the stop left at its original level
    (including ones that dipped back to entry after TP1 and went on to TP3). They are re-followed under the published rule (break-even after TP1, TP1 after TP2) - wins and losses
    alike; nothing is removed. Returns how many were re-opened."""
    return db.execute("UPDATE signals SET status = 'OPEN', closed_at = NULL WHERE tp1_hit = 1 "
                      "AND status IN ('TP1', 'TP2', 'TP3') AND created_at >= ?", (since,))
