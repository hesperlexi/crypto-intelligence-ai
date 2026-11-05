"""Read-only TP-hit probe for one coin's OPEN record calls: did the price reach each level, on Binance spot (the engine's
candles) and on Binance futures (the website's live price)? Output: booleans and R multiples only - never a call's side,
grade or levels (public report)."""
import json, os, sys, time
import requests
import firebase_admin
from firebase_admin import credentials, firestore
firebase_admin.initialize_app(credentials.Certificate(json.loads(os.environ["FIREBASE_SERVICE_ACCOUNT"])), {"projectId": "crypapp-6a9b9"})
fs = firestore.client()
coin = (sys.argv[1] if len(sys.argv) > 1 else "SOL/USDT").upper()
sym = coin.replace("/", "")


def view(name):
    d = fs.document(f"views/{name}").get().to_dict() or {}
    return json.loads(d.get("json") or "null")


def klines(base, path, since):
    out, t = [], since
    for _ in range(20):
        try:
            r = requests.get(base + path, params={"symbol": sym, "interval": "15m", "startTime": t, "limit": 1000}, timeout=15)
        except Exception as e:
            return {"error": type(e).__name__}
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code} {r.text[:80]}"}
        rows = r.json()
        if not rows:
            break
        out += rows
        if len(rows) < 1000:
            break
        t = rows[-1][0] + 1
    return out


tr = view("track_record") or {}
sigs = (tr.get("live") or {}).get("signals") or tr.get("signals") or []
mine = [s for s in sigs if s.get("symbol") == coin]
res = {"coin": coin, "calls_in_record": len(mine), "calls": []}
sources = {"spot (engine)": ("https://data-api.binance.vision", "/api/v3/klines"),
           "futures (website)": ("https://fapi.binance.com", "/fapi/v1/klines"),
           "spot api.binance.com": ("https://api.binance.com", "/api/v3/klines")}
for s in mine:
    side = 1 if str(s.get("side")).upper() in ("1", "LONG", "BUY") or s.get("side") == 1 else -1
    entry, stop = float(s["entry"]), float(s["stop"])
    risk = abs(entry - stop) or 1e-12
    since = int(s.get("filled_at") or s.get("created_at"))
    until = int(s.get("closed_at") or 0) or None
    c = {"status": s.get("status"), "timeframe": s.get("timeframe"), "age_h": round((time.time() * 1000 - since) / 3.6e6, 1),
         "record_hits": {k: s.get(k) for k in ("tp1_hit", "tp2_hit", "tp3_hit", "stop_hit")},
         "levels_R": {k: round((float(s[k]) - entry) * side / risk, 2) for k in ("tp1", "tp2", "tp3") if s.get(k)}, "sources": {}}
    for name, (base, path) in sources.items():
        k = klines(base, path, since)
        if isinstance(k, dict):
            c["sources"][name] = k
            continue
        if until:
            k = [x for x in k if x[0] <= until]
        first = {}
        for t, r in c["levels_R"].items():
            for x in k:
                mv = ((float(x[2]) - entry) if side > 0 else (entry - float(x[3]))) / risk
                if mv >= r:
                    first[t] = round((x[0] - since) / 60000)
                    break
        hi = max(float(x[2]) for x in k) if k else None
        lo = min(float(x[3]) for x in k) if k else None
        best = ((hi - entry) if side > 0 else (entry - lo)) / risk if k else None
        worst = ((lo - entry) if side > 0 else (entry - hi)) / risk if k else None
        c["sources"][name] = {"candles": len(k), "last_candle_age_min": round((time.time() * 1000 - k[-1][0]) / 60000) if k else None,
                              "best_move_R": round(best, 2) if best is not None else None,
                              "worst_move_R": round(worst, 2) if worst is not None else None,
                              "first_reach_min_after_fill": first, "reached": {t: (best is not None and best >= r) for t, r in c["levels_R"].items()},
                              "last_close_R": round((float(k[-1][4]) - entry) * side / risk, 2) if k else None}
    res["calls"].append(c)
h = view("health") or {}
res["engine"] = {k: v for k, v in h.items() if any(w in k for w in ("lean", "firestore", "budget"))}
res["engine"]["last_tick"] = {k: (h.get("engine") or {}).get(k) for k in ("last_tick_finished", "last_tick_seconds", "failed_steps")}
res["engine"]["now"] = int(time.time() * 1000)
res["track_record_updated"] = (fs.document("views/track_record").get().to_dict() or {}).get("updated_at")
res["engine_series"] = [{"tf": x.get("timeframe"), "candles": x.get("candles"), "status": x.get("status"), "age_min": x.get("age_min")}
                        for x in h.get("series", []) if x.get("symbol") == coin]
print(json.dumps(res, indent=1, default=str))
