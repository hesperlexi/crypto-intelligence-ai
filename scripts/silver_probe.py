"""Read-only: where can the engine's runner get silver candles? Counts only."""
import json, requests
out = {}
def get(u, **p):
    try:
        r = requests.get(u, params=p, timeout=15); return r.status_code, (r.json() if r.ok else r.text[:150])
    except Exception as e: return 0, str(e)[:150]
s, d = get("https://contract.mexc.com/api/v1/contract/detail")
if s == 200:
    rows = d.get("data") or []
    out["mexc_matches"] = [x.get("symbol") for x in rows if any(k in (x.get("symbol") or "").upper() for k in ("SILVER", "XAG"))]
    for c in out["mexc_matches"][:4]:
        for iv in ("Min15", "Day1"):
            s2, k = get(f"https://contract.mexc.com/api/v1/contract/kline/{c}", interval=iv)
            t = ((k or {}).get("data") or {}).get("time") or [] if s2 == 200 else []
            cl = ((k or {}).get("data") or {}).get("close") or [] if s2 == 200 else []
            out[f"mexc_{c}_{iv}"] = {"bars": len(t), "first": t[0] if t else None, "last": t[-1] if t else None, "last_close": cl[-1] if cl else None}
        s3, dd = get("https://contract.mexc.com/api/v1/contract/detail", symbol=c)
        if s3 == 200: out[f"mexc_{c}_detail"] = {k: (dd.get("data") or {}).get(k) for k in ("contractSize", "displayNameEn", "state", "createTime")}
for sym in ("XAGUSDT",):
    s, d = get("https://data-api.binance.vision/api/v3/klines", symbol=sym, interval="1d", limit=5)
    out[f"binance_spot_{sym}"] = s
s, d = get("https://www.okx.com/api/v5/public/instruments", instType="SWAP")
if s == 200: out["okx_matches"] = [x["instId"] for x in d.get("data", []) if "XAG" in x["instId"] or "SILVER" in x["instId"]]
s, d = get("https://fapi.binance.com/fapi/v1/klines", symbol="XAGUSDT", interval="1d", limit=3)
out["binance_fapi"] = s if s != 200 else len(d)
try:
    r = requests.post("https://api.hyperliquid.xyz/info", json={"type": "meta"}, timeout=15)
    out["hl_matches"] = [u["name"] for u in r.json().get("universe", []) if "XAG" in u["name"] or "SILVER" in u["name"].upper()]
except Exception as e: out["hl"] = str(e)[:100]
print(json.dumps(out, indent=1))
