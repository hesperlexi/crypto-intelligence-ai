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


# v2.13: the output goes to the public `reports` branch and public job logs, so it holds COUNTS only - never a call's
# side, grade, levels, decision or a bot's positions (members pay for those).
out = {"coin": coin}
sig, _ = view("signals")
rows = sig.get("signals") if isinstance(sig, dict) else sig
rows = [r for r in (rows or []) if isinstance(r, dict) and r.get("status") != "INFO" and (coin == "ALL" or r.get("symbol") == coin)]
out["signals"] = {"total": len(rows), "by_status": {s: sum(1 for r in rows if r.get("status") == s) for s in sorted({str(r.get("status")) for r in rows})},
                  "by_timeframe": {t: sum(1 for r in rows if r.get("timeframe") == t) for t in sorted({str(r.get("timeframe")) for r in rows})}}
bots, _ = view("bots")
ob = []
for b in (bots or {}).get("bots", []):
    st = b.get("state") or {}
    match = (lambda x: coin == "ALL" or x.get("symbol") == coin)
    ob.append({"bot": (b.get("config") or {}).get("id"),
               "open_positions": sum(1 for p in (b.get("positions") or st.get("positions") or []) if match(p)),
               "pending_orders": sum(1 for p in (b.get("pending") or st.get("pending") or []) if match(p)),
               "closed_trades": sum(1 for t in (b.get("trades") or []) if match(t))})
out["bots"] = ob
an = {}
for tf in (() if coin == "ALL" else ("15m", "1h", "4h", "12h", "1d", "3d")):
    a, ts = view(f"analysis_{slug}_{tf}")
    if not a:
        continue
    an[tf] = {"updated_at": ts, "status": a.get("status"), "has_flags": bool(a.get("flags"))}
out["analysis"] = an
print(json.dumps(out, indent=1, default=str))
