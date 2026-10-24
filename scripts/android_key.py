"""Get the Android signing key, or create it once. The key lives in Firestore (admin_secrets/android_signing),
a collection no website user can read (no security rule matches it); only the service account can.

Writes android/android.keystore and appends KEYSTORE_PASSWORD / SHA256 fingerprint to $GITHUB_ENV.
"""
import base64
import json
import os
import secrets
import subprocess
import sys
import time

import firebase_admin
from firebase_admin import credentials, firestore

ALIAS = "cryptoai"
out = sys.argv[1] if len(sys.argv) > 1 else "android/android.keystore"
cred = credentials.Certificate(json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"]))
firebase_admin.initialize_app(cred, {"projectId": "crypapp-6a9b9"})
ref = firestore.client().document("admin_secrets/android_signing")
snap = ref.get()
if snap.exists:
    d = snap.to_dict()
    open(out, "wb").write(base64.b64decode(d["keystore_b64"]))
    password = d["password"]
    print("using the existing signing key from", d.get("created_at"))
else:
    password = secrets.token_urlsafe(24)
    subprocess.run(["keytool", "-genkeypair", "-keystore", out, "-alias", ALIAS, "-keyalg", "RSA", "-keysize", "2048",
                    "-validity", "10000", "-storepass", password, "-keypass", password,
                    "-dname", "CN=Hesper, O=Hesper, C=AE"], check=True)
    ref.set({"keystore_b64": base64.b64encode(open(out, "rb").read()).decode(), "password": password, "alias": ALIAS,
             "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    print("created a new signing key and stored it in Firestore")
listing = subprocess.run(["keytool", "-list", "-v", "-keystore", out, "-alias", ALIAS, "-storepass", password],
                         capture_output=True, text=True, check=True).stdout
fp = next(line.split("SHA256:", 1)[1].strip() for line in listing.splitlines() if "SHA256:" in line)
with open(os.environ.get("GITHUB_ENV", "/dev/null"), "a") as f:
    f.write(f"KEYSTORE_PASSWORD={password}\nSHA256_FINGERPRINT={fp}\n")
print(f"::add-mask::{password}")
print("fingerprint", fp)
