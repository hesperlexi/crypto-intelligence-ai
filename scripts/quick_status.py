"""v2.1 check: watchlist (gold), signal views and record, as AGGREGATE COUNTS only (no personal data).

The output goes to the public `reports` branch and public job logs, so it never contains a call's coin, side, grade or
levels (members pay for those), nor any record row - only counts and statuses (v2.13)."""
import json, os, time
import firebase_admin
from firebase_admin import credentials, firestore

firebase_admin.initialize_app(credentials.Certificate(json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"])), {"projectId": "crypapp-6a9b9"})
fs = firestore.client()
wl = [x.get("symbol") for x in (fs.document("config/watchlist").get().to_dict() or {}).get("symbols", [])]
out = {"watchlist": wl, "views": {}}
for tf in ("15m", "1h", "4h", "12h", "1d", "3d"):
    d = fs.document(f"views/futures_{tf}").get().to_dict()
    v = json.loads(d["json"]) if d and d.get("json") else {}
    rows = v.get("rows") or []
    out["views"][tf] = {
        "rows": len(rows), "updated": (d or {}).get("updated_at"),
        "with_plan": sum(1 for r in rows if r.get("plan")),
        "grades": {g: sum(1 for r in rows if r.get("plan") and str(r.get("grade")) == g) for g in sorted({str(r.get("grade")) for r in rows if r.get("plan")})},
        "statuses": sorted({str(r.get("status")) for r in rows}),
        "gold_row": any(str(r.get("symbol", "")).startswith("PAXG") for r in rows),
    }
# size of every published view (what the website downloads), largest first
out["view_sizes_kb"] = sorted(((d.id, round(len((d.to_dict() or {}).get("json") or "") / 1024, 1)) for d in fs.collection("views").stream()),
                              key=lambda x: -x[1])[:25]
h = fs.document("views/health_admin").get().to_dict() or fs.document("views/health").get().to_dict()
hj = json.loads(h["json"]) if h else {}
out["health"] = {"status": hj.get("status"), "engine": {k: v for k, v in (hj.get("engine") or {}).items()
                                                         if not isinstance(v, (list, dict)) or k in ("failed_steps",)},
                 "quota": {k: v for k, v in hj.items() if any(w in k for w in ("firestore", "reads", "writes", "lean", "budget"))},
                 "models_15m": [{"symbol": m["symbol"], "state": m["state"], "message": (m.get("message") or "")[:120]} for m in hj.get("models", []) if m["timeframe"] == "15m"][:30],
                 "series_15m": [{"symbol": s["symbol"], "candles": s["candles"], "status": s["status"]} for s in hj.get("series", []) if s["timeframe"] == "15m"]}
ages = {}
for m in hj.get("models", []):
    ages.setdefault(m["timeframe"], []).append(m.get("age_h"))
out["model_age_h"] = {tf: {"n": len(v), "fresh_12h": sum(1 for a in v if a is not None and a <= 12),
                           "max": max((a for a in v if a is not None), default=None), "missing": sum(1 for a in v if a is None)}
                      for tf, v in ages.items()}
out["last_train"] = (hj.get("engine") or {}).get("last_train")
out["safety"] = hj.get("safety")
# v2.1 fresh start check: release marker, record views, practice data counts (no personal data)
out["release"] = fs.document("config/release").get().to_dict()
tr = fs.document("views/track_record").get().to_dict()
trj = json.loads(tr["json"]) if tr and tr.get("json") else {}
out["track_record"] = {"record_since": trj.get("record_since"), "live_signals": len((trj.get("live") or {}).get("signals") or trj.get("signals") or []),
                       "updated": (tr or {}).get("updated_at")}
sigs = (trj.get("live") or {}).get("signals") or trj.get("signals") or []
out["record_live"] = {"summary": (trj.get("live") or {}).get("summary") or trj.get("summary"),
                      "by_timeframe": (trj.get("live") or {}).get("by_timeframe") or trj.get("by_timeframe"),
                      # counts only: no coin / side / levels / single results
                      "signals_by_status": {s: sum(1 for x in sigs if x.get("status") == s) for s in sorted({str(x.get("status")) for x in sigs})},
                      "signals_by_timeframe": {t: sum(1 for x in sigs if x.get("timeframe") == t) for t in sorted({str(x.get("timeframe")) for x in sigs})}}
out["counts"] = {c: sum(1 for _ in fs.collection(c).select([]).stream()) for c in ("paper", "paper_trades", "paper_futures_trades", "auto_paper_state", "jobs")}
bots = fs.document("config/bots").get().to_dict() or {}
out["bots"] = [{"id": b.get("id"), "reset_token": b.get("reset_token")} for b in bots.get("bots", [])]
# notifications check (no secrets: booleans, kinds and counts only)
tg = fs.document("owner/telegram").get().to_dict() or {}
out["telegram"] = {"has_token": bool(tg.get("token")), "has_channel": bool(tg.get("channel")),
                   **{k: v for k, v in tg.items() if k.startswith(("enabled", "approve_first", "post_"))}}
st = fs.document("owner/telegram_status").get().to_dict() or {}
out["telegram_status"] = {k: st.get(k) for k in ("ok", "checked_at", "last_sent", "last_post_at", "updated_at")}
out["telegram_status"]["errors"] = len(st.get("errors") or [])
dr = fs.document("owner/telegram_drafts").get().to_dict() or {}
out["telegram_drafts"] = {"n": len(dr.get("items") or []), "items": [{k: i.get(k) for k in ("kind", "created_at", "at")} for i in (dr.get("items") or [])][:10]}
out["telegram"]["keys"] = sorted(k for k in tg.keys() if k != "token")
out["push_tokens"] = sum(1 for _ in fs.collection("push_tokens").select([]).stream())
import re as _re
_jobs = [d.to_dict() or {} for d in fs.collection("jobs").where("type", "==", "telegram_post").stream()]
out["telegram_post_jobs"] = [{"status": j.get("status"), "created_at": j.get("created_at"),
                              "error": _re.sub(r"bot\d+:[\w-]+", "bot***", str(j.get("error") or (j.get("result") or {}).get("reason") or ""))[:200]}
                             for j in sorted(_jobs, key=lambda j: -(j.get("created_at") or 0))[:5]]
# every job type: how many done / failed / waiting, and the newest failure reasons (no user data)
try:
    js = {}
    for d in fs.collection("jobs").stream():
        j = d.to_dict() or {}
        t = js.setdefault(str(j.get("type")), {"n": 0, "status": {}, "errors": [], "oldest_queued_min": None})
        t["n"] += 1
        st = str(j.get("status")); t["status"][st] = t["status"].get(st, 0) + 1
        if j.get("error") and len(t["errors"]) < 3:
            t["errors"].append(_re.sub(r"bot\d+:[\w-]+", "bot***", str(j.get("error")))[:160])
        if st in ("queued", "pending", "running") and j.get("created_at"):
            age = round((time.time() * 1000 - int(j["created_at"])) / 60000)
            t["oldest_queued_min"] = max(t["oldest_queued_min"] or 0, age)
    out["jobs_summary"] = js
except Exception as exc:
    out["jobs_summary"] = {"error": str(exc)[:200]}
# v2.75 check: views/derivs summary + silver (XAG/USDT) models (counts / names only)
try:
    dv = fs.document("views/derivs").get().to_dict()
    dj = json.loads(dv["json"]) if dv else {}
    out2 = {"exists": bool(dv), "generated_at": dj.get("generated_at"), "coins": len(dj.get("coins") or {}),
            "liq_maps": len(dj.get("liq_maps") or {}), "volatility": sorted((dj.get("volatility") or {}).keys()),
            "macro": sorted((dj.get("macro") or {}).keys()), "unlocks": len(dj.get("unlocks") or [])}
except Exception as exc:
    out2 = {"error": type(exc).__name__}
xag = {}
for tf in ("15m", "1h", "4h", "12h", "1d", "3d"):
    m = fs.document(f"views/models_XAGUSDT_{tf}").get().to_dict()
    mj = json.loads(m["json"]) if m else {}
    xag[tf] = {"exists": bool(m), "active": bool(mj.get("active") or mj.get("bundle") or mj.get("models")), "keys": sorted(mj.keys())[:8]}
out["derivs"], out["xag_models"] = out2, xag
# V3.0 market risk state (state, score, factor levels only)
try:
    r = fs.document("views/risk_state").get().to_dict()
    rj = json.loads(r["json"]) if r and "json" in r else (r or {})
    out["risk_state"] = {"state": rj.get("state"), "score": rj.get("score"), "at": rj.get("generated_at"),
                         "factors": {f["key"]: f["status"] for f in rj.get("factors") or []}} if rj else None
except Exception as e:  # noqa: BLE001
    out["risk_state"] = {"error": type(e).__name__}
# Hesper challenge (main + Last Stand): counts only - no coin, side or levels in this public report
for vid in ("hesper", "laststand"):
    try:
        r = fs.document(f"views/{vid}").get().to_dict()
        hj = json.loads(r["json"]) if r and "json" in r else (r or {})
        def _n(o, k):
            v = o.get(k) if isinstance(o, dict) else None
            return len(v) if isinstance(v, list) else v
        out[f"challenge_{vid}"] = {"keys": sorted(hj.keys())[:30], "runs": _n(hj, "runs"), "trades": _n(hj, "trades"),
                                   "at": hj.get("generated_at"), "since": hj.get("since"),
                                   "current_run": (hj.get("current") or {}).get("run") if isinstance(hj.get("current"), dict) else None,
                                   "run_numbers": [x.get("run") for x in (hj.get("runs") or []) if isinstance(x, dict)][:40],
                                   "run_trades": [x.get("trades") for x in (hj.get("runs") or []) if isinstance(x, dict)][:40],
                                   "laststand": {k: (len(v) if isinstance(v, list) else v if isinstance(v, (int, float, str)) else None)
                                                 for k, v in (hj.get("laststand") or {}).items()} if isinstance(hj.get("laststand"), dict) else None}
    except Exception as e:  # noqa: BLE001
        out[f"challenge_{vid}"] = {"error": type(e).__name__}
# news / calendar (public facts only): is the calendar arriving, which high-impact US events were due
try:
    import time as _t
    nd = fs.document("views/news").get().to_dict() or {}
    nv = json.loads(nd["json"]) if nd.get("json") else {}
    now_ms_ = int(_t.time() * 1000)
    cal = nv.get("calendar") or []
    hi = [e for e in cal if e.get("impact") == "High" and e.get("country") == "USD"]
    out["news"] = {"updated": nd.get("updated_at"), "generated_at": nv.get("generated_at"), "calendar_n": len(cal),
                   "high_usd": [{"title": e.get("title"), "ts": e.get("ts"), "past": e.get("ts", 0) < now_ms_} for e in hi][:20],
                   "next_high": (nv.get("next_high") or {}).get("title"), "headlines_n": len(nv.get("headlines") or []),
                   "errors": nv.get("errors")}
except Exception as exc:
    out["news"] = {"error": str(exc)[:200]}
try:
    _h = fs.document("views/health_admin").get().to_dict() or {}
    hj = json.loads(_h["json"]) if _h.get("json") else {}
    out["alert_watcher"] = (hj.get("engine") or {}).get("alert_watcher")
except Exception:
    pass
# health tiles the owner sees as warnings: market data, exchange errors, AI check (counts / labels only)
try:
    _h = fs.document("views/health_admin").get().to_dict() or {}
    hj = json.loads(_h["json"]) if _h.get("json") else {}
    out["hj_keys"] = sorted(hj.keys())
    out["md"] = {k: v for k, v in (hj.get("market_data") or {}).items() if not isinstance(v, list)}
    out["md_stale"] = [{k: v for k, v in x.items() if k in ("symbol", "timeframe", "status", "candles", "last_ts", "age_s", "gaps", "quality_pct", "missing")} for x in (hj.get("series") or []) if x.get("status") not in ("OK", "ok", "LIVE", None)][:40]
    out["series_status"] = {st_: sum(1 for x in (hj.get("series") or []) if x.get("status") == st_) for st_ in {x.get("status") for x in (hj.get("series") or [])}}
    out["series_sample"] = (hj.get("series") or [None])[0]
    _e = hj.get("engine") or {}
    out["step_avg"] = dict(sorted((_e.get("step_seconds_avg") or {}).items(), key=lambda kv: -(kv[1] or 0))[:15])
    out["step_max"] = dict(sorted((_e.get("step_seconds_max") or {}).items(), key=lambda kv: -(kv[1] or 0))[:10])
    out["eng_watch"] = {k: v for k, v in (hj.get("engine") or {}).items() if k.startswith(("watch", "alert", "flow", "round", "last_tick"))}
    out["exchange"] = {k: (v if not isinstance(v, (list, dict)) else str(v)[:300]) for k, v in (hj.get("exchange") or {}).items()}
    g = fs.document("views/guardian").get().to_dict() or {}
    gj = json.loads(g["json"]) if g.get("json") else {}
    cal = (gj.get("checks") or {}).get("calibration") or {}
    out["ai_check"] = {"warnings": cal.get("warnings"), "by_tf": {tf: {k: v for k, v in (x or {}).items() if not isinstance(v, (list, dict))} for tf, x in (cal.get("by_tf") or cal.get("timeframes") or {}).items()} if isinstance(cal.get("by_tf") or cal.get("timeframes"), dict) else None,
                       "keys": sorted(cal.keys())}
except Exception as exc:
    out["md_probe_error"] = str(exc)[:200]
# auto-trade: per member (anonymous index) the settings that decide what is taken, and recent outcomes (no coin / side / levels)
try:
    import time as _t2
    cut = int(_t2.time() * 1000) - 2 * 86_400_000
    ap = []
    for i, d in enumerate(fs.collection("auto_paper").stream()):
        a = d.to_dict() or {}
        st_ = fs.document(f"auto_paper_state/{d.id}").get().to_dict() or {}
        log = [x for x in (st_.get("log") or []) if int(x.get("ts") or 0) >= cut]
        reasons, last2h = {}, {}
        for x in log:
            k = f"{x.get('timeframe')}|{x.get('grade')}|{x.get('action')}|{x.get('reason') or ''}"
            reasons[k] = reasons.get(k, 0) + 1
            if int(x.get("ts") or 0) >= int(time.time() * 1000) - 2 * 3_600_000:
                last2h[k] = last2h.get(k, 0) + 1
        ap.append({"n": i, "enabled": a.get("enabled"), "timeframes": a.get("timeframes"), "grades": a.get("grades"),
                   "coins": a.get("coins"), "max_open": a.get("max_open"), "max_same_side": a.get("max_same_side"),
                   "max_new_per_day": a.get("max_new_per_day"), "last2h": last2h, "margin": {k: a.get(k) for k in a if "margin" in k or "size" in k or "risk" in k},
                   "state_updated": st_.get("updated_at"), "recent": reasons})
    out["auto_trade"] = ap
except Exception as exc:
    out["auto_trade"] = {"error": str(exc)[:200]}
# the Cloudflare price-alert watcher itself (counts only; no tokens, no keys)
try:
    import hashlib, urllib.request
    key = hashlib.sha256(("cia-edge-v1|" + os.environ["FIREBASE_SERVICE_ACCOUNT"]).encode()).hexdigest()
    req = urllib.request.Request("https://cia-chat.cryptointelai.workers.dev/watch/status?since=0", headers={"X-Edge-Key": key, "User-Agent": "cia-status"})
    st = json.load(urllib.request.urlopen(req, timeout=20))
    out["cloud_watcher"] = {**{k: st.get(k) for k in ("at", "armed", "armed_at", "sent", "sent_total", "due", "priced", "error", "idle")},
                            "sent_keys_n": len(st.get("sent_keys") or []), "bad_tokens_n": len(st.get("bad_tokens") or []),
                            "engine_diag": st.get("engine_diag"), "fcm_check": st.get("fcm_check"), "price_tries": st.get("price_tries")}
except Exception as exc:
    out["cloud_watcher"] = {"probe_error": str(exc)[:200]}
print(json.dumps(out, indent=1, default=str))

