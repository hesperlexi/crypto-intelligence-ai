"""Where does the engine's analysis step spend its time? Read-only profile on a copy of the engine state (no publishing).
Run from backend/: python ../scripts/profile_analyses.py. Prints timings per timeframe and the top functions (no coin data)."""
import cProfile
import io
import os
import pstats
import sys
import time

sys.path.insert(0, os.getcwd())
from app.config import settings  # noqa: E402
from app.db import get_db  # noqa: E402
from app.services import analysis, market  # noqa: E402
from app.services.runtime import Runtime  # noqa: E402

settings.ensure_dirs()
rt = Runtime(get_db(), market.make_provider())
syms = rt.symbols()
pr = cProfile.Profile()
per = {}
for tf in ("15m", "1h", "4h", "12h", "1d", "3d"):
    t0 = time.time()
    pr.enable()
    for s in syms:
        try:
            analysis.analyze(rt, s, tf, detail=True, use_cache=False)
        except Exception as exc:
            print("error", tf, type(exc).__name__)
    pr.disable()
    per[tf] = round(time.time() - t0, 1)
print("coins", len(syms), "seconds per timeframe", per, "total", round(sum(per.values()), 1))
# a normal (non-hourly) cycle: fresh models + memo, only 15m / 1h / 4h analysed (what most engine cycles do)
from app.ml import trainer  # noqa: E402
rt.__dict__.pop("_fc_memo", None)
trainer._cache.clear()
rt.analysis_cache.clear() if hasattr(rt, "analysis_cache") else None
t0 = time.time()
for tf in ("15m", "1h", "4h"):
    for s in syms:
        analysis.analyze(rt, s, tf, detail=True, use_cache=False)
print("normal cycle (15m/1h/4h, cold models)", round(time.time() - t0, 1))
# second pass on 15m: what a repeat analysis on the same candle costs
t0 = time.time()
for s in syms:
    analysis.analyze(rt, s, "15m", detail=True, use_cache=False)
print("15m repeat", round(time.time() - t0, 1))
buf = io.StringIO()
pstats.Stats(pr, stream=buf).sort_stats("cumulative").print_stats(45)
print(buf.getvalue()[-12000:])
buf = io.StringIO()
pstats.Stats(pr, stream=buf).sort_stats("tottime").print_stats(25)
print(buf.getvalue()[-6000:])
