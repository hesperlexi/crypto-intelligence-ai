"""Summary of the engine's last health record (views/health): overall status and the reasons behind it."""
import json, os, time
import firebase_admin
from firebase_admin import credentials, firestore

firebase_admin.initialize_app(credentials.Certificate(json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"])), {"projectId": "crypapp-6a9b9"})
doc = firestore.client().document("views/health").get().to_dict() or {}
h = json.loads(doc.get("json") or "{}")
now = time.time() * 1000
series = h.get("series") or []
bad = [s for s in series if s.get("status") != "OK"]
out = {
    "status": h.get("status"), "generated_min_ago": round((now - (h.get("generated_at") or now)) / 60000, 1),
    "market_data": h.get("market_data"), "exchange": h.get("exchange"), "database": h.get("database"),
    "engine": {k: (h.get("engine") or {}).get(k) for k in ("last_tick_finished", "last_tick_seconds", "failed_steps", "data_host", "ticks")},
    "series_total": len(series), "series_not_ok": len(bad),
    "not_ok": [{k: s.get(k) for k in ("symbol", "timeframe", "status", "candles", "missing", "misaligned", "malformed", "quality_pct", "age_s", "gaps")} for s in bad][:60],
    "recent_errors": (h.get("recent_errors") or [])[:10],
}
print(json.dumps(out, indent=1, default=str))
