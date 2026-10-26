"""Live prediction tracking: every forecast is stored when made and scored once its outcome is known.

Nothing here is back-filled: the live statistics only contain predictions that were actually issued by
this installation, in real time, before the outcome existed.
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np

from ..data.base import tf_ms
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

def log_signal(db: Database, a: dict[str, Any]) -> bool:
    """Store a signal when it differs from the last one logged for this symbol/timeframe."""
    sig = a.get("signal") or {}
    if not sig.get("signal") or a.get("bar_ts") is None:
        return False
    from ..config import MODEL_TIMEFRAMES
    if a.get("timeframe") not in MODEL_TIMEFRAMES:      # daily charts are context only, never a signal
        return False
    prev = db.one("SELECT signal, decision FROM signals WHERE symbol = ? AND timeframe = ? ORDER BY bar_ts DESC LIMIT 1",
                  (a["symbol"], a["timeframe"]))
    if prev and prev["signal"] == sig["signal"] and prev["decision"] == a["decision"]:
        return False
    setup = a.get("setup") or {}
    tradable = a["decision"] in ("BUY", "BUY ON PULLBACK", "SELL") and setup.get("valid")
    tps = [t["price"] for t in setup.get("targets", [])] if tradable else [None, None, None]
    fc = a.get("forecast") or {}
    n = db.execute(
        "INSERT INTO signals (id, created_at, symbol, timeframe, bar_ts, signal, decision, score, confidence, regime, "
        "price, side, entry, stop, tp1, tp2, tp3, rr, status, model_version_id, payload) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (symbol, timeframe, bar_ts) DO NOTHING",
        (new_id(), now_ms(), a["symbol"], a["timeframe"], a["bar_ts"], sig["signal"], a["decision"], sig.get("score"),
         a.get("confidence"), (a.get("regime") or {}).get("regime"), a["price"],
         setup.get("side_int", 0) if tradable else 0, a["price"] if tradable else None,
         setup.get("stop") if tradable else None, tps[0], tps[1], tps[2],
         setup.get("risk_reward") if tradable else None, "OPEN" if tradable else "INFO",
         fc.get("model_version"), dumps({"reasons": sig.get("reasons"), "warnings": sig.get("warnings"),
                                         "flags": a.get("flags"), "decision_reason": a.get("decision_reason"),
                                         "grade": a.get("grade")})))
    return n > 0


def update_signal_outcomes(rt: Any, horizon_bars: int = 30) -> int:
    """Follow OPEN signals through later candles. Stop is assumed first when stop and target share a bar.
    Return = three legs (50% / 25% / 25%), each exiting at its target if reached, otherwise at the stop or,
    on expiry, at the last close."""
    db = rt.db
    changed = 0
    for s in db.query("SELECT * FROM signals WHERE status = 'OPEN'"):
        df = rt.candles(s["symbol"], s["timeframe"])
        after = df[df["ts"] > s["bar_ts"]].iloc[:horizon_bars]
        if after.empty:
            continue
        side, entry = s["side"], s["entry"]
        tps = [s["tp1"], s["tp2"], s["tp3"]]
        hit = [False, False, False]
        stop_hit, closed_ts = False, None
        for _, c in after.iterrows():
            if (side > 0 and c["low"] <= s["stop"]) or (side < 0 and c["high"] >= s["stop"]):
                stop_hit, closed_ts = True, int(c["ts"])
                break
            for i, tp in enumerate(tps):
                if (side > 0 and c["high"] >= tp) or (side < 0 and c["low"] <= tp):
                    hit[i] = True
            if hit[2]:
                closed_ts = int(c["ts"])
                break
        expired = closed_ts is None and len(after) >= horizon_bars
        last_close = float(after["close"].iloc[-1])
        fallback = s["stop"] if stop_hit else last_close
        ret = float(sum(w * side * ((tps[i] if hit[i] else fallback) / entry - 1) for i, w in enumerate((0.5, 0.25, 0.25)))) * 100      # 50% / 25% / 25% exits
        status = "STOPPED" if stop_hit and not hit[0] else "TP3" if hit[2] else \
            ("TP2" if hit[1] else "TP1" if hit[0] else "EXPIRED") if (stop_hit or expired) else "OPEN"
        if closed_ts is None and expired:
            closed_ts = int(after["ts"].iloc[-1])
        n = db.execute(
            "UPDATE signals SET tp1_hit = ?, tp2_hit = ?, tp3_hit = ?, stop_hit = ?, status = ?, closed_at = ?, "
            "return_pct = ? WHERE id = ? AND (status != ? OR tp1_hit != ? OR tp2_hit != ? OR return_pct IS NULL "
            "OR return_pct != ?)",
            (int(hit[0]), int(hit[1]), int(hit[2]), int(stop_hit), status, closed_ts if status != "OPEN" else None,
             ret, s["id"], status, int(hit[0]), int(hit[1]), ret))
        changed += n
    return changed


def signal_history(db: Database, symbol: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    sql, args = "SELECT * FROM signals", []
    if symbol:
        sql, args = sql + " WHERE symbol = ?", [symbol]
    rows = db.query(sql + " ORDER BY created_at DESC LIMIT ?", args + [limit])
    for r in rows:
        r["payload"] = loads(r["payload"], {})
    return rows


def signal_summary(db: Database) -> dict[str, Any]:
    rows = db.query("SELECT status, return_pct FROM signals WHERE status NOT IN ('OPEN', 'INFO')")
    if not rows:
        return {"closed": 0, "note": "No tracked trade signals have closed yet."}
    rets = np.array([r["return_pct"] for r in rows if r["return_pct"] is not None], float)
    return {"closed": len(rows), "win_rate": float((rets > 0).mean()) if len(rets) else None,
            "avg_return_pct": float(rets.mean()) if len(rets) else None,
            "by_status": {s: sum(r["status"] == s for r in rows) for s in ("STOPPED", "TP1", "TP2", "TP3", "EXPIRED")},
            "generated_at": int(time.time() * 1000)}
