"""Read-only probe: how long each Firestore read of the engine's config step takes, and how big it is."""
import json, os, time
import firebase_admin
from firebase_admin import credentials, firestore
firebase_admin.initialize_app(credentials.Certificate(json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"])), {"projectId": "crypapp-6a9b9"})
fs = firestore.client()
out = {}
for col in ("users", "user_coins", "alerts", "jobs", "push_tokens", "presence", "paper", "auto_paper", "auto_paper_state"):
    t = time.time()
    try:
        docs = list(fs.collection(col).stream(timeout=120))
        size = sum(len(json.dumps(d.to_dict() or {}, default=str)) for d in docs)
        out[col] = {"docs": len(docs), "mb": round(size / 1e6, 2), "seconds": round(time.time() - t, 1)}
        if col == "jobs":
            st = {}
            for d in docs:
                s = (d.to_dict() or {}).get("status"); st[s] = st.get(s, 0) + 1
            out[col]["by_status"] = st
    except Exception as e:
        out[col] = {"error": f"{type(e).__name__}: {e}"[:300], "seconds": round(time.time() - t, 1)}
for path in ("config/watchlist", "config/settings", "config/bots", "owner/telegram"):
    t = time.time()
    try:
        d = fs.document(path).get(timeout=60).to_dict() or {}
        out[path] = {"keys": len(d), "seconds": round(time.time() - t, 1)}
    except Exception as e:
        out[path] = {"error": f"{type(e).__name__}: {e}"[:300]}
t = time.time()
try:
    fs.document("admin/probe").set({"at": int(time.time() * 1000)}, timeout=60); out["write_test"] = {"ok": True, "seconds": round(time.time() - t, 1)}
except Exception as e:
    out["write_test"] = {"error": f"{type(e).__name__}: {e}"[:300]}
rj = []
for d in fs.collection("jobs").order_by("created_at", direction=firestore.Query.DESCENDING).limit(8).stream():
    j = d.to_dict() or {}
    rj.append({"type": j.get("type"), "status": j.get("status"), "created_at": j.get("created_at"),
               "started_at": j.get("started_at"), "finished_at": j.get("finished_at") or j.get("done_at")})
out["recent_jobs"] = rj
import statistics
rb = {}
for tf in ("15m", "1h", "4h", "12h", "1d"):
    d = fs.document(f"views/futures_{tf}").get().to_dict() or {}
    rows = (json.loads(d.get("json") or "{}") or {}).get("rows") or []
    rk = sorted(r["plan"]["risk_pct"] for r in rows if (r.get("plan") or {}).get("risk_pct"))
    tr = sorted(r["plan"]["risk_pct"] for r in rows if (r.get("plan") or {}).get("valid") and r.get("decision") in ("BUY", "SELL", "BUY ON PULLBACK"))
    rb[tf] = {"plans": len(rk), "risk_pct_min": rk[0] if rk else None, "median": statistics.median(rk) if rk else None,
              "max": rk[-1] if rk else None, "tradable_risk_pcts": [round(x, 2) for x in tr]}
out["risk_by_tf"] = rb
out["watchlist"] = (fs.document("config/watchlist").get().to_dict() or {})
d = fs.document("views/track_record").get().to_dict() or {}
tr = json.loads(d.get("json") or "{}") or {}
out["tested"] = [{k: t.get(k) for k in ("symbol", "timeframe", "edge", "all_calls_hit_rate", "selective_hit_rate", "selective_calls", "coverage", "calls_per_day")}
                 for t in tr.get("tested") or []]
out["live_signals"] = [{k: x.get(k) for k in ("symbol", "timeframe", "status", "return_pct")} for x in (tr.get("live") or {}).get("signals") or []]
print(json.dumps(out, indent=1, default=str))
