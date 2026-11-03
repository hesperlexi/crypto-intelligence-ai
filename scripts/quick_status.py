"""v2.1 check: watchlist (gold), signal views and record, as AGGREGATE COUNTS only (no personal data).

The output goes to the public `reports` branch and public job logs, so it never contains a call's coin, side, grade or
levels (members pay for those), nor any record row - only counts and statuses (v2.13)."""
import json, os
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
h = fs.document("views/health").get().to_dict()
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
print(json.dumps(out, indent=1, default=str))
