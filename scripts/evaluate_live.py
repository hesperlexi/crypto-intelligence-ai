"""Live evaluation snapshot (no personal data): signal record, bots, models, engine timing, member counts."""
import json, os, time
import firebase_admin
from firebase_admin import credentials, firestore

firebase_admin.initialize_app(credentials.Certificate(json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"])), {"projectId": "crypapp-6a9b9"})
fs = firestore.client()
def view(n):
    d = fs.document(f"views/{n}").get().to_dict()
    return json.loads(d["json"]) if d and d.get("json") else {}
tr = view("track_record"); bots = view("bots"); h = view("health"); perf = view("performance"); ms = view("models_status")
out = {"track_record_keys": sorted(tr.keys())[:40]}
for k in ("summary", "totals", "by_timeframe", "by_grade", "since", "record_since"):
    if k in tr: out[k] = tr[k]
out["bots"] = [{k: b.get(k) for k in ("id", "name", "timeframe", "market", "return_pct", "trades", "win_rate", "max_drawdown_pct", "equity", "open")}
               for b in (bots.get("bots") or [])][:30]
out["engine"] = {k: (h.get("engine") or {}).get(k) for k in ("last_tick_seconds", "failed_steps", "ticks", "schedule_minutes")}
out["models"] = {"edge": sum(1 for m in h.get("models", []) if m.get("edge_confirmed")), "total": len(h.get("models", []))}
out["perf_keys"] = sorted(perf.keys())[:30]
users = [d.to_dict() for d in fs.collection("users").stream()]
now = time.time() * 1000
out["members"] = {"total": len(users), "approved_active": sum(1 for u in users if u.get("status") == "approved" and (not u.get("expires_at") or u["expires_at"] > now)),
                  "pending": sum(1 for u in users if u.get("status") == "pending")}
out["presence"] = len(list(fs.collection("presence").stream()))
print(json.dumps(out, indent=1, default=str)[:20000])
