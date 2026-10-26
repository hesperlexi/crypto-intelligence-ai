"""Sanitised notification errors (no uid, no email): error code/message, app vs browser, Android and browser version."""
import json, os, re
import firebase_admin
from firebase_admin import credentials, firestore

firebase_admin.initialize_app(credentials.Certificate(json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"])), {"projectId": "crypapp-6a9b9"})
fs = firestore.client()
rows = []
for d in fs.collection("user_state").stream():
    x = d.to_dict() or {}
    e = x.get("push_error")
    ok = x.get("push_ok_at")
    if not e and not ok:
        continue
    ua = (e or {}).get("ua") or ""
    android = re.search(r"Android [\d.]+", ua)
    browser = re.search(r"(SamsungBrowser|Chrome|Firefox|Edg|OPR)/[\d]+", ua)
    rows.append({"step": (e or {}).get("step"), "code": (e or {}).get("code"), "message": str((e or {}).get("message"))[:200],
                 "app": (e or {}).get("app"), "android": android.group(0) if android else None,
                 "browser": browser.group(0) if browser else None, "at": (e or {}).get("at"), "ok_at": ok})
tokens = [{"app": (t.to_dict() or {}).get("app"), "browser": (re.search(r"(SamsungBrowser|Chrome)/\d+", (t.to_dict() or {}).get("ua") or "") or [None])[0]}
          for t in fs.collection("push_tokens").stream()]
print(json.dumps({"errors": rows, "tokens": tokens}, indent=1, default=str))
