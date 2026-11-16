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
        except Exception as e:
            out[tf] = {"error": f"{type(e).__name__}: {e}"[:200]}
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
