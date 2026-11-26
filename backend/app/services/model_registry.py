"""V3.4 Stage 4A/4B: model registry and model health (admin report; changes nothing).

One row per coin x model timeframe, from what the engine already stores (no model file is loaded):
  identity     version id, trained at, training data range, samples, out-of-sample predictions, models in the ensemble,
               top features (importance), whether BTC / higher-timeframe / futures inputs are used
  validation   ensemble walk-forward metrics (model_metrics): Brier, ECE (calibration error), precision / recall of the
               up / down calls, directional accuracy and its n, ROC AUC; edge confirmed
  live         live direction hit rate of the last DRIFT_N resolved forecasts (predictions + closed candles) vs the
               out-of-sample directional accuracy; drift when it is more than 2 standard errors below
  status       active | stale (older than STALE_H) | missing | held (a newer valid version was kept out by the champion)
               | invalid (the newest version failed validation: file does not load, too few OOS predictions ...)
  last import  the latest activation decision (setting `model_activation_log`) and failure reasons
Published as `views/model_registry` (admin only) every 2 h with the Performance Lab.

Directional accuracy and Brier are about the NEXT candle; they say nothing directly about trade results - those are in
`trade_quality` (record calls by the model's own probability bucket, net R after costs, by timeframe and market regime).
"""
from __future__ import annotations

import time
from typing import Any

import numpy as np

from ..db import loads

STALE_H = 48
DRIFT_N = 100
H = 3_600_000
ENS_KEYS = ("brier", "ece", "precision", "recall", "precision_up", "recall_up", "precision_down", "recall_down",
            "directional_accuracy", "directional_n", "roc_auc")


def _metrics(db: Any, version: str) -> dict[str, float]:
    return {r["metric"]: r["value"] for r in db.query(
        "SELECT metric, value FROM model_metrics WHERE model_version_id = ? AND model = 'ensemble'", (version,))}


def live_hit(rt: Any, symbol: str, tf: str, n: int = DRIFT_N) -> dict[str, Any] | None:
    from ..data.base import tf_ms
    try:
        df = rt.candles(symbol, tf)
    except Exception:
        return None
    if df is None or len(df) < 3:
        return None
    closes = dict(zip(df["ts"].astype("int64").tolist(), df["close"].astype(float).tolist()))
    step = tf_ms(tf)
    rows = rt.db.query("SELECT bar_ts, p_up, p_down FROM predictions WHERE symbol = ? AND timeframe = ? "
                       "ORDER BY bar_ts DESC LIMIT ?", (symbol, tf, n * 4))
    seen, hits = set(), []
    for r in rows:
        t = int(r["bar_ts"])
        if t in seen or t not in closes or t + step not in closes:
            continue
        seen.add(t)
        s = np.sign(float(r["p_up"]) - float(r["p_down"]))
        m = np.sign(closes[t + step] - closes[t])
        if s == 0 or m == 0:
            continue
        hits.append(float(s == m))
        if len(hits) >= n:
            break
    return {"n": len(hits), "hit": round(float(np.mean(hits)), 3) if hits else None}


def row(rt: Any, symbol: str, tf: str, now: int, activations: list[dict[str, Any]]) -> dict[str, Any]:
    from ..ml import trainer
    db = rt.db
    act = trainer.active_version(symbol, tf, db)
    newest = db.one("SELECT id, created_at, active FROM model_versions WHERE symbol = ? AND timeframe = ? "
                    "ORDER BY created_at DESC LIMIT 1", (symbol, tf))
    last = next((e for e in reversed(activations) if e.get("symbol") == symbol and e.get("tf") == tf), None)
    out: dict[str, Any] = {"symbol": symbol, "timeframe": tf}
    if act is None:
        out.update(status="missing", reasons=["no active model"] + ((last or {}).get("problems") or []))
        return out
    sm = act.get("summary") or {}
    age_h = round((now - int(act["created_at"])) / H, 1)
    m = _metrics(db, act["id"])
    imp = sm.get("importance") or {}
    top = sorted(imp.items(), key=lambda kv: -float(kv[1] or 0))[:6] if isinstance(imp, dict) else []
    out.update({
        "version": act["id"], "trained_at": int(act["created_at"]), "age_h": age_h,
        "data_range": [act.get("data_start"), act.get("data_end")], "n_samples": act.get("n_samples"),
        "n_oos": act.get("n_oos"), "edge_confirmed": bool(act.get("edge_confirmed")), "models": sm.get("models"),
        "features_top": [k for k, _ in top], "inputs": {"btc": sm.get("uses_btc"), "htf": sm.get("uses_htf")},
        "validation": {k: (round(float(m[k]), 4) if m.get(k) is not None and np.isfinite(m[k]) else None) for k in ENS_KEYS},
        "addons": sm.get("addons"), "last_activation": last,
    })
    lv = live_hit(rt, symbol, tf)
    ref = out["validation"].get("directional_accuracy")
    drift = None
    if lv and lv["n"] >= DRIFT_N and ref:
        se = float(np.sqrt(max(ref * (1 - ref), 1e-6) / lv["n"]))
        drift = {"live_hit": lv["hit"], "oos_hit": ref, "n": lv["n"], "drifting": bool(lv["hit"] < ref - 2 * se)}
    out["live"] = {"recent": lv, "drift": drift}
    reasons = []
    status = "active"
    if age_h > STALE_H:
        status = "stale"
        reasons.append(f"trained {age_h:.0f} h ago (> {STALE_H} h)")
    if newest and newest["id"] != act["id"] and not newest["active"]:
        if last and last.get("version") == newest["id"] and last.get("problems"):
            status = "invalid" if status == "active" else status
            reasons += [f"newest version {newest['id']} failed validation: " + "; ".join(last["problems"][:2])]
        else:
            status = "held" if status == "active" else status
            reasons.append(f"newer version {newest['id']} held: the live model was better on shared unseen bars")
    if drift and drift["drifting"]:
        reasons.append(f"live hit rate {drift['live_hit']:.0%} vs {drift['oos_hit']:.0%} out-of-sample")
    for f in (sm.get("failures") or [])[:3]:
        reasons.append(f"model failed in training: {f if isinstance(f, str) else f.get('model', f)}")
    out["status"], out["reasons"] = status, reasons
    return out


def trade_quality(db: Any) -> dict[str, Any]:
    """Record calls (closed) by the model's own confidence bucket, timeframe and market regime: net R after costs.
    This is what a call actually earned - not the next-candle hit rate."""
    from .. import views
    from . import tracking as T

    class _RT:
        pass
    rt = _RT()
    rt.db = db
    try:
        rc, rp = views.record_clause(rt)
    except Exception:
        rc, rp = "1=1", ()
    rows = db.query(f"SELECT * FROM signals WHERE side != 0 AND status IN ('STOPPED','TP1','TP2','TP3','EXPIRED') AND {rc}", rp)
    pts = []
    for r in rows:
        p = loads(r.get("payload"), {}) or {}
        rk = abs(float(r["entry"]) - float(r["stop"])) / float(r["entry"]) * 100 if r.get("entry") and r.get("stop") else None
        n = T.net_pct(r)
        if not rk or n is None:
            continue
        conf = p.get("confidence")
        pts.append({"r": n / rk, "tf": r["timeframe"], "conf": conf,
                    "regime": ((p.get("risk_shadow") or {}).get("regime") or {}).get("regime") or "not recorded"})

    def agg(xs):
        x = np.asarray([p["r"] for p in xs], float)
        if not len(x):
            return {"n": 0}
        h = 1.96 * x.std(ddof=1) / np.sqrt(len(x)) if len(x) > 1 else None
        return {"n": len(x), "avg_r": round(float(x.mean()), 3), "win_rate": round(float((x > 0).mean()), 3),
                "ci95": [round(float(x.mean() - h), 3), round(float(x.mean() + h), 3)] if h is not None else None}
    buckets = {}
    for lo, hi in ((0, 0.55), (0.55, 0.6), (0.6, 0.65), (0.65, 1.01)):
        buckets[f"{lo:.2f}-{min(hi, 1):.2f}"] = agg([p for p in pts if p["conf"] is not None and lo <= float(p["conf"]) < hi])
    return {"overall": agg(pts), "by_confidence": buckets,
            "by_timeframe": {tf: agg([p for p in pts if p["tf"] == tf]) for tf in sorted({p["tf"] for p in pts})},
            "by_regime": {g: agg([p for p in pts if p["regime"] == g]) for g in sorted({p["regime"] for p in pts})},
            "basis": "closed record calls, net R after costs; confidence = the model's hit-rate estimate, not a win probability"}


def build(rt: Any, now: int | None = None) -> dict[str, Any]:
    from ..config import MODEL_TIMEFRAMES
    now = int(time.time() * 1000) if now is None else int(now)
    acts = list(rt.db.get_setting("model_activation_log", []) or [])
    rows = []
    for s in rt.symbols():
        for tf in MODEL_TIMEFRAMES:
            try:
                rows.append(row(rt, s, tf, now, acts))
            except Exception as exc:
                rows.append({"symbol": s, "timeframe": tf, "status": "error", "reasons": [type(exc).__name__]})
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    drifting = sum(1 for r in rows if ((r.get("live") or {}).get("drift") or {}).get("drifting"))
    try:
        tq = trade_quality(rt.db)
    except Exception as exc:
        tq = {"error": type(exc).__name__}
    training = None
    try:                                     # V3.4 Stage 4E: the last nightly merge, by outcome
        t = rt.db.one("SELECT started_at, finished_at, status, detail FROM engine_runs WHERE kind = 'train' "
                      "ORDER BY started_at DESC LIMIT 1")
        if t:
            d = loads(t.get("detail"), {}) or {}
            training = {"started_at": t["started_at"], "finished_at": t["finished_at"], "status": t["status"],
                        "outcome": d.get("outcome"), "problems": d.get("problems"), "invalid": d.get("invalid"),
                        "held_by_champion": d.get("held_by_champion"), "stale_models": (d.get("stale_models") or {}).get("n")}
    except Exception:
        training = None
    return {"generated_at": now, "counts": counts, "drifting": drifting, "models": rows, "training": training,
            "activations": acts[-40:], "trade_quality": tq,
            "rule": "a model goes live only after its file loads, it has >= MODEL_MIN_OOS out-of-sample predictions "
                    "and (with the champion check on) it is not clearly worse than the live one"}


def publish(rt: Any, sink: Any, now: int | None = None) -> dict[str, Any]:
    if getattr(sink, "lean", False):
        return {"skipped": "lean"}
    v = build(rt, now)
    sink.view("model_registry", v, volatile=("generated_at",), min_interval_s=7200,
              core={"counts": v["counts"], "drifting": v["drifting"]})
    return {"counts": v["counts"], "drifting": v["drifting"]}
