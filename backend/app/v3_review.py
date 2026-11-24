"""V3.0 Stage 2 read-only review: the 23 Nov 2026 incident and the champion / challenger log.

python -m app.v3_review --out x.json
Incident window: 20 Nov 20:00 UTC (21 Nov 00:00 Dubai) to 24 Nov 08:00 UTC. Per closed record call: coin, timeframe,
side, grade, times, exit, net R, worst move (trough R), the protection shadow at publication, Guardian
recommendations, admin changes; bots / challenge trades in the window (size as share of the book); calls held back by
filters; BTC hourly closes; engine round gaps; how many calls ran on each side over time. No entry / stop prices
(the same facts as the public Results page)."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from typing import Any

from .db import Database, loads
from .services import tracking

H = 3_600_000
T0 = 1795204800000           # 21 Nov 2026 00:00 Dubai = 20 Nov 20:00 UTC
T1 = 1795507200000           # 24 Nov 2026 08:00 UTC


def _r(row: dict) -> float | None:
    net = tracking.net_pct(row)
    e, s = row.get("entry"), row.get("stop")
    if net is None or not e or not s:
        return None
    risk = abs(float(e) - float(s)) / float(e) * 100
    return round(float(net) / risk, 3) if risk > 0 else None


def incident(db: Database) -> dict[str, Any]:
    closed = tuple(tracking.CLOSED_STATUSES)
    rows = db.query(f"SELECT * FROM signals WHERE side != 0 AND ((closed_at >= ? AND closed_at < ?) OR "
                    f"(created_at < ? AND (closed_at IS NULL OR closed_at >= ?))) ORDER BY created_at",
                    (T0, T1, T1, T0))
    recs = defaultdict(list)
    for g in db.query("SELECT signal_id, level, rules_level, severity, created_at, status, status_reason, payload FROM guardian_recs "
                      "WHERE created_at >= ? AND created_at < ?", (T0 - 48 * H, T1)):
        p = loads(g.get("payload"), {}) or {}
        recs[g["signal_id"]].append({"level": g["level"], "severity": g["severity"], "at": g["created_at"], "status": g["status"],
                                     "reasons": [x.get("key") if isinstance(x, dict) else x for x in (p.get("reasons") or [])][:5]})
    adj = Counter(r["signal_id"] for r in db.query("SELECT signal_id FROM signal_adjustments WHERE at >= ?", (T0 - 72 * H,))) \
        if _has(db, "signal_adjustments") else Counter()
    calls = []
    for r in rows:
        p = loads(r.get("payload"), {}) or {}
        rs = p.get("risk_shadow") or {}
        calls.append({
            "id": r["id"], "coin": r["symbol"].split("/")[0], "tf": r["timeframe"], "side": "LONG" if r["side"] > 0 else "SHORT",
            "grade": p.get("grade"), "created": r["created_at"], "filled": r.get("filled_at"), "closed": r.get("closed_at"),
            "status": r["status"], "fill": r.get("fill_status"), "net_r": _r(r) if r.get("closed_at") else None,
            "net_pct": tracking.net_pct(r) if r.get("closed_at") else None, "trough_r": r.get("trough_r"), "peak_r": r.get("peak_r"),
            "tp1": r.get("tp1_hit"), "tp2": r.get("tp2_hit"), "stop_hit": r.get("stop_hit"),
            "exit": p.get("exit_reason") or r["status"], "leverage": p.get("signal_leverage") or p.get("leverage"),
            "shadow": {k: rs.get(k) for k in ("volatile", "loss_stop", "would_block", "day_r", "week_r")} | {"turn": bool(rs.get("turn"))},
            "filter_bypassed": p.get("filter_bypassed"), "runner": bool((p.get("runner") or {}).get("on")) if isinstance(p.get("runner"), dict) else bool(p.get("runner")),
            "guardian": recs.get(r["id"], []), "admin_changes": adj.get(r["id"], 0),
            "excluded": not _in_record(db, r),
        })
    # one-sided exposure over time: filled calls running at each hour
    hours = []
    for t in range(T0, T1, 4 * H):
        run = [c for c in calls if (c["filled"] or c["created"]) <= t and (c["closed"] is None or c["closed"] > t) and c["fill"] != "NOT_FILLED"]
        hours.append({"t": t, "long": sum(c["side"] == "LONG" for c in run), "short": sum(c["side"] == "SHORT" for c in run)})
    # held back calls
    rej = Counter()
    rej_side = Counter()
    if _has(db, "rejected_signals"):
        for x in db.query("SELECT reject_flag, side, status, payload FROM rejected_signals WHERE created_at >= ? AND created_at < ?", (T0, T1)):
            rej[x["reject_flag"]] += 1
            rej_side[("LONG" if x["side"] > 0 else "SHORT")] += 1
    # bots and challenges
    bots = []
    eq = {}
    for b in db.query("SELECT id, state FROM bots"):
        st = loads(b["state"], {}) or {}
        eq[b["id"]] = st.get("equity") or st.get("balance")
    for t in db.query("SELECT bot_id, symbol, side, opened_at, closed_at, pnl, fees, return_pct, r_multiple, exit_reason, qty, entry, info "
                      "FROM bot_trades WHERE closed_at >= ? AND closed_at < ?", (T0, T1)):
        info = loads(t.get("info"), {}) or {}
        notional = float(t["qty"]) * float(t["entry"])
        bots.append({"bot": t["bot_id"], "coin": t["symbol"].split("/")[0], "side": "LONG" if t["side"] > 0 else "SHORT",
                     "opened": t["opened_at"], "closed": t["closed_at"], "pnl": round(float(t["pnl"]), 2),
                     "r": t.get("r_multiple"), "exit": t["exit_reason"], "lev": info.get("leverage"),
                     "margin": info.get("margin"), "notional": round(notional, 2), "size_mult": info.get("size_mult")})
    chal = []
    for tab in ("hesper_trades", "laststand_trades"):
        if _has(db, tab):
            for t in db.query(f"SELECT run, symbol, timeframe, side, leverage, opened_at, closed_at, margin, pnl, exit_reason FROM {tab} "
                              "WHERE closed_at >= ? AND closed_at < ?", (T0, T1)):
                chal.append({"table": tab, **{k: t[k] for k in ("run", "timeframe", "leverage", "opened_at", "closed_at", "margin", "pnl", "exit_reason")},
                             "coin": t["symbol"].split("/")[0], "side": "LONG" if t["side"] > 0 else "SHORT"})
    # BTC hourly closes and engine gaps
    btc = [(int(r["ts"]), float(r["close"])) for r in db.query(
        "SELECT ts, close FROM market_data WHERE symbol = 'BTC/USDT' AND timeframe = '1h' AND ts >= ? AND ts < ? ORDER BY ts", (T0 - 48 * H, T1))]
    runs = [int(r["started_at"]) for r in db.query("SELECT started_at FROM engine_runs WHERE started_at >= ? AND started_at < ? ORDER BY started_at", (T0, T1))]
    gaps = sorted(((b - a) / 60_000, a) for a, b in zip(runs, runs[1:]))[::-1][:5]
    return {"window": [T0, T1], "calls": calls, "exposure_4h": hours, "held_back": dict(rej), "held_back_side": dict(rej_side),
            "bots": bots, "bot_equity_now": eq, "challenges": chal, "btc_1h": btc, "engine_runs": len(runs),
            "engine_gap_min_top": [[round(g, 1), a] for g, a in gaps]}


def _has(db, t):
    return bool(db.query("SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (t,)))


def _in_record(db, r) -> bool:
    try:
        from . import views
        clause, args = views.record_clause(type("RT", (), {"db": db})())
        return bool(db.query(f"SELECT 1 FROM signals WHERE id = ? AND {clause}", (r["id"], *args)))
    except Exception:
        return True


def challenger(db: Database) -> dict[str, Any]:
    log = db.get_setting("challenger_log", []) or []
    by = defaultdict(lambda: Counter())
    d_brier = defaultdict(list)
    for x in log:
        tf = x.get("tf")
        by[tf]["n"] += 1
        by[tf]["refuse"] += (x.get("verdict") is False)
        by[tf]["no_basis"] += (not x.get("basis"))
        if x.get("brier_new") is not None and x.get("brier_old") is not None:
            d_brier[tf].append(float(x["brier_new"]) - float(x["brier_old"]))
    out = {tf: {**dict(c), "brier_new_minus_old_avg": round(sum(d_brier[tf]) / len(d_brier[tf]), 5) if d_brier[tf] else None}
           for tf, c in by.items()}
    ref = [x for x in log if x.get("verdict") is False]
    return {"n": len(log), "first": log[0]["at"] if log else None, "last": log[-1]["at"] if log else None, "by_tf": out,
            "refusals_sample": [{k: x.get(k) for k in ("tf", "bars", "brier_new", "brier_old", "hit_new", "hit_old", "basis")} for x in ref[-15:]]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--db", default="sqlite:///./data/crypto_ai.db")
    a = ap.parse_args()
    db = Database(a.db)
    out: dict[str, Any] = {"ok": True}
    for k, fn in (("incident", incident), ("challenger", challenger)):
        try:
            out[k] = fn(db)
        except Exception as e:  # noqa: BLE001
            import traceback
            out[k] = {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}
    with open(a.out, "w") as f:
        json.dump(out, f, default=str)


if __name__ == "__main__":
    main()
