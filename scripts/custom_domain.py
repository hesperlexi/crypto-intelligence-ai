"""Connect a custom domain to Firebase Hosting and allow it for Google sign-in (uses the service account).
Prints the DNS records the owner must add at the registrar. Safe to run again (shows the current state)."""
import json
import os
import sys

import google.auth.transport.requests
from google.oauth2 import service_account

DOMAIN = sys.argv[1]
PROJECT, SITE = "crypapp-6a9b9", "crypapp-6a9b9"
info = json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"])
creds = service_account.Credentials.from_service_account_info(info, scopes=["https://www.googleapis.com/auth/cloud-platform",
                                                                            "https://www.googleapis.com/auth/firebase"])
s = google.auth.transport.requests.AuthorizedSession(creds)
H = f"https://firebasehosting.googleapis.com/v1beta1/projects/{PROJECT}/sites/{SITE}/customDomains"
out = {}
for name, redirect in ((DOMAIN, None), (f"www.{DOMAIN}", DOMAIN)):
    r = s.get(f"{H}/{name}")
    if r.status_code == 404:
        body = {"redirectTarget": redirect} if redirect else {}
        r = s.post(f"{H}?customDomainId={name}", json=body)
    d = r.json()
    if "error" in d:
        out[name] = {"error": d["error"].get("message")}
        continue
    if d.get("name", "").startswith("projects/") and "/operations/" in d.get("name", ""):
        r = s.get(f"{H}/{name}"); d = r.json()
    req = (d.get("requiredDnsUpdates") or {}).get("desired") or []
    recs = []
    for g in req:
        for rec in g.get("records") or []:
            recs.append({"host": g.get("domainName"), "type": rec.get("type"), "value": rec.get("rdata"), "action": rec.get("requiredAction")})
    out[name] = {"host_state": d.get("hostState"), "ownership_state": d.get("ownershipState"), "cert_state": (d.get("cert") or {}).get("state"),
                 "redirect": d.get("redirectTarget"), "records": recs,
                 "current": (d.get("requiredDnsUpdates") or {}).get("discovered")}
# Google sign-in must allow the new domain
cfg_url = f"https://identitytoolkit.googleapis.com/admin/v2/projects/{PROJECT}/config"
c = s.get(cfg_url).json()
doms = c.get("authorizedDomains") or []
want = [x for x in (DOMAIN, f"www.{DOMAIN}") if x not in doms]
if want and "error" not in c:
    u = s.patch(cfg_url + "?updateMask=authorizedDomains", json={"authorizedDomains": doms + want}).json()
    out["auth_domains"] = u.get("authorizedDomains") or u.get("error", {}).get("message")
else:
    out["auth_domains"] = doms if "error" not in c else c["error"].get("message")
print(json.dumps(out, indent=1, default=str))
