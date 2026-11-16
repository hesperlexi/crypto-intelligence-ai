"""v2.49 probe 3 (read-only, no secrets): the engine's own provider fetching MSTR/USDT (MEXC futures) on the runner.
Prints counts / first dates / one price only."""
import asyncio, json, sys, time
sys.path.insert(0, "backend")
from app.data.binance_public import BinancePublicProvider
from app.data.store import CandleStore
from app.db import Database
from app.config import HISTORY_BARS

async def main():
    p, st = BinancePublicProvider(), CandleStore(Database("sqlite:///:memory:"))
    out = {"at": int(time.time())}
    for tf in ("15m", "1h", "4h", "12h", "1d", "3d", "1w"):
        t0 = time.time()
        try:
            n = await st.sync(p, "MSTR/USDT", tf)
            df = st.load("binance", "MSTR/USDT", tf)
            out[tf] = {"written": n, "rows": len(df), "want": HISTORY_BARS.get(tf), "secs": round(time.time() - t0, 1),
                       "first": time.strftime("%Y-%m-%d %H:%M", time.gmtime(int(df["ts"].iloc[0]) / 1e3)) if len(df) else None,
                       "last_close": float(df["close"].iloc[-1]) if len(df) else None}
            from app.data.futures_only import STEP_MS
            ts = [int(x) for x in df["ts"]]
            stp = STEP_MS[tf]
            d = [b - a for a, b in zip(ts, ts[1:])]
            out[tf].update({"misaligned": sum(1 for t in ts if (t - (345_600_000 if tf == "1w" else 0)) % stp),
                            "gaps_not_step": sum(1 for x in d if x != stp), "min_gap": min(d) if d else None,
                            "first5": [time.strftime("%m-%d %H:%M", time.gmtime(t / 1e3)) for t in ts[:5]],
                            "last3": [time.strftime("%m-%d %H:%M", time.gmtime(t / 1e3)) for t in ts[-3:]]})
        except Exception as e:
            out[tf] = {"error": f"{type(e).__name__}: {e}"[:200]}
    import requests
    now = int(time.time())
    for iv, back in (("Day1", 30 * 86400), ("Week1", 120 * 86400), ("Min60", 3 * 86400)):
        r = requests.get(f"https://contract.mexc.com/api/v1/contract/kline/MSTRSTOCK_USDT", params={"interval": iv, "start": now - back, "end": now}, timeout=15).json()
        t = (r.get("data") or {}).get("time") or []
        out["raw_" + iv] = {"n": len(t), "first3": [time.strftime("%m-%d %H:%M", time.gmtime(x)) for x in t[:3]], "last2": [time.strftime("%m-%d %H:%M", time.gmtime(x)) for x in t[-2:]]}
        r = requests.get(f"https://contract.mexc.com/api/v1/contract/kline/MSTRSTOCK_USDT", params={"interval": iv, "start": now - 3000 * 86400, "end": now - 2000 * 86400}, timeout=15).json()
        t = (r.get("data") or {}).get("time") or []
        out["raw_old_" + iv] = {"n": len(t), "first3": [time.strftime("%y-%m-%d %H:%M", time.gmtime(x)) for x in t[:3]]}
    for name, f in (("ticker", p.fetch_ticker("MSTR/USDT")), ("book", p.fetch_order_book("MSTR/USDT", 200)),
                    ("trades", p.fetch_trades("MSTR/USDT", 500)), ("search", p.search_markets("MSTR"))):
        try:
            r = await f
            out[name] = ({"last": r["last"], "change_pct": r["change_pct"]} if name == "ticker" else
                         {"bids": len(r["bids"]), "asks": len(r["asks"])} if name == "book" else
                         {"n": len(r)} if name == "trades" else r)
        except Exception as e:
            out[name] = {"error": f"{type(e).__name__}: {e}"[:200]}
    print(json.dumps(out, indent=1))

asyncio.run(main())
