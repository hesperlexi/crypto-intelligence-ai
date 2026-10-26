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
           if str(r.get("state") or "").lower() != "done"]
cnt = {}
for r in hm:
    cnt.setdefault(r.get("timeframe"), [0, 0])[0 if str(r.get("state")).lower() == "done" else 1] += 1
print(json.dumps({"models_done_vs_not_by_tf": cnt, "not_trained": skipped[:80]}, indent=1, default=str))
ser = [s for s in (h.get("series") or []) if s.get("timeframe") in ("3d", "1w")]
print(json.dumps({"series_3d_1w": [{k: s.get(k) for k in ("symbol", "timeframe", "candles", "missing", "quality_pct", "first_ts")} for s in ser]}, default=str))
