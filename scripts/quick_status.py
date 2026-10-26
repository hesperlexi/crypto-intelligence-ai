"""v2.1 check: watchlist (gold), 15m/1h/4h signal views, and the newest plans' risk/reward (no personal data)."""
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
        "tradable": [{"symbol": r.get("symbol"), "side": (r.get("plan") or {}).get("side"), "grade": r.get("grade"),
                      "rr": round((r.get("plan") or {}).get("risk_reward") or 0, 2),
                      "targets_rr": [round(t.get("rr") or 0, 2) for t in (r.get("plan") or {}).get("targets") or []]}
                     for r in rows if r.get("plan")][:8],
        "statuses": sorted({str(r.get("status")) for r in rows}),
        "gold": next(({k: r.get(k) for k in ("status", "reason", "decision", "grade")} for r in rows if str(r.get("symbol", "")).startswith("PAXG")), None),
    }
h = fs.document("views/health").get().to_dict()
hj = json.loads(h["json"]) if h else {}
out["health"] = {"status": hj.get("status"), "engine": {k: (hj.get("engine") or {}).get(k) for k in ("failed_steps", "last_tick_seconds")},
                 "models_15m": [{"symbol": m["symbol"], "state": m["state"], "message": (m.get("message") or "")[:120]} for m in hj.get("models", []) if m["timeframe"] == "15m"][:30],
                 "series_15m": [{"symbol": s["symbol"], "candles": s["candles"], "status": s["status"]} for s in hj.get("series", []) if s["timeframe"] == "15m"]}
print(json.dumps(out, indent=1, default=str))
