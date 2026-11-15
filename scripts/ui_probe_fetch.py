"""ui-probe.yml: copy live views (member-readable data) into frontend/dev/live/<name>.json for a local page test on the
runner. Nothing is committed or uploaded; only the probe's error report leaves the job."""
import json
import os
import pathlib
import sys

import firebase_admin
from firebase_admin import credentials, firestore

firebase_admin.initialize_app(credentials.Certificate(json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"])), {"projectId": "crypapp-6a9b9"})
fs = firestore.client()
out = pathlib.Path("frontend/dev/live")
out.mkdir(parents=True, exist_ok=True)
for name in sys.argv[1:]:
    d = fs.document(f"views/{name}").get().to_dict() or {}
    (out / f"{name}.json").write_text(d.get("json") or "null")
    print(name, len(d.get("json") or ""))
