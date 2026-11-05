"""Read-only: status of one coin's newest record call - runner or standard exits (no levels, no side)."""
import json, os, sys
import firebase_admin
from firebase_admin import credentials, firestore
firebase_admin.initialize_app(credentials.Certificate(json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"])), {"projectId": "crypapp-6a9b9"})
fs = firestore.client()
coin = sys.argv[1].upper()
d = fs.document("views/track_record").get().to_dict() or {}
tr = json.loads(d.get("json") or "{}")
sigs = [s for s in ((tr.get("live") or {}).get("signals") or tr.get("signals") or []) if s.get("symbol") == coin]
sigs.sort(key=lambda s: -(s.get("created_at") or 0))
out = []
for s in sigs[:2]:
    p = s.get("payload") if isinstance(s.get("payload"), dict) else {}
    out.append({"timeframe": s.get("timeframe"), "status": s.get("status"), "exit_reason": s.get("exit_reason"),
                "closed": bool(s.get("closed_at")), "hits": {k: s.get(k) for k in ("tp1_hit", "tp2_hit", "tp3_hit", "stop_hit")},
                "runner_on_row": bool(s.get("runner")), "runner_in_payload": bool(p.get("runner")),
                "row_keys": sorted(k for k in s.keys() if "run" in k or "exit" in k or "manag" in k)})
print(json.dumps({"updated_at": d.get("updated_at"), "calls": out}, indent=1))
