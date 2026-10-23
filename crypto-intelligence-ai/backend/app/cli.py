"""Command-line helpers.

  python -m app.cli doctor                      check libraries and exchange connectivity
  python -m app.cli sync [--symbol BTC/USDT]     download / update candle history
  python -m app.cli train [--symbol BTC/USDT] [--timeframe 4h] [--fast]
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from .config import MODEL_TIMEFRAMES, settings
from .db import get_db
from .ml.models import model_status
from .services import market, training
from .services.runtime import Runtime


async def _doctor() -> int:
    print(f"exchange: {settings.exchange}   database: {settings.database_url}")
    for m in model_status():
        print(f"  model {m['label']:<34} {'ok' if m['available'] else 'UNAVAILABLE - ' + str(m['reason'])}")
    try:
        prov = market.make_provider()
    except Exception as exc:
        print(f"provider could not be created: {type(exc).__name__}: {exc}")
        return 1
    try:
        rows = await prov.fetch_ohlcv(settings.symbols[0], "1h", limit=5)
        print(f"exchange reachable: last {settings.symbols[0]} 1h close = {rows[-1][4]}")
        return 0
    except Exception as exc:
        print(f"EXCHANGE NOT REACHABLE: {type(exc).__name__}: {exc}")
        print("Try another EXCHANGE in .env (bybit, okx, kraken) or EXCHANGE=csv with exported candles.")
        return 1
    finally:
        await prov.close()


async def _sync(symbol: str | None) -> int:
    settings.ensure_dirs()
    prov = market.make_provider()
    rt = Runtime(get_db(), prov)
    try:
        for s in [symbol] if symbol else rt.symbols():
            out = await market.sync_symbol(rt, s, force=True)
            print(s, out)
    finally:
        await prov.close()
    return 0


def _train(symbol: str | None, timeframe: str | None, fast: bool) -> int:
    settings.ensure_dirs()
    rt = Runtime(get_db(), None)
    rt.provider = type("Stored", (), {"name": settings.exchange})()     # training reads stored candles only
    failed = 0
    for s in [symbol] if symbol else rt.symbols():
        for tf in [timeframe] if timeframe else MODEL_TIMEFRAMES:
            st = training.train_one(rt, s, tf, fast)
            print(f"{s:<10} {tf:<4} {st['state']:<8} {st.get('error') or st.get('message')}")
            failed += st["state"] == "failed"
    return 1 if failed else 0


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor")
    s = sub.add_parser("sync")
    s.add_argument("--symbol")
    t = sub.add_parser("train")
    t.add_argument("--symbol")
    t.add_argument("--timeframe")
    t.add_argument("--fast", action="store_true")
    a = p.parse_args()
    if a.cmd == "doctor":
        sys.exit(asyncio.run(_doctor()))
    if a.cmd == "sync":
        sys.exit(asyncio.run(_sync(a.symbol)))
    sys.exit(_train(a.symbol, a.timeframe, a.fast))


if __name__ == "__main__":
    main()
