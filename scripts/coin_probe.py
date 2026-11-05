"""Read-only: does the bot position on one coin carry a runner target (no levels, no side)."""
import json, os, sys
import firebase_admin
from firebase_admin import credentials, firestore
firebase_admin.initialize_app(credentials.Certificate(json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"])), {"projectId": "crypapp-6a9b9"})
fs = firestore.client()
coin = sys.argv[1].upper()
d = fs.document("views/bots").get().to_dict() or {}
v = json.loads(d.get("json") or "{}")
out = []
for b in v.get("bots", []):
    st = b.get("state") or {}
    for p in (b.get("positions") or st.get("positions") or []):
        if p.get("symbol") == coin:
            info = p.get("info") or {}
            out.append({"bot": (b.get("config") or {}).get("id"), "runner_target": info.get("run_target") is not None,
                        "info_keys": sorted(info.keys())[:30], "pos_keys": sorted(p.keys())[:30]})
    for t in (b.get("trades") or [])[-50:]:
        if t.get("symbol") == coin:
            out.append({"bot": (b.get("config") or {}).get("id"), "closed_trade_reason": t.get("reason") or t.get("exit_reason"), "opened": t.get("opened_at")})
print(json.dumps(out, indent=1, default=str))
