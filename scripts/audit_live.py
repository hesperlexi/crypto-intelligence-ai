"""Live audit (manual workflow audit-live.yml): checks the published app data against the product requirements.

Only aggregate facts and coin names go into the report (no prices, no entries, no personal data), because the
reports branch of this public repository is readable by anyone.
"""
import json
import os
import time

import firebase_admin
from firebase_admin import credentials, firestore

firebase_admin.initialize_app(credentials.Certificate(json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"])),
                              {"projectId": "crypapp-6a9b9"})
fs = firestore.client()
now = time.time() * 1000
out: dict = {"checked_at_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime()), "problems": [], "notes": []}
P, N = out["problems"].append, out["notes"].append


def view(name):
    d = fs.document(f"views/{name}").get().to_dict()
    if not d:
        return None, None
    try:
        return json.loads(d.get("json") or "null"), d.get("updated_at")
    except Exception:
        return None, d.get("updated_at")


def age_min(ts):
    if not ts:
        return None
    if hasattr(ts, "timestamp"):
        ts = ts.timestamp() * 1000
    return round((now - float(ts)) / 60000, 1)


# 1. every published view: freshness and size (Firestore documents hold at most 1 MB)
sizes, stale = {}, []
for doc in fs.collection("views").stream():
    d = doc.to_dict() or {}
    n = len(d.get("json") or "")
    sizes[doc.id] = n
    a = age_min(d.get("updated_at"))
    if n > 800_000:
        P(f"view {doc.id} is {n // 1000} KB (limit 1 MB)")
    if a is not None and a > 24 * 60 and not doc.id.startswith(("alerts_u_", "replay", "backtest")):
        stale.append((doc.id, round(a / 60)))
out["views_total"] = len(sizes)
out["views_not_updated_for_a_day"] = sorted(stale, key=lambda x: -x[1])[:40]

# 2. meta / watchlist
meta, meta_ts = view("meta")
meta = meta or {}
out["meta_age_min"] = age_min(meta_ts)
out["model_timeframes"] = meta.get("model_timeframes")
wl = [w["symbol"] if isinstance(w, dict) else w for w in (meta.get("watchlist") or [])]
out["watchlist_n"] = len(wl)
out["gold_in_watchlist"] = "PAXG/USDT" in wl
if set(meta.get("model_timeframes") or []) != {"15m", "1h", "4h", "12h", "1d", "3d"}:
    P(f"model timeframes are {meta.get('model_timeframes')} (required 15m/1h/4h/12h/1d/3d)")
if "PAXG/USDT" not in wl:
    P("gold (PAXG/USDT) is not in the watchlist")

# 3. signals per timeframe: targets 1R / [1.25,2]R / [2,3]R, blended R:R >= 1.25
tfs = {}
for tf in ("15m", "1h", "4h", "12h", "1d", "3d"):
    for kind in ("futures", "dashboard"):
        v, ts = view(f"{kind}_{tf}")
        if v is None:
            P(f"view {kind}_{tf} is missing")
            continue
        if kind != "futures":
            continue
        rows = v.get("rows") or []
        valid = [r for r in rows if (r.get("plan") or {}).get("valid")]
        bad = []
        for r in valid:
            pl = r["plan"]
            rr = [t.get("rr") for t in pl.get("targets") or []]
            ok = (len(rr) == 3 and abs(rr[0] - 1) < 0.02 and 1.24 <= rr[1] <= 2.01 and 1.99 <= rr[2] <= 3.01
                  and (pl.get("risk_reward") or 0) >= 1.24)
            if not ok:
                bad.append({"symbol": r["symbol"], "targets_rr": rr, "rr": pl.get("risk_reward")})
        stat = {}
        for r in rows:
            stat[r.get("status")] = stat.get(r.get("status"), 0) + 1
        grades = {}
        for r in valid:
            grades[str(r.get("grade"))] = grades.get(str(r.get("grade")), 0) + 1
        tfs[tf] = {"age_min": age_min(ts), "coins": len(rows), "statuses": stat, "trade_plans": len(valid),
                   "grades": grades, "gold_row": any(r["symbol"] == "PAXG/USDT" for r in rows),
                   "target_rule_breaks": bad[:8]}
        if bad:
            P(f"{tf}: {len(bad)} trade plans break the 1:1 / 1:1.25-2 / 1:2-3 target rule")
        a = age_min(ts)
        limit = {"15m": 30, "1h": 90}.get(tf, 300)
        if a is not None and a > limit:
            P(f"futures_{tf} not updated for {a} min")
out["timeframes"] = tfs

# 4. track record honesty: losses must be visible
tr, ts = view("track_record")
live = (tr or {}).get("live") or {}
out["track_record"] = {"age_min": age_min(ts), "since": (tr or {}).get("since"),
                       **{k: live.get(k) for k in ("closed", "wins", "losses", "win_rate", "total_return_pct",
                                                   "avg_return_pct", "open")}}
perf, _ = view("performance")
out["performance_keys"] = list((perf or {}).keys())

# 5. wins today / weekly report
w, ts = view("wins_today")
out["wins_today"] = {"age_min": age_min(ts), "period": (w or {}).get("period"), "n": len((w or {}).get("wins") or [])}
wr, ts = view("weekly_report")
out["weekly_report_age_min"] = age_min(ts)

# 6. bots
b, ts = view("bots")
bots = (b or {}).get("bots") or []
out["bots"] = {"age_min": age_min(ts), "n": len(bots), "ids": [x.get("id") for x in bots][:30]}
cfg = (fs.document("config/bots").get().to_dict() or {}).get("bots") or []
ids = [x.get("id") for x in cfg]
if len(ids) != len(set(ids)):
    P("config/bots has duplicate bot ids")
out["bots"]["configured"] = len(cfg)

# 7. membership + payments (public config)
m = fs.document("config/membership").get().to_dict() or {}
out["membership"] = {"keys": sorted(m.keys()),
                     "plans": [{k: p.get(k) for k in ("id", "name", "price", "currency", "days")} for p in (m.get("plans") or [])],
                     "payment_methods": [x.get("id") or x.get("name") for x in (m.get("payment_methods") or m.get("methods") or [])],
                     "support_email_set": bool(m.get("support_email"))}

# 8. telegram (never the token)
tg = fs.document("owner/telegram").get().to_dict() or {}
out["telegram"] = {k: tg.get(k) for k in ("enabled", "channel", "post_wins", "post_weekly", "post_teaser", "post_each_win",
                                          "approve_first")}
out["telegram"]["token_set"] = bool(tg.get("token"))
st = fs.document("owner/telegram_status").get().to_dict() or {}
out["telegram"]["status"] = {"ok": st.get("ok"), "errors": st.get("errors"), "last_post_min_ago": age_min(st.get("last_post_at")),
                             "checked_min_ago": age_min(st.get("checked_at"))}
dr = fs.document("owner/telegram_drafts").get().to_dict() or {}
out["telegram"]["drafts_waiting"] = len(dr.get("items") or [])
if tg.get("enabled") and not tg.get("token"):
    P("Telegram autopilot is on but no bot token is saved")
if st.get("errors"):
    P(f"Telegram errors: {st.get('errors')}")

# 9. people (counts only)
pres = [d.to_dict() or {} for d in fs.collection("presence").stream()]
out["presence"] = {"n": len(pres), "with_country": sum(1 for p in pres if p.get("country")),
                   "active_10_min": sum(1 for p in pres if (age_min(p.get("last_seen")) or 1e9) < 10),
                   "devices": sorted({str(p.get("device")) for p in pres})[:8]}
mem = list(fs.collection("members").limit(500).stream()) if True else []
out["members_docs"] = len(mem)

# 10. jobs stuck in the queue
stuck = []
for d in fs.collection("jobs").where("status", "==", "queued").limit(50).stream():
    j = d.to_dict() or {}
    a = age_min(j.get("created_at"))
    if a and a > 20:
        stuck.append({"type": j.get("type"), "age_min": a})
out["jobs_stuck"] = stuck
if stuck:
    P(f"{len(stuck)} website jobs waited more than 20 minutes")

# 11. health
h, ts = view("health")
h = h or {}
out["health"] = {"status": h.get("status"), "age_min": age_min(ts), "failed_steps": (h.get("engine") or {}).get("failed_steps"),
                 "paused_by_safety_switch": len(h.get("safety") or h.get("safety_paused") or []),
                 "recent_errors": (h.get("recent_errors") or [])[:5]}
if h.get("status") not in ("LIVE", "OK"):
    P(f"health is {h.get('status')}")

# 12. news / radar / context freshness
for n, lim in (("news", 120), ("radar", 120), ("context", 120)):
    v, ts = view(n)
    a = age_min(ts)
    out[f"{n}_age_min"] = a
    if v is None:
        P(f"view {n} missing")
    elif a is not None and a > lim:
        P(f"view {n} not updated for {a} min")

print(json.dumps(out, indent=1, default=str))

# 13. model coverage: which coin/timeframes have no model and why (from the health view)
hm = (h or {}).get("models") or []
skipped = [{k: r.get(k) for k in ("symbol", "timeframe", "state", "message")} for r in hm
           if str(r.get("state") or "").lower() not in ("done", "active")]
cnt = {}
for r in hm:
    cnt.setdefault(r.get("timeframe"), [0, 0])[0 if str(r.get("state")).lower() == "done" else 1] += 1
print(json.dumps({"models_done_vs_not_by_tf": cnt, "not_trained": skipped[:200]}, indent=1, default=str))
ser = [s for s in (h.get("series") or []) if s.get("timeframe") in ("3d", "1w")]
print(json.dumps({"series_3d_1w": [{k: s.get(k) for k in ("symbol", "timeframe", "candles", "missing", "quality_pct", "first_ts")} for s in ser]}, default=str))
hb = fs.document("admin/engine_heartbeat").get().to_dict() or {}
if hb.get("stack"):
    print("STACK:\n" + hb["stack"])
print(json.dumps({"heartbeat": {**{k: v for k, v in hb.items() if k != "stack"}, "at_min_ago": age_min(hb.get("at")), "tick_started_min_ago": age_min(hb.get("tick_started"))}}, default=str))

# 14. consistency of every published trade plan with its own inputs (the numbers members act on)
import math
MMR = 0.005


def liq(entry, side, lev):
    lev = max(1.0, float(lev))
    return max(0.0, entry * (1 - 1 / lev + MMR)) if side > 0 else entry * (1 + 1 / lev - MMR)


def safe_lev(entry, stop, mx=20, buffer=1.5):
    d = abs(entry - stop) / entry
    return int(max(1, min(mx, math.floor(1 / (buffer * d + MMR))))) if d > 0 else 1


checks = {"plans": 0, "problems": []}
Q = checks["problems"].append
for tf in ("15m", "1h", "4h", "12h", "1d", "3d"):
    v, _ = view(f"futures_{tf}")
    for r in (v or {}).get("rows") or []:
        sym = r.get("symbol")
        pr = [r.get("p_up"), r.get("p_down"), r.get("p_neutral")]
        if all(x is not None for x in pr) and abs(sum(pr) - 1) > 0.02:
            Q(f"{sym} {tf}: probabilities add to {sum(pr):.3f}")
        if r.get("confidence") is not None and not 0 <= r["confidence"] <= 1:
            Q(f"{sym} {tf}: confidence {r['confidence']} outside 0-1")
        dec, grade = r.get("decision"), r.get("grade")
        if grade and dec not in ("BUY", "BUY ON PULLBACK", "SELL"):
            Q(f"{sym} {tf}: grade {grade} on a {dec} decision")
        p = r.get("plan") or {}
        if not p.get("valid"):
            continue
        checks["plans"] += 1
        side = 1 if p.get("side") == "LONG" else -1
        e, s, tg = p.get("entry"), p.get("stop"), p.get("targets") or []
        if dec in ("BUY", "BUY ON PULLBACK") and side < 0 or dec == "SELL" and side > 0:
            Q(f"{sym} {tf}: decision {dec} but plan side {p.get('side')}")
        if not (e and s) or side * (e - s) <= 0:
            Q(f"{sym} {tf}: stop on the wrong side of entry"); continue
        R = abs(e - s)
        prices = [t["price"] for t in tg]
        if len(prices) != 3 or any(side * (prices[i] - (prices[i - 1] if i else e)) <= 0 for i in range(3)):
            Q(f"{sym} {tf}: targets not in order beyond entry")
        for t in tg:
            if abs(side * (t["price"] - e) / R - t["rr"]) > 0.02:
                Q(f"{sym} {tf}: {t['name']} price is {side * (t['price'] - e) / R:.2f}R but labelled 1:{t['rr']}")
        zone = p.get("entry_zone") or []
        if zone and not (min(zone) - 1e-9 <= e <= max(zone) + 1e-9):
            Q(f"{sym} {tf}: entry outside its entry zone")
        if p.get("risk_pct") is not None and abs(p["risk_pct"] - R / e * 100) > 0.01:
            Q(f"{sym} {tf}: risk % {p['risk_pct']:.3f} vs {R / e * 100:.3f} from entry/stop")
        bl = 0.5 * 1 + 0.25 * tg[1]["rr"] + 0.25 * tg[2]["rr"] if len(tg) == 3 else None
        if bl is not None and p.get("risk_reward") is not None and abs(p["risk_reward"] - bl) > 0.02:
            Q(f"{sym} {tf}: blended R:R {p['risk_reward']:.2f} vs {bl:.2f}")
        lev = p.get("suggested_leverage")
        if lev:
            if lev > min(10, safe_lev(e, s)):
                Q(f"{sym} {tf}: suggested {lev}x above the safe {min(10, safe_lev(e, s))}x")
            if abs((p.get("liquidation_at_suggested") or 0) - liq(e, side, lev)) > e * 1e-6:
                Q(f"{sym} {tf}: liquidation price does not match {lev}x")
            if side * (p["liquidation_at_suggested"] - s) >= 0:
                Q(f"{sym} {tf}: liquidation before the stop at {lev}x")
        run = p.get("runner") or {}
        if run.get("on") and abs(side * (run["target"] - e) / R - run.get("rr", 4)) > 0.02:
            Q(f"{sym} {tf}: runner target is not 1:{run.get('rr')}")
checks["problems"] = checks["problems"][:40]
print(json.dumps({"plan_checks": checks}))

# 15. record arithmetic
tr, _ = view("track_record")
lv = (tr or {}).get("live") or {}
sm = lv.get("summary") or {}
sig = lv.get("signals") or []
closed = [x for x in sig if x.get("status") not in ("OPEN", "INFO") and x.get("return_pct") is not None]
rec = {"summary": sm, "listed_signals": len(sig), "listed_closed": len(closed),
       "statuses": {s: sum(1 for x in sig if x.get("status") == s) for s in {x.get("status") for x in sig}}}
bad = [x for x in closed if (x["status"] == "STOPPED" and x["return_pct"] > 0.001)
       or (x["status"] in ("TP2", "TP3") and x["return_pct"] < -0.001)]
rec["status_return_mismatch"] = len(bad)
if sm.get("closed") and len(closed) == sm["closed"]:
    import statistics
    rec["win_rate_check"] = abs(sum(1 for x in closed if x["return_pct"] > 0) / len(closed) - sm["win_rate"]) < 1e-9
    rec["total_check"] = abs(sum(x["return_pct"] for x in closed) - sm["total_return_pct"]) < 1e-6
print(json.dumps({"record_checks": rec}, default=str))

# 16. bots: sane numbers
b, _ = view("bots")
bc = []
for bt in (b or {}).get("bots") or []:
    st = bt.get("stats") or {}
    eq, cash = st.get("equity"), (bt.get("state") or {}).get("cash")
    pos = bt.get("positions") or (bt.get("state") or {}).get("positions") or []
    wrong = 0
    for q in pos:
        if q.get("stop") and q.get("entry") and q.get("tp_hit", 0) == 0 and q["side"] * (q["entry"] - q["stop"]) <= 0:
            wrong += 1
    bc.append({"id": (bt.get("config") or {}).get("id") or bt.get("id"), "equity": round(eq, 2) if isinstance(eq, (int, float)) else eq,
               "trades": st.get("trades"), "open": len(pos), "lev": (bt.get("config") or {}).get("leverage"),
               "stop_wrong_side": wrong, "cash_negative": isinstance(cash, (int, float)) and cash < -1e-6})
print(json.dumps({"bot_checks": bc}, default=str))

# 17. failed website jobs (types only)
fj = []
for d in fs.collection("jobs").where("status", "==", "failed").limit(20).stream():
    j = d.to_dict() or {}
    fj.append({"type": j.get("type"), "age_h": round((age_min(j.get("created_at")) or 0) / 60, 1), "error": str(j.get("error") or j.get("result"))[:120]})
print(json.dumps({"failed_jobs": sorted(fj, key=lambda x: x["age_h"])[:10]}, default=str))
