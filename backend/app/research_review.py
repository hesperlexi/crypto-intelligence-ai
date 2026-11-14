"""Live performance review (owner, 14 Nov 2026) - read-only (python -m app.research review).

Everything since the current record start (`record_since`, the v2.18 fresh restart), from the engine's own database:
  * the public record as stored, and RE-ASSESSED without any admin decision (no stop / TP1 changes, no "Close now"):
    every call is followed again on the stored 15-minute candles with the live rules only;
  * the same split by timeframe, side, coin, entry kind, "let it run", hour of day, grade, internal confidence;
  * how far losing calls went into profit first, how far winners went against first;
  * the demo bots, the Hesper challenge, the Trade Guardian scoreboard.
Aggregates only (the results branch is public): no single call's coin + side + levels."""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from .config import MODEL_TIMEFRAMES
from .db import loads

log = logging.getLogger(__name__)
CLOSED = ("STOPPED", "TP1", "TP2", "TP3", "EXPIRED")


def _risk_pct(r: dict[str, Any]) -> float | None:
    try:
        e, s = float(r["entry"]), float(r["stop"])
        return abs(e - s) / e * 100 if e else None
    except Exception:
        return None


def _stats(rows: list[dict[str, Any]], key: str = "net_r") -> dict[str, Any]:
    v = [float(x[key]) for x in rows if x.get(key) is not None]
    if not v:
        return {"n": 0}
    pct = [float(x["net_pct"]) for x in rows if x.get("net_pct") is not None]
    gains, losses = sum(x for x in v if x > 0), -sum(x for x in v if x < 0)
    cum, peak, dd = 0.0, 0.0, 0.0
    for x in v:
        cum += x
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return {"n": len(v), "win_rate": round(sum(1 for x in v if x > 0) / len(v), 3), "avg_r": round(sum(v) / len(v), 3),
            "total_r": round(sum(v), 2), "profit_factor": round(gains / losses, 2) if losses else None,
            "max_dd_r": round(dd, 2), "avg_pct": round(sum(pct) / len(pct), 3) if pct else None,
            "total_pct": round(sum(pct), 2) if pct else None}


def _group(rows, fn, key="net_r"):
    g = defaultdict(list)
    for r in rows:
        g[fn(r)].append(r)
    return {str(k): _stats(v, key) for k, v in sorted(g.items(), key=lambda kv: str(kv[0]))}


def record(rt, now: int) -> dict[str, Any]:
    from . import views
    from .services import tracking as T

    db = rt.db
    rc, rp = views.record_clause(rt)
    rows = db.query(f"SELECT * FROM signals WHERE side != 0 AND status != 'INFO' AND {rc} ORDER BY created_at", rp)
    adj_ids = {a["signal_id"] for a in db.query("SELECT DISTINCT signal_id FROM signal_adjustments")}
    params = T.manage_params(db)
    paths, out_rows, mismatch = {}, [], 0
    for r in rows:
        p = loads(r.get("payload"), {}) or {}
        rk = _risk_pct(r)
        item = {"tf": r["timeframe"], "side": "LONG" if r["side"] > 0 else "SHORT", "coin": r["symbol"].split("/")[0],
                "status": r["status"], "fill": r.get("fill_status"), "grade": p.get("grade"),
                "runner": bool((p.get("runner") or {}).get("on")), "entry_mode": (p.get("entry_rule") or {}).get("mode") or "?",
                "decision": r.get("decision"), "conf": r.get("confidence"), "risk_pct": rk,
                "hour": datetime.fromtimestamp(r["created_at"] / 1000, timezone.utc).hour,
                "peak_r": r.get("peak_r"), "admin": r["id"] in adj_ids, "exit": r.get("exit_reason"),
                "hold_h": round((r["closed_at"] - (r.get("filled_at") or r["created_at"])) / 3.6e6, 1) if r.get("closed_at") else None,
                "lev": p.get("leverage") or p.get("signal_leverage")}
        if r["status"] in CLOSED and r.get("return_pct") is not None:
            n = T.net_pct(r)
            item.update(net_pct=n, net_r=(n / rk) if rk else None)
        # re-assess without any admin decision
        try:
            if r["symbol"] not in paths:
                paths[r["symbol"]] = rt.candles(r["symbol"], T.PATH_TF)
            own = rt.candles(r["symbol"], r["timeframe"])
            s0 = dict(r)
            if r["id"] in adj_ids:
                s0["status"] = "OPEN"
            res = T.evaluate_signal(s0, paths[r["symbol"]], own, now, 30, params, None)
            expo = res.pop("exposure", None)
            res.pop("events", None)
            if res.get("status") in CLOSED and res.get("return_pct") is not None:
                nf = T.net_fields(db, r["symbol"], int(r["side"]), float(res["return_pct"]), expo)
                rk2 = _risk_pct({**r, "entry": res.get("entry") or r["entry"]})
                item.update(na_status=res["status"], na_net_pct=nf["return_net_pct"],
                            na_net_r=nf["return_net_pct"] / rk2 if rk2 else None)
            else:
                item.update(na_status=res.get("status"))
            if not item["admin"] and item.get("net_r") is not None and item.get("na_net_r") is not None \
                    and abs(item["net_r"] - item["na_net_r"]) > 0.02:
                mismatch += 1
        except Exception as exc:
            item["na_error"] = type(exc).__name__
        out_rows.append(item)
    closed = [x for x in out_rows if x.get("net_r") is not None]
    na_closed = [{**x, "net_r": x["na_net_r"], "net_pct": x["na_net_pct"]} for x in out_rows if x.get("na_net_r") is not None]
    adm = [x for x in out_rows if x["admin"]]
    lose = [x for x in closed if x["net_r"] < 0]
    win = [x for x in closed if x["net_r"] >= 0]
    conf_b = lambda x: "?" if x.get("conf") is None else f"{int(float(x['conf']) * 20) * 5}%"  # noqa: E731
    sess = lambda x: "Asia 00-08 UTC" if x["hour"] < 8 else "Europe 08-13" if x["hour"] < 13 else "US 13-21" if x["hour"] < 21 else "late 21-24"  # noqa: E731
    return {
        "since": rp[0] if rp else None, "calls": len(out_rows),
        "status_counts": {s: sum(1 for x in out_rows if x["status"] == s) for s in sorted({x["status"] for x in out_rows})},
        "not_filled": sum(1 for x in out_rows if x["status"] == "NOT_FILLED"),
        "open_now": sum(1 for x in out_rows if x["status"] == "OPEN"),
        "as_stored": {"overall": _stats(closed), "by_tf": _group(closed, lambda x: x["tf"]),
                      "by_side": _group(closed, lambda x: x["side"]), "by_coin": _group(closed, lambda x: x["coin"]),
                      "by_runner": _group(closed, lambda x: "let it run" if x["runner"] else "standard"),
                      "by_entry": _group(closed, lambda x: x["entry_mode"]), "by_grade": _group(closed, lambda x: x["grade"]),
                      "by_session": _group(closed, sess), "by_conf": _group(closed, conf_b),
                      "by_tf_side": _group(closed, lambda x: f"{x['tf']} {x['side']}"),
                      "by_exit": {e: sum(1 for x in closed if x["exit"] == e) for e in sorted({str(x['exit']) for x in closed})}},
        "no_admin": {"overall": _stats(na_closed), "by_tf": _group(na_closed, lambda x: x["tf"]),
                     "by_side": _group(na_closed, lambda x: x["side"]), "by_coin": _group(na_closed, lambda x: x["coin"]),
                     "still_open": sum(1 for x in out_rows if x.get("na_status") == "OPEN")},
        "admin_touched": {"calls": len(adm), "stored": _stats([x for x in adm if x.get("net_r") is not None]),
                          "without_admin": _stats([{**x, "net_r": x["na_net_r"]} for x in adm if x.get("na_net_r") is not None])},
        "reassess_mismatch_untouched": mismatch,
        "losers": {"n": len(lose), "reached_profit_first": {f"+{t}R": sum(1 for x in lose if (x.get("peak_r") or 0) >= t) for t in (0.3, 0.5, 0.7, 0.9)}},
        "winners": {"n": len(win), "avg_peak_r": round(sum(float(x.get("peak_r") or 0) for x in win) / len(win), 2) if win else None},
        "risk_pct": {"median": sorted(x["risk_pct"] for x in out_rows if x["risk_pct"])[len([x for x in out_rows if x["risk_pct"]]) // 2]
                     if any(x["risk_pct"] for x in out_rows) else None},
        "hold_h_median": (sorted(x["hold_h"] for x in closed if x.get("hold_h") is not None) or [None])[len(closed) // 2] if closed else None,
        "calls_per_day": round(len(out_rows) / max(1e-9, (now - (rp[0] if rp else now)) / 86_400_000), 2) if rp else None,
    }


def bots(rt) -> dict[str, Any]:
    db = rt.db
    out = {}
    for b in db.query("SELECT id, config, state FROM bots"):
        cfg, st = loads(b["config"], {}) or {}, loads(b["state"], {}) or {}
        tr = db.query("SELECT pnl, fees, return_pct, r_multiple, exit_reason FROM bot_trades WHERE bot_id = ?", (b["id"],))
        eq = db.one("SELECT equity FROM bot_equity WHERE bot_id = ? ORDER BY ts DESC LIMIT 1", (b["id"],))
        start = float(cfg.get("start_balance") or cfg.get("balance") or st.get("start_balance") or 10_000)
        out[b["id"]] = {"timeframe": cfg.get("timeframe"), "market": cfg.get("market"), "trades": len(tr),
                        "win_rate": round(sum(1 for t in tr if t["pnl"] > 0) / len(tr), 3) if tr else None,
                        "pnl": round(sum(t["pnl"] for t in tr), 2), "fees": round(sum(t["fees"] for t in tr), 2),
                        "avg_r": round(sum(t["r_multiple"] or 0 for t in tr) / len(tr), 3) if tr else None,
                        "equity": round(float(eq["equity"]), 2) if eq else None, "start": start,
                        "open_positions": len(st.get("positions") or []),
                        "exits": {e: sum(1 for t in tr if t["exit_reason"] == e) for e in sorted({t["exit_reason"] for t in tr})}}
    return out


def hesper(rt) -> dict[str, Any]:
    db = rt.db
    try:
        runs = db.query("SELECT * FROM hesper_runs ORDER BY started_at")
    except Exception as exc:
        return {"error": type(exc).__name__}
    try:
        trades = db.query("SELECT * FROM hesper_trades")
    except Exception:
        trades = []
    res = defaultdict(int)
    for r in runs:
        res[str(r.get("result") or r.get("status"))] += 1
    peak = max((float(r.get("peak_balance") or r.get("best") or 0) for r in runs), default=None)
    return {"runs": len(runs), "results": dict(res), "trades": len(trades), "best_balance": peak,
            "trade_wins": sum(1 for t in trades if float(t.get("pnl") or 0) > 0)}


def guardian(rt) -> dict[str, Any]:
    from .services import guardian as G
    db = rt.db
    try:
        rows = db.query("SELECT * FROM guardian_recs")
    except Exception as exc:
        return {"error": type(exc).__name__}
    return {"recs": len(rows), "by_status": {s: sum(1 for r in rows if r["status"] == s) for s in sorted({r["status"] for r in rows})},
            "by_level": {s: sum(1 for r in rows if r["level"] == s) for s in sorted({r["level"] for r in rows})},
            "scoreboard": G.scoreboard(rows)}


def models(db) -> dict[str, Any]:
    rows = db.query("SELECT symbol, timeframe, summary FROM model_versions WHERE active = 1")
    out = defaultdict(lambda: {"active": 0, "edge": 0, "filter_on": 0, "runner_on": 0})
    for r in rows:
        s = loads(r.get("summary"), {}) or {}
        o = out[r["timeframe"]]
        o["active"] += 1
        o["edge"] += bool(s.get("edge_confirmed"))
        o["filter_on"] += bool((s.get("trade_filter") or {}).get("enabled"))
        o["runner_on"] += bool((s.get("runner") or {}).get("enabled"))
    return dict(out)


def run(db_url: str, budget_s: float = 0, symbols=None, tfs=None) -> dict[str, Any]:
    from .db import Database
    from .services.runtime import Runtime

    class _Prov:
        name = "binance"

    db = Database(db_url)
    rt = Runtime(db, _Prov())
    ex = db.one("SELECT exchange, COUNT(*) AS n FROM market_data GROUP BY exchange ORDER BY n DESC LIMIT 1")
    if ex:
        _Prov.name = ex["exchange"]
    now = int(time.time() * 1000)
    out: dict[str, Any] = {"method": __doc__.strip(), "generated_at": now}
    for name, fn in (("record", lambda: record(rt, now)), ("bots", lambda: bots(rt)), ("hesper", lambda: hesper(rt)),
                     ("guardian", lambda: guardian(rt)), ("models", lambda: models(db))):
        try:
            out[name] = fn()
        except Exception as exc:
            log.exception(name)
            out[name] = {"error": f"{type(exc).__name__}: {exc}"[:300]}
    out["settings"] = {k: db.get_setting(k, None) for k in ("record_since", "record_since_tf", "record_restart")}
    return out
