"""Read-only: everything the live app shows about one coin (signals, bot positions/trades, analysis per timeframe)."""
import json, os, sys
import firebase_admin
from firebase_admin import credentials, firestore
firebase_admin.initialize_app(credentials.Certificate(json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"])), {"projectId": "crypapp-6a9b9"})
fs = firestore.client()
coin = (sys.argv[1] if len(sys.argv) > 1 else "SOL/USDT").upper()
slug = coin.replace("/", "")


def view(name):
    d = fs.document(f"views/{name}").get().to_dict() or {}
    return json.loads(d.get("json") or "null"), d.get("updated_at")


out = {"coin": coin}
sig, _ = view("signals")
rows = sig.get("signals") if isinstance(sig, dict) else sig
out["signals"] = [r for r in (rows or []) if isinstance(r, dict) and r.get("symbol") == coin][:12]
bots, _ = view("bots")
ob = []
for b in (bots or {}).get("bots", []):
    st = b.get("state") or {}
    ob.append({"bot": (b.get("config") or {}).get("id"),
               "positions": [p for p in (b.get("positions") or st.get("positions") or []) if p.get("symbol") == coin],
               "pending": [p for p in (b.get("pending") or st.get("pending") or []) if p.get("symbol") == coin],
               "trades": [t for t in (b.get("trades") or b.get("recent_trades") or []) if t.get("symbol") == coin][:5]})
out["bots"] = ob
an = {}
for tf in ("15m", "1h", "4h", "12h", "1d", "3d"):
    a, ts = view(f"analysis_{slug}_{tf}")
    if not a:
        continue
    st = a.get("setup") or {}
    an[tf] = {"updated_at": ts, "price": a.get("price"), "decision": a.get("decision"), "grade": a.get("grade"),
              "reason": a.get("decision_reason"), "flags": a.get("flags"), "confidence": a.get("confidence"),
              "runner": a.get("runner"), "setup": {k: st.get(k) for k in ("side", "valid", "entry", "stop", "targets", "risk_reward", "reason")},
              "trend_check": a.get("trend_check")}
out["analysis"] = an
print(json.dumps(out, indent=1, default=str))
