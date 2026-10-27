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
print(json.dumps(out, indent=1))
