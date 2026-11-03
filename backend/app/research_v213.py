"""`python -m app.research v213`: impact of the v2.13 honest-record and stricter-grading changes (read-only).

Part 1 - live record. Every recorded call (table `signals`) published since 30 Oct 2026 00:00 Dubai is followed again on
the stored candles with the current exit rules, in three ways:
  old    the call as it was recorded (entry = the plan's ideal entry, stop on a gap at the stop, limit fills on a touch);
  fills  the same entry, v2.13 fills (stop on a gap at the candle's open, limits only when traded through);
  new    v2.13 entry too: a call filled at publication enters at the price the engine saw (targets rebuilt in R from it,
         same stop; not recorded when that price was already beyond the stop); pullback / confirm calls unchanged.
Each closed result is shown gross (price return) and net (minus the 0.15 % round trip and the funding over the hold,
tracking.net_fields). `edge` marks calls whose model would fail the v2.13 edge requirement (edge test or direction
policy edge, from the model version that made the call; 'unknown' when its file is gone).
Approximation: each call is replayed on its own; a different close time could have let a different later call in.

Part 2 - research replay (research_engine's method: the models' walk-forward out-of-sample calls replayed through the
live decision rules, first 70 % of each series as the reference, last 30 % the untouched test). On the test set, per
timeframe: current grading vs grading that needs a proven edge, each with the pre-v2.13 record entry (ideal entry,
filled at once) and the v2.13 entry (market price, pullback limit through-fill). R after the 0.15 % round trip and the
default funding (0.01 % per 8 h, longs pay) over the hold.
"""
from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np

from .config import MODEL_TIMEFRAMES, settings
from .data.base import tf_ms
from .db import loads

log = logging.getLogger("research.v213")
SINCE_30_OCT = 1793304000000          # 2026-10-30 00:00 Dubai (UTC+4)
CLOSED = ("STOPPED", "TP1", "TP2", "TP3", "EXPIRED")


# ---- part 1: the live record ------------------------------------------------------------------------------------

def _edge_of(db, version_id: str | None, cache: dict) -> dict[str, Any]:
    if not version_id:
        return {"edge_confirmed": None, "policy_edge": None, "known": False}
    if version_id in cache:
        return cache[version_id]
    out = {"edge_confirmed": None, "policy_edge": None, "known": False}
    row = db.one("SELECT id, path, edge_confirmed FROM model_versions WHERE id = ?", (version_id,))
    if row:
        out["edge_confirmed"] = bool(row["edge_confirmed"])
        try:
            import joblib

            from .ml import direction
            b = joblib.load(row["path"])
            pol = direction.direction_policy(b.get("oos") or {}, None)
            out["policy_edge"] = bool((pol or {}).get("edge"))
            out["known"] = True
        except Exception:
            pass
    cache[version_id] = out
    return out


def _market_row(r: dict[str, Any]) -> dict[str, Any] | None:
    """The call as v2.13 would record it (None: not recorded - the price was already at / beyond the stop)."""
    pay = loads(r.get("payload"), {}) or {}
    rule = pay.get("entry_rule") or {}
    pending = r["decision"] == "BUY ON PULLBACK" or rule.get("mode") in ("confirm", "pullback")
    if pending or rule.get("mode") == "market":
        return dict(r)                     # a limit / confirmation, or already entered at the market price
    side, stop, ideal = int(r["side"]), float(r["stop"]), float(r["entry"])
    px = float(pay.get("live_price") or r["price"])
    if side * (px - stop) <= 0:
        return None
    d0 = abs(ideal - stop)
    mult = [abs(float(r[k]) - ideal) / d0 if r.get(k) is not None and d0 else m for k, m in (("tp1", 1.0), ("tp2", 1.75), ("tp3", 2.5))]
    d = abs(px - stop)
    out = dict(r)
    out.update(entry=px, tp1=px + side * mult[0] * d, tp2=px + side * mult[1] * d, tp3=px + side * mult[2] * d)
    run = pay.get("runner") or {}
    if run.get("on"):
        rr = float(run.get("rr") or 4.0)
        pay = {**pay, "runner": {**run, "target": px + side * rr * d}}
        out["payload"] = __import__("json").dumps(pay)
    return out


def _follow(rt, r: dict[str, Any], now: int, legacy: bool) -> dict[str, Any]:
    from .engine import manage as M
    from .services import tracking as T
    gap, tick = M.GAP_FILLS, M.TICK_FRAC
    try:
        if legacy:
            M.GAP_FILLS, M.TICK_FRAC = False, 0.0
        s = dict(r)
        s["status"] = "OPEN"
        # replay from publication: a pending call starts pending again, a filled one keeps its fill
        rule = (loads(r.get("payload"), {}) or {}).get("entry_rule") or {}
        is_limit = (r["decision"] == "BUY ON PULLBACK" and rule.get("mode") != "market") or rule.get("mode") in ("confirm", "pullback")
        if is_limit and r.get("fill_status") in ("FILLED", "NOT_FILLED", "PENDING"):
            s["fill_status"], s["filled_at"] = "PENDING", None
        try:
            p15 = rt.candles(r["symbol"], T.PATH_TF)
        except Exception:
            p15 = None
        try:
            own = rt.candles(r["symbol"], r["timeframe"])
        except Exception:
            own = None
        adj = T.adjustments_of(rt.db, r["id"])
        res = T.evaluate_signal(s, p15, own, now, adjust=adj)
    finally:
        M.GAP_FILLS, M.TICK_FRAC = gap, tick
    out = {"status": res.get("status", "OPEN"), "gross": res.get("return_pct"), "fill_status": res.get("fill_status") or s.get("fill_status")}
    if out["status"] in CLOSED and out["gross"] is not None:
        nf = T.net_fields(rt.db, r["symbol"], int(r["side"]), float(out["gross"]), res.get("exposure"))
        out.update(net=nf["return_net_pct"], funding=nf["funding_pct"], cost=nf["cost_pct"])
    return out


def _agg(items: list[dict[str, Any]], key: str) -> dict[str, Any]:
    closed = [x[key] for x in items if x.get(key) and x[key]["status"] in CLOSED and x[key].get("gross") is not None]
    g = np.array([c["gross"] for c in closed], float)
    n = np.array([c["net"] for c in closed], float)
    return {"closed": len(closed), "open": sum(1 for x in items if x.get(key) and x[key]["status"] == "OPEN"),
            "not_filled_or_void": sum(1 for x in items if x.get(key) and x[key]["status"] in ("NOT_FILLED", "VOID")),
            "not_recorded": sum(1 for x in items if x.get(key) is None),
            "win_rate_gross": float((g > 0).mean()) if len(g) else None,
            "win_rate_net": float((n > 0).mean()) if len(n) else None,
            "avg_gross_pct": float(g.mean()) if len(g) else None, "avg_net_pct": float(n.mean()) if len(n) else None,
            "total_gross_pct": float(g.sum()) if len(g) else 0.0, "total_net_pct": float(n.sum()) if len(n) else 0.0}


def live_record(rt, since: int = SINCE_30_OCT, now: int | None = None) -> dict[str, Any]:
    from .db import now_ms
    from .views import record_clause
    now = now or now_ms()
    db = rt.db
    rc, rp = record_clause(rt)
    in_rec = {r["id"] for r in db.query(f"SELECT id FROM signals WHERE side != 0 AND {rc}", rp)}
    rows = db.query("SELECT * FROM signals WHERE side != 0 AND status != 'INFO' AND entry IS NOT NULL AND stop IS NOT NULL "
                    "AND created_at >= ? ORDER BY created_at", (since,))
    cache: dict = {}
    items = []
    for r in rows:
        stored_closed = r["status"] in CLOSED and r.get("return_pct") is not None
        from .services import tracking as T
        stored = {"status": r["status"], "gross": r.get("return_pct"), "fill_status": r.get("fill_status")}
        if stored_closed:
            stored["net"] = T.net_pct({**r, "return_net_pct": None})
        x = {"id": r["id"], "symbol": r["symbol"], "timeframe": r["timeframe"], "side": int(r["side"]),
             "decision": r["decision"], "grade": (loads(r.get("payload"), {}) or {}).get("grade"),
             "created_at": r["created_at"], "in_record": r["id"] in in_rec,
             "entry_ideal": r["entry"], "price_at_call": (loads(r.get("payload"), {}) or {}).get("live_price") or r["price"],
             "stored": stored}
        try:
            x["old"] = _follow(rt, r, now, legacy=True)
            x["fills"] = _follow(rt, r, now, legacy=False)
            m = _market_row(r)
            x["new"] = _follow(rt, m, now, legacy=False) if m is not None else None
            x["entry_new"] = m["entry"] if m is not None else None
        except Exception as exc:
            x["error"] = f"{type(exc).__name__}: {exc}"[:200]
            items.append(x)
            continue
        e = _edge_of(db, r.get("model_version_id"), cache)
        x["edge"] = e
        if e["edge_confirmed"] is False:
            x["edge_blocked"] = True
        elif not e["known"]:
            x["edge_blocked"] = None
        else:
            x["edge_blocked"] = not e["policy_edge"]
        # did the call's result change sign (old: gross as recorded / replayed; new: net)?
        o, nw = x["old"], x["new"]
        if o["status"] in CLOSED and nw and nw["status"] in CLOSED and o.get("gross") is not None and nw.get("net") is not None:
            x["flip"] = ("win->loss" if o["gross"] > 0 >= nw["net"] else "loss->win" if o["gross"] <= 0 < nw["net"] else None)
        items.append(x)
    by_tf: dict[str, Any] = {}
    for tf in [t for t in MODEL_TIMEFRAMES if any(i["timeframe"] == t for i in items)]:
        xs = [i for i in items if i["timeframe"] == tf and "error" not in i]
        kept = [i for i in xs if i.get("edge_blocked") is False]
        by_tf[tf] = {"calls": len(xs), "in_record_now": sum(i["in_record"] for i in xs),
                     "stored": _agg(xs, "stored"), "old": _agg(xs, "old"), "fills": _agg(xs, "fills"), "new": _agg(xs, "new"),
                     "result_changed": {"win->loss": sum(i.get("flip") == "win->loss" for i in xs),
                                        "loss->win": sum(i.get("flip") == "loss->win" for i in xs)},
                     "entry_moved_pct_avg": float(np.mean([i["side"] * (i["entry_new"] / i["entry_ideal"] - 1) * 100 for i in xs
                                                           if i.get("entry_new") and i["entry_new"] != i["entry_ideal"]] or [0.0])),
                     "edge_blocked": {"blocked": sum(i.get("edge_blocked") is True for i in xs),
                                      "kept": len(kept), "unknown": sum(i.get("edge_blocked") is None for i in xs),
                                      "new_if_only_kept": _agg(kept, "new")}}
    allx = [i for i in items if "error" not in i]
    total = {"calls": len(allx), "stored": _agg(allx, "stored"), "old": _agg(allx, "old"), "fills": _agg(allx, "fills"),
             "new": _agg(allx, "new"),
             "result_changed": {"win->loss": sum(i.get("flip") == "win->loss" for i in allx),
                                "loss->win": sum(i.get("flip") == "loss->win" for i in allx)},
             "edge_blocked": sum(i.get("edge_blocked") is True for i in allx),
             "new_if_only_kept": _agg([i for i in allx if i.get("edge_blocked") is False], "new")}
    return {"since": since, "now": now, "by_timeframe": by_tf, "total": total,
            "errors": [i for i in items if "error" in i][:20],
            "calls": [{k: v for k, v in i.items()} for i in items][-400:]}


# ---- part 2: research replay ----------------------------------------------------------------------------------------

def _with_funding(ctx, d, trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from .engine.futures import DEFAULT_FUNDING_RATE
    out = []
    for t in trades:
        side = int(d["side"][t["j"]])
        hours = max(0.0, (t["closed_ts"] - t["ts"]) / 3_600_000)
        fund = side * hours * DEFAULT_FUNDING_RATE / 8 * 100
        r = t["r"] - (fund / t["risk_pct"] if t.get("risk_pct") else 0.0)
        out.append({**t, "r": float(r), "r_cost_only": t["r"]})
    return out


def replay(rt, symbols: list[str], tfs: list[str], deadline: float) -> dict[str, Any]:
    from . import research_engine as RE
    from .ml import series_policy as SP
    news = RE._news_fn(rt.db)
    frames: dict = {}
    res: dict[str, dict[str, list]] = {k: {} for k in ("cur_ideal", "cur_market", "edge_ideal", "edge_market")}
    weeks: dict[str, float] = {}
    spans: dict[str, list[int]] = {}
    skipped, series = [], {}
    for s, tf in [(s, tf) for tf in RE.TF_ORDER if tf in tfs for s in symbols]:
        if time.time() > deadline:
            skipped.append(f"{s} {tf}: time budget")
            continue
        try:
            b = RE.build(rt, s, tf, frames)
        except Exception as exc:
            skipped.append(f"{s} {tf}: {type(exc).__name__}")
            continue
        if b is None:
            skipped.append(f"{s} {tf}: no model / too few out-of-sample bars")
            continue
        ctx, paths = b
        tune, test, cut = RE._split(ctx)
        if tune.sum() < 150 or test.sum() < 30:
            skipped.append(f"{s} {tf}: span too short to split")
            continue
        key = f"{s} {tf}"
        weeks[key] = RE._weeks(ctx, test)
        ts = ctx.ts[test]
        spans[key] = [int(ts[0]), int(ts[-1])]
        info = {}
        for grading, req in (("cur", False), ("edge", True)):
            d = SP.decide(ctx, tune, require_edge=req)
            info[grading] = int(d["trade"][test].sum())
            for ent, mode in (("ideal", "ideal"), ("market", "old")):
                tr = SP.run_series(ctx, paths, test, d, entry_mode=mode, news=news)
                res[f"{grading}_{ent}"][key] = _with_funding(ctx, d, tr)
        series[key] = {"edge_confirmed": bool(ctx.edge_confirmed), "test_calls": info, "test_span": spans[key]}
        log.info("%s: done", key)
    tables = {k: RE._table(v, weeks) for k, v in res.items()}
    for k, t in tables.items():
        for tf, blk in t["by_timeframe"].items():
            blk["trades_per_month"] = (blk.get("trades_per_week") or 0.0) * 30.44 / 7
            sp = [v for kk, v in spans.items() if kk.endswith(f" {tf}")]
            blk["test_period"] = [min(a for a, _ in sp), max(b for _, b in sp)] if sp else None
        t["overall"]["trades_per_month"] = (t["overall"].get("trades_per_week") or 0.0) * 30.44 / 7
    return {"tables": tables, "series": series, "skipped": skipped,
            "variants": {"cur_ideal": "current grading, pre-v2.13 record entry (ideal entry filled at once)",
                         "cur_market": "current grading, v2.13 entry (market price; pullback limit through-fill)",
                         "edge_ideal": "edge required, pre-v2.13 record entry",
                         "edge_market": "v2.13: edge required and honest entry"},
            "costs": {"round_trip_pct": settings.research_cost_pct, "funding": "0.01% per 8 h (longs pay), over the hold"}}


def run(db_url: str, budget_s: float, symbols: list[str] | None = None, tfs: list[str] | None = None) -> dict[str, Any]:
    from .config import ENGINE_VERSION
    from .db import Database
    from .services.runtime import Runtime

    class _Prov:
        name = "binance"

    db = Database(db_url)
    rt = Runtime(db, _Prov())
    ex = db.one("SELECT exchange, COUNT(*) AS n FROM market_data GROUP BY exchange ORDER BY n DESC LIMIT 1")
    if ex:
        _Prov.name = ex["exchange"]
    t0 = time.time()
    out: dict[str, Any] = {"engine_version": ENGINE_VERSION, "method": __doc__.strip()}
    try:
        out["live_record"] = live_record(rt)
    except Exception as exc:
        log.exception("live record")
        out["live_record"] = {"error": f"{type(exc).__name__}: {exc}"[:300]}
    syms = symbols or [r["symbol"] for r in db.query("SELECT DISTINCT symbol FROM model_versions WHERE active = 1 ORDER BY symbol")]
    try:
        out["replay"] = replay(rt, syms, tfs or list(MODEL_TIMEFRAMES), t0 + budget_s)
    except Exception as exc:
        log.exception("replay")
        out["replay"] = {"error": f"{type(exc).__name__}: {exc}"[:300]}
    out["seconds"] = round(time.time() - t0, 1)
    out["record_since"] = db.get_setting("record_since", None)
    out["record_since_tf"] = db.get_setting("record_since_tf", None)
    out["fill_window_bars"] = settings.fill_window_bars
    out["tf_ms"] = {tf: tf_ms(tf) for tf in MODEL_TIMEFRAMES}
    return out
