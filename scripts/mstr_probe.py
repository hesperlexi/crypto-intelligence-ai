"""v2.49 probe 2 (read-only, no secrets): raw shapes of MSTR perpetual candle sources. Prints short snippets only."""
import json, time, requests
now = int(time.time())
out = {"at": now}
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0 (probe)"
def raw(url, method="GET", **kw):
    try:
        r = S.request(method, url, timeout=15, **kw)
        return {"http": r.status_code, "body": r.text[:400]}
    except Exception as e:
        return {"err": f"{type(e).__name__}: {e}"[:200]}
for sym in ("MSTR_USDT", "MSTRSTOCK_USDT"):
    out[f"detail_{sym}"] = raw(f"https://contract.mexc.com/api/v1/contract/detail?symbol={sym}")
    out[f"kline_{sym}"] = raw(f"https://contract.mexc.com/api/v1/contract/kline/{sym}?interval=Min15&start={now-86400}&end={now}")
    out[f"ticker_{sym}"] = raw(f"https://contract.mexc.com/api/v1/contract/ticker?symbol={sym}")
out["mexc_kline_price_MSTR"] = raw(f"https://contract.mexc.com/api/v1/contract/kline/index_price/MSTR_USDT?interval=Min15&start={now-86400}&end={now}")
out["s3_listing"] = raw("https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?delimiter=/&prefix=data/futures/um/monthly/klines/MSTRUSDT/15m/")
out["s3_daily_listing"] = raw("https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?delimiter=/&prefix=data/futures/um/daily/klines/MSTRUSDT/15m/MSTRUSDT-15m-2026-0")
out["arch_yesterday"] = raw(f"https://data.binance.vision/data/futures/um/daily/klines/MSTRUSDT/15m/MSTRUSDT-15m-{time.strftime('%Y-%m-%d', time.gmtime(now-86400))}.zip", method="HEAD")
for coin in ("MSTR", "xyz:MSTR", "km:MSTR", "flx:MSTR"):
    out[f"hl_{coin}"] = raw("https://api.hyperliquid.xyz/info", method="POST", json={"type": "candleSnapshot", "req": {"coin": coin, "interval": "15m", "startTime": (now-7200)*1000, "endTime": now*1000}})
out["bitget"] = raw("https://api.bitget.com/api/v2/mix/market/candles?symbol=MSTRUSDT&productType=usdt-futures&granularity=15m&limit=3")
out["bybit"] = raw("https://api.bybit.com/v5/market/kline?category=linear&symbol=MSTRUSDT&interval=15&limit=3")
out["okx"] = raw("https://www.okx.com/api/v5/market/candles?instId=MSTR-USDT-SWAP&bar=15m&limit=3")
out["gate"] = raw("https://api.gateio.ws/api/v4/futures/usdt/candlesticks?contract=MSTR_USDT&interval=15m&limit=3")
print(json.dumps(out, indent=1))
