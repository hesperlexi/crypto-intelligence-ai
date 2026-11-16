"""v2.49 probe (read-only, no secrets): can the engine runner get MSTR perpetual candles? Prints counts / spans only."""
import json, time, requests

out = {"at": int(time.time())}
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (probe)"
def get(url, **kw):
    try:
        r = S.get(url, timeout=15, **kw)
        return r.status_code, (r.json() if "json" in r.headers.get("content-type", "") else r.text[:200])
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"[:200]

# MEXC futures: contract detail + candles
for sym in ("MSTR_USDT", "MSTRSTOCK_USDT", "MSTRX_USDT"):
    c, j = get(f"https://contract.mexc.com/api/v1/contract/detail?symbol={sym}")
    out[f"mexc_detail_{sym}"] = {"http": c, "ok": isinstance(j, dict) and j.get("success"), "name": (j.get("data") or {}).get("displayNameEn") if isinstance(j, dict) and isinstance(j.get("data"), dict) else None}
c, j = get("https://contract.mexc.com/api/v1/contract/kline/MSTR_USDT", params={"interval": "Min15"})
d = (j or {}).get("data") if isinstance(j, dict) else None
out["mexc_kline_15m_recent"] = {"http": c, "n": len((d or {}).get("time", [])) if isinstance(d, dict) else 0,
                                 "last": ((d or {}).get("time") or [None])[-1] if isinstance(d, dict) else None,
                                 "last_close": ((d or {}).get("close") or [None])[-1] if isinstance(d, dict) else None}
# how far back: daily candles from 2020
c, j = get("https://contract.mexc.com/api/v1/contract/kline/MSTR_USDT", params={"interval": "Day1", "start": 1577836800, "end": int(time.time())})
d = (j or {}).get("data") if isinstance(j, dict) else None
t = (d or {}).get("time", []) if isinstance(d, dict) else []
out["mexc_daily"] = {"http": c, "n": len(t), "first": t[0] if t else None}
c, j = get("https://contract.mexc.com/api/v1/contract/kline/MSTR_USDT", params={"interval": "Min15", "start": int(time.time()) - 400 * 86400, "end": int(time.time()) - 399 * 86400})
d = (j or {}).get("data") if isinstance(j, dict) else None
out["mexc_15m_400d_ago"] = {"http": c, "n": len((d or {}).get("time", [])) if isinstance(d, dict) else 0}
c, j = get("https://contract.mexc.com/api/v1/contract/ticker", params={"symbol": "MSTR_USDT"})
out["mexc_ticker"] = {"http": c, "last": ((j or {}).get("data") or {}).get("lastPrice") if isinstance(j, dict) else None}
# Binance: futures REST (geo-blocked from US?) and the public archive
c, j = get("https://fapi.binance.com/fapi/v1/klines", params={"symbol": "MSTRUSDT", "interval": "15m", "limit": 5})
out["binance_fapi"] = {"http": c, "n": len(j) if isinstance(j, list) else 0, "last_close": j[-1][4] if isinstance(j, list) and j else None}
day = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 2 * 86400))
c, _ = get(f"https://data.binance.vision/data/futures/um/daily/klines/MSTRUSDT/15m/MSTRUSDT-15m-{day}.zip")
out["binance_archive_daily"] = {"http": c, "day": day}
print(json.dumps(out, indent=1))
