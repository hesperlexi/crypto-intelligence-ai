"""v2.25 Performance Lab (admin, owner-approved 14 Nov 2026). Read-only study of the live record since its start
(`views.record_clause`), published as ONE admin-only document `views/perf_lab` every `EVERY_S` (2 h), skipped in lean mode.

  * the record as stored (net, after fees, in R of each call's risk) and RE-ASSESSED without any admin decision
    (calls with a stop / TP1 change or "Close now" are followed again on the stored candles with the live rules only);
  * splits by timeframe, side, grade, coin, session (UTC), weekday, entry kind, "let it run";
  * equity curve in R with drawdown, R histogram, streaks, how far losers went into profit first, hold times;
  * the proof checks (filters' blocked calls, AI calibration) from `proof_checks.checks`.
No engine reads, at most 12 writes a day. Nothing here changes a call."""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from ..db import loads, now_ms

VIEW = "perf_lab"
EVERY_S = 7200
CLOSED = ("STOPPED", "TP1", "TP2", "TP3", "EXPIRED")
R_BINS = (-1.5, -1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0)
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
TF_ORDER = {"15m": 0, "1h": 1, "4h": 2, "12h": 3, "1d": 4, "3d": 5}


def _risk_pct(r: dict[str, Any]) -> float | None:
    try:
        e, s = float(r["entry"]), float(r["stop"])
        return abs(e - s) / e * 100 if e else None
    except Exception:
        return None


def stats(v: list[float]) -> dict[str, Any]:
    if not v:
        return {"n": 0}
    gains, losses = sum(x for x in v if x > 0), -sum(x for x in v if x < 0)
    cum = peak = dd = 0.0
    for x in v:
        cum += x
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    n, m = len(v), sum(v) / len(v)
    se = (sum((x - m) ** 2 for x in v) / (n - 1)) ** 0.5 / n ** 0.5 if n > 1 else None
    return {"n": n, "win_rate": round(sum(1 for x in v if x > 0) / n, 3), "avg_r": round(m, 3),
            "total_r": round(sum(v), 2), "profit_factor": round(gains / losses, 2) if losses else None,
            "max_dd_r": round(dd, 2), "best_r": round(max(v), 2), "worst_r": round(min(v), 2),
            # V3.3: 95 % interval of the average (normal approx.; shown from 10 calls) - small samples prove nothing
            "ci95_avg_r": [round(m - 1.96 * se, 3), round(m + 1.96 * se, 3)] if se is not None and n >= 10 else None,
            "max_losing_streak": streaks(v)["losses"]}


def group(rows: list[dict[str, Any]], fn, key: str = "r", order=None) -> list[dict[str, Any]]:
    g: dict[str, list[float]] = defaultdict(list)
    for x in rows:
        if x.get(key) is not None:
            g[str(fn(x))].append(float(x[key]))
    out = [{"key": k, **stats(v)} for k, v in g.items()]
    return sorted(out, key=(lambda d: order(d["key"])) if order else (lambda d: -d["n"]))


def session(h: int) -> str:
    return "Asia" if h < 8 else "Europe" if h < 13 else "US" if h < 21 else "Late"


def histogram(v: list[float]) -> list[dict[str, Any]]:
    edges = (-1e9, *R_BINS, 1e9)
    out = []
    for a, b in zip(edges[:-1], edges[1:]):
        out.append({"lo": None if a < -1e8 else a, "hi": None if b > 1e8 else b, "n": sum(1 for x in v if a <= x < b)})
    return out


def streaks(v: list[float]) -> dict[str, int]:
    best = worst = cur = 0
    for x in v:
        cur = (cur + 1 if cur >= 0 else 1) if x > 0 else (cur - 1 if cur <= 0 else -1)
        best, worst = max(best, cur), min(worst, cur)
    return {"wins": best, "losses": -worst, "current": cur}


def _portfolio(rt: Any) -> dict[str, Any] | None:
    try:
        from .portfolio_risk import summary
        return summary(rt)
    except Exception as exc:
        return {"available": False, "reason": type(exc).__name__}


def _ml_shadow(rt: Any, now: int) -> dict[str, Any] | None:
    try:
        from .ml_shadow import build as ml_build
        return ml_build(rt, now)
    except Exception as exc:
        return {"available": False, "reason": type(exc).__name__}


def build(rt: Any, now: int | None = None) -> dict[str, Any]:
    from .. import views
    from . import tracking as T

    now = now or now_ms()
    t0 = time.time()
    db = rt.db
    rc, rp = views.record_clause(rt)
    rows = db.query(f"SELECT * FROM signals WHERE side != 0 AND status != 'INFO' AND {rc} ORDER BY created_at", rp)
    try:
        adj_ids = {a["signal_id"] for a in db.query("SELECT DISTINCT signal_id FROM signal_adjustments")}
    except Exception:
        adj_ids = set()
    params = T.manage_params(db)
    paths: dict[str, Any] = {}
    items: list[dict[str, Any]] = []
    for r in rows:
        p = loads(r.get("payload"), {}) or {}
        rk = _risk_pct(r)
        dt = datetime.fromtimestamp(r["created_at"] / 1000, timezone.utc)
        x = {"id": r["id"], "t": r["created_at"], "tf": r["timeframe"], "side": "LONG" if r["side"] > 0 else "SHORT",
             "coin": r["symbol"].split("/")[0], "status": r["status"], "grade": p.get("grade") or "?",
             "runner": bool((p.get("runner") or {}).get("on")), "entry": (p.get("entry_rule") or {}).get("mode") or "?",
             "hour": dt.hour, "wd": WEEKDAYS[dt.weekday()], "admin": r["id"] in adj_ids,
             "peak_r": r.get("peak_r"), "exit": r.get("exit_reason"), "tp1": int(r.get("tp1_hit") or 0),
             "hold_h": round((r["closed_at"] - (r.get("filled_at") or r["created_at"])) / 3.6e6, 1) if r.get("closed_at") else None,
             "closed_at": r.get("closed_at"),
             "regime": ((p.get("risk_shadow") or {}).get("state")) or "unknown"}
        if r["status"] in CLOSED and r.get("return_pct") is not None and rk:
            n = T.net_pct(r)
            x["r"] = round(n / rk, 3) if n is not None else None
        x["na_r"] = x.get("r")
        if x["admin"]:            # follow it again with the live rules only
            x["na_r"] = None
            try:
                if r["symbol"] not in paths:
                    paths[r["symbol"]] = rt.candles(r["symbol"], T.PATH_TF)
                s0 = {**r, "status": "OPEN"}
                res = T.evaluate_signal(s0, paths[r["symbol"]], rt.candles(r["symbol"], r["timeframe"]), now, 30, params, None)
                expo = res.pop("exposure", None)
                res.pop("events", None)
                if res.get("status") in CLOSED and res.get("return_pct") is not None:
                    nf = T.net_fields(db, r["symbol"], int(r["side"]), float(res["return_pct"]), expo)
                    rk2 = _risk_pct({**r, "entry": res.get("entry") or r["entry"]})
                    x["na_r"] = round(nf["return_net_pct"] / rk2, 3) if rk2 else None
                x["na_status"] = res.get("status")
            except Exception as exc:
                x["na_error"] = type(exc).__name__
        items.append(x)
    closed = [x for x in items if x.get("r") is not None]
    closed_by_close = sorted(closed, key=lambda x: x.get("closed_at") or x["t"])
    rv = [x["r"] for x in closed_by_close]
    na = sorted((x for x in items if x.get("na_r") is not None), key=lambda x: x.get("closed_at") or x["t"])
    curve, cum, peak = [], 0.0, 0.0
    for x in closed_by_close:
        cum += x["r"]
        peak = max(peak, cum)
        curve.append({"t": x.get("closed_at") or x["t"], "r": round(cum, 3), "dd": round(peak - cum, 3)})
    lose = [x for x in closed if x["r"] < 0]
    heat: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for x in closed:
        heat[x["wd"]][session(x["hour"])].append(x["r"])
    tf_ord = lambda k: TF_ORDER.get(k, 9)  # noqa: E731
    try:
        from .proof_checks import checks
        proof = checks(db, now)
    except Exception:
        proof = None
    holds = sorted(x["hold_h"] for x in closed if x.get("hold_h") is not None)
    return {
        "generated_at": now, "since": rp[0] if rp else None, "calls": len(items),
        "open": sum(1 for x in items if x["status"] == "OPEN"),
        "missed": sum(1 for x in items if x["status"] in ("NOT_FILLED", "VOID")),
        "overall": stats(rv), "no_admin": stats([x["na_r"] for x in na]),
        "admin": {"touched": sum(1 for x in items if x["admin"]),
                  "stored": stats([x["r"] for x in closed if x["admin"]]),
                  "without": stats([x["na_r"] for x in items if x["admin"] and x.get("na_r") is not None])},
        "by_tf": group(closed, lambda x: x["tf"], order=tf_ord),
        "by_side": group(closed, lambda x: x["side"]),
        "by_grade": group(closed, lambda x: x["grade"]),
        "by_coin": group(closed, lambda x: x["coin"]),
        "by_session": group(closed, lambda x: session(x["hour"]), order=lambda k: ["Asia", "Europe", "US", "Late"].index(k)),
        "by_entry": group(closed, lambda x: x["entry"]),
        "by_runner": group(closed, lambda x: "let it run" if x["runner"] else "standard"),
        # V3.3 (Stage 2 phase D): market risk state at publication; side split per timeframe
        "by_regime": group(closed, lambda x: x["regime"]),
        "by_tf_side": group(closed, lambda x: f"{x['tf']} {x['side']}", order=lambda k: (TF_ORDER.get(k.split()[0], 9), k)),
        "portfolio": _portfolio(rt),
        "ml_shadow": _ml_shadow(rt, now),
        "basis": {"r": "net R: after the record's 0.15 % round trip and funding, per call's planned risk",
                  "confidence": "model scores are rankings, not verified win probabilities",
                  "costs_gap": "one flat cost for every coin; memecoins / thin coins cost more in reality"},
        "heat": [{"wd": d, "cells": [{"s": s, **stats(heat[d][s])} for s in ("Asia", "Europe", "US", "Late")]} for d in WEEKDAYS],
        "histogram": histogram(rv), "streaks": streaks(rv), "curve": curve[-400:],
        "losers": {"n": len(lose), "reached_profit": {f"{t}": sum(1 for x in lose if (x.get("peak_r") or 0) >= t)
                                                      for t in (0.3, 0.5, 0.75, 1.0)}},
        "hold_h": {"median": holds[len(holds) // 2] if holds else None, "max": holds[-1] if holds else None},
        "exits": {str(e): sum(1 for x in closed if x["exit"] == e) for e in sorted({str(x["exit"]) for x in closed})},
        # one dot per closed call for the orbit chart (admin only document)
        "dots": [{"t": x.get("closed_at") or x["t"], "tf": x["tf"], "side": x["side"][0], "r": x["r"], "coin": x["coin"],
                  "g": x["grade"], "a": int(x["admin"])} for x in closed_by_close[-300:]],
        "proof": None if not proof else {"rejected": {k: proof["rejected"].get(k) for k in
                                                      ("n", "closed", "total_r", "avg_r", "verdict", "by_flag")},
                                         "calibration": proof.get("calibration")},
        "took_s": round(time.time() - t0, 2),
    }


def view_core(v: dict[str, Any]) -> list[Any]:
    return [v["calls"], (v.get("overall") or {}).get("n"), v.get("open")]


def publish(rt: Any, sink: Any, now: int | None = None) -> dict[str, Any]:
    if getattr(sink, "lean", False):
        return {"skipped": "lean"}
    v = build(rt, now)
    sink.view(VIEW, v, volatile=("generated_at", "took_s"), min_interval_s=EVERY_S, core=view_core(v))
    return {"calls": v["calls"], "closed": (v["overall"] or {}).get("n", 0), "took_s": v["took_s"]}
