"""Read-only probe: is an Anthropic pre-IPO perpetual reachable from the runners (MEXC / OKX / Binance archive)?
Counts only -> reports/anthropic-probe.json"""
import json
import urllib.request


def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "cia-probe"}), timeout=15) as r:
            return json.load(r)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"[:200]}


out = {}
d = get("https://contract.mexc.com/api/v1/contract/detail")
names = [c.get("symbol") for c in (d.get("data") or [])] if isinstance(d, dict) else []
out["mexc_matches"] = [n for n in names if "ANTHROP" in str(n).upper()]
for sym in out["mexc_matches"][:3]:
    k = get(f"https://contract.mexc.com/api/v1/contract/kline/{sym}?interval=Min60")
    data = (k or {}).get("data") or {}
    t = data.get("time") or []
    out[f"mexc_{sym}_1h"] = {"bars": len(t), "first": t[0] if t else None, "last": t[-1] if t else None,
                             "last_close": (data.get("close") or [None])[-1]}
    k = get(f"https://contract.mexc.com/api/v1/contract/kline/{sym}?interval=Day1")
    t = ((k or {}).get("data") or {}).get("time") or []
    out[f"mexc_{sym}_1d"] = {"bars": len(t), "first": t[0] if t else None}
o = get("https://www.okx.com/api/v5/public/instruments?instType=SWAP")
out["okx_matches"] = [i.get("instId") for i in (o.get("data") or []) if "ANTHROP" in str(i.get("instId")).upper()] if isinstance(o, dict) else []
b = get("https://fapi.binance.com/fapi/v1/exchangeInfo")
out["binance_fapi"] = "blocked" if "error" in b else [s["symbol"] for s in b.get("symbols", []) if "ANTHROP" in s["symbol"]]
print(json.dumps(out, indent=1))
