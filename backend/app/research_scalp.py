"""Independent futures SCALPING study on 5m / 10m / 15m bars built from Binance USDT-M 1-minute candles (read-only).

  python -m app.research_scalp [--cache data/scalp_cache] [--out results/scalp.json] [--budget 6600] [--months 12]

Question (owner, Nov 2026): would a separate scalping engine make money AFTER realistic costs, and what would help?
Nothing here touches the live engine, its database, Firestore or the app: the data are the public archive files of
data.binance.vision (futures 1m klines + funding rates), cached on disk.

Method (no look-ahead):
  * 1m candles on a full UTC minute grid; 5m/10m/15m bars aggregated from complete minutes only (a bar with a missing
    minute never signals). A signal is decided on a CLOSED bar; the earliest entry is the open of the next 1m bar.
  * Entry valid 3 minutes: MARKET (taker, first available 1m open) or LIMIT at the signal close that must trade THROUGH
    (maker) within the window, else no trade.
  * Exits followed on 1m bars: stop checked first inside a bar, stop fills at min/max(open, stop); TP1 = 1R closes 50 %
    and moves the stop to break-even (a break-even touch in the same 1m bar as TP1 is assumed to come after it), TP2 = 2R
    closes the rest (limit orders, must trade through); time stop after T bars of the signal timeframe (market close).
  * Costs: taker 0.05 %/side, maker 0.02 %, slippage 0.02 % per market fill (0.03 % on stop fills), funding pro-rata
    from the archive (fallback 0.01 %/8h). Results in R (1R = stop distance) and in % of notional, gross and net.
  * Costs rule like the app: no trade when the TP1 distance (1R) < 3 x the round-trip taker cost (0.14 %).
  * One position per coin per configuration; portfolio view with max 3 concurrent positions.
  * 6 strategy families x 4 parameter sets x 2 time stops = 48 configurations per timeframe (144 in all).
  * Chronological split per coin: first 60 % tune (best parameters per family per timeframe), next 20 % select
    (Bonferroni over the 18 family/timeframe candidates, day-block bootstrap), last 20 % holdout (evaluated once for the
    18 tuned candidates; "selected" marks those that passed). White reality check + deflated Sharpe for the tuning.
  * Levers (decided before the holdout; effect shown on select AND holdout): limit entries, TP1 >= 5 x cost, only with the
    coin's 1h trend, favourable BTC-trend x volatility regimes (chosen on tune+select), liquid coins only (top 4 by tune
    volume), EU/US session only, VIP fee tier (maker 0.018 % / taker 0.045 %).
Output: one JSON document (also with a progress log and any error) on stdout and in --out.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import sys
import time
import traceback
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import NormalDist
from typing import Any, Callable

import numpy as np
import pandas as pd

try:                                                     # numba makes the 1-minute walk fast on Actions; optional
    from numba import njit
    HAVE_NUMBA = True
except Exception:                                        # pragma: no cover - plain Python fallback (tests, sandbox)
    HAVE_NUMBA = False

    def njit(*a, **k):
        if a and callable(a[0]):
            return a[0]
        return lambda f: f

BASE = "https://data.binance.vision/data/futures/um"
COINS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "LTCUSDT", "AVAXUSDT", "AAVEUSDT",
         "LINKUSDT", "PAXGUSDT")
TFS = (5, 10, 15)
TIME_STOPS = (30, 90)                                    # bars of the signal timeframe
TP1_R, TP2_R = 1.0, 2.0
ENTRY_WINDOW = 3                                         # minutes
TAKER, MAKER, SLIP, SLIP_STOP = 0.0005, 0.0002, 0.0002, 0.0003
VIP_TAKER, VIP_MAKER = 0.00045, 0.00018
RT_COST = 2 * TAKER + 2 * SLIP                           # 0.14 % round trip at market
COST_MULT = 3.0
FUND_FALLBACK = 0.0001 / 480.0                           # 0.01 % per 8 h, per minute
SPLITS = (0.6, 0.8)
MIN_TUNE_TRADES = 60
BOOT = 2000
BLOCK_DAYS = 5
ALPHA = 0.05
SESSIONS = (0, 420, 810)                                 # UTC minute of day: Asia 00:00, London 07:00, NY 13:30
LIQUID_N = 4

FEES_BASE = {"taker": TAKER, "maker": MAKER, "slip": SLIP, "slip_stop": SLIP_STOP}
FEES_VIP = {"taker": VIP_TAKER, "maker": VIP_MAKER, "slip": SLIP, "slip_stop": SLIP_STOP}
FEES_ZERO = {"taker": 0.0, "maker": 0.0, "slip": 0.0, "slip_stop": 0.0}

LOG: list[str] = []
T_START = time.time()


def log(msg: str) -> None:
    line = f"[{time.time() - T_START:7.0f}s] {msg}"
    LOG.append(line)
    print(line, file=sys.stderr, flush=True)


# ================================================================================================ data (public archive)

def month_list(n: int, today: date | None = None) -> list[str]:
    """The n most recent COMPLETE calendar months before `today`, oldest first ('YYYY-MM')."""
    t = today or datetime.now(timezone.utc).date()
    y, m = t.year, t.month
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(f"{y:04d}-{m:02d}")
    return out[::-1]


def _get(url: str, path: Path, tries: int = 3) -> bytes | None:
    if path.exists():
        b = path.read_bytes()
        return b or None                                 # an empty file caches a 404
    import requests
    for i in range(tries):
        try:
            r = requests.get(url, timeout=60)
            if r.status_code == 404:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"")
                return None
            r.raise_for_status()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(r.content)
            return r.content
        except Exception as e:                           # noqa: BLE001
            if i == tries - 1:
                log(f"download failed {url}: {e}")
                return None
            time.sleep(2 + 3 * i)
    return None


def _read_zip_csv(b: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(b)) as z:
        name = z.namelist()[0]
        raw = z.read(name)
    first = raw[:200].decode("utf-8", "ignore").split("\n", 1)[0]
    header = 0 if any(ch.isalpha() for ch in first.split(",")[0]) else None
    return pd.read_csv(io.BytesIO(raw), header=header)


def parse_klines(b: bytes) -> pd.DataFrame:
    df = _read_zip_csv(b)
    df = df.iloc[:, :6].copy()
    df.columns = ["ts", "open", "high", "low", "close", "volume"]
    df = df.apply(pd.to_numeric, errors="coerce").dropna()
    ts = df["ts"].astype("int64")
    ts = np.where(ts > 10**14, ts // 1000, ts)           # microsecond archives -> ms
    df["ts"] = ts
    return df


def parse_funding(b: bytes) -> pd.DataFrame:
    df = _read_zip_csv(b)
    cols = [str(c).lower() for c in df.columns]
    if "calc_time" in cols:
        df.columns = cols
        out = pd.DataFrame({"ts": pd.to_numeric(df["calc_time"], errors="coerce"),
                            "hours": pd.to_numeric(df.get("funding_interval_hours", 8), errors="coerce"),
                            "rate": pd.to_numeric(df["last_funding_rate"], errors="coerce")})
    else:
        out = pd.DataFrame({"ts": pd.to_numeric(df.iloc[:, 0], errors="coerce"),
                            "hours": pd.to_numeric(df.iloc[:, 1], errors="coerce"),
                            "rate": pd.to_numeric(df.iloc[:, 2], errors="coerce")})
    out = out.dropna()
    out["hours"] = out["hours"].where(out["hours"] > 0, 8)
    return out


def load_coin(sym: str, months: list[str], cache: Path) -> tuple[pd.DataFrame | None, pd.DataFrame | None, dict]:
    parts, fparts, info = [], [], {"months": 0, "daily_files": 0, "funding_months": 0}
    for ym in months:
        b = _get(f"{BASE}/monthly/klines/{sym}/1m/{sym}-1m-{ym}.zip", cache / "klines" / f"{sym}-1m-{ym}.zip")
        if b:
            parts.append(parse_klines(b))
            info["months"] += 1
        elif ym == months[-1]:                           # newest month not published yet -> daily files
            y, m = map(int, ym.split("-"))
            nd = (date(y + (m == 12), m % 12 + 1, 1) - date(y, m, 1)).days
            for d in range(1, nd + 1):
                ds = f"{ym}-{d:02d}"
                bd = _get(f"{BASE}/daily/klines/{sym}/1m/{sym}-1m-{ds}.zip", cache / "klines" / f"{sym}-1m-{ds}.zip")
                if bd:
                    parts.append(parse_klines(bd))
                    info["daily_files"] += 1
        fb = _get(f"{BASE}/monthly/fundingRate/{sym}/{sym}-fundingRate-{ym}.zip",
                  cache / "funding" / f"{sym}-fundingRate-{ym}.zip")
        if fb:
            fparts.append(parse_funding(fb))
            info["funding_months"] += 1
    if not parts:
        return None, None, info
    k = pd.concat(parts).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    f = pd.concat(fparts).drop_duplicates("ts").sort_values("ts").reset_index(drop=True) if fparts else None
    return k, f, info


# ================================================================================================ minute grid / bars

def to_grid(k: pd.DataFrame, funding: pd.DataFrame | None = None) -> dict[str, Any]:
    """Full UTC minute grid from the day of the first candle. Missing minutes: flat at the previous close, valid=False."""
    t0 = int(k["ts"].iloc[0]) // 86_400_000 * 86_400_000
    idx = ((k["ts"].to_numpy(np.int64) - t0) // 60_000).astype(np.int64)
    n = int(idx[-1]) + 1
    g = {name: np.full(n, np.nan) for name in ("open", "high", "low", "close", "volume")}
    for name in g:
        g[name][idx] = k[name].to_numpy(float)
    valid = ~np.isnan(g["close"])
    c = pd.Series(g["close"]).ffill().bfill().to_numpy()
    for name in ("open", "high", "low", "close"):
        g[name] = np.where(valid, g[name], c)
    g["volume"] = np.where(valid, g["volume"], 0.0)
    rate = np.full(n, FUND_FALLBACK)
    if funding is not None and len(funding):
        fi = ((funding["ts"].to_numpy(np.int64) - t0) // 60_000)
        per_min = funding["rate"].to_numpy(float) / (funding["hours"].to_numpy(float) * 60.0)
        s = pd.Series(np.nan, index=np.arange(n))
        ok = (fi >= 0) & (fi < n)
        s.iloc[fi[ok]] = per_min[ok]
        pre = per_min[fi < 0]
        if len(pre):
            s.iloc[0] = pre[-1]
        rate = s.ffill().fillna(FUND_FALLBACK).to_numpy()   # the rate known in force (last settled) - no look-ahead
    g["valid"] = valid
    g["fund_cum"] = np.concatenate([[0.0], np.cumsum(rate)])  # long pays fund_cum[x] - fund_cum[j] (fraction)
    g["t0"] = t0
    g["n"] = n
    return g


def aggregate(g: dict[str, Any], tf: int) -> dict[str, np.ndarray]:
    """tf-minute bars aligned to UTC multiples; bar k covers minutes [k*tf, (k+1)*tf); complete = all minutes valid."""
    nb = g["n"] // tf
    m = nb * tf
    sh = (nb, tf)
    o = g["open"][:m].reshape(sh)[:, 0]
    h = g["high"][:m].reshape(sh).max(axis=1)
    lo = g["low"][:m].reshape(sh).min(axis=1)
    c = g["close"][:m].reshape(sh)[:, -1]
    v = g["volume"][:m].reshape(sh).sum(axis=1)
    complete = g["valid"][:m].reshape(sh).all(axis=1)
    return {"open": o, "high": h, "low": lo, "close": c, "volume": v, "complete": complete,
            "entry_min": (np.arange(nb, dtype=np.int64) + 1) * tf, "tf": tf}


# ================================================================================================ indicators

def ema(x: np.ndarray, span: float) -> np.ndarray:
    return pd.Series(x).ewm(span=span, adjust=False).mean().to_numpy()


def atr(b: dict, n: int = 14) -> np.ndarray:
    h, lo, c = b["high"], b["low"], b["close"]
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - lo, np.maximum(np.abs(h - pc), np.abs(lo - pc)))
    return pd.Series(tr).ewm(alpha=1.0 / n, adjust=False).mean().to_numpy()


def _prev_roll(x: np.ndarray, n: int, fn: str) -> np.ndarray:
    """Rolling stat of the n bars BEFORE the current one (excludes the signal bar)."""
    r = getattr(pd.Series(x).rolling(n, min_periods=n), fn)()
    return r.shift(1).to_numpy()


# ================================================================================================ strategy families
# Each returns (side int8 per bar, stop distance per bar); the signal price is the bar close.

def f_breakout(b: dict, p: dict, cx: dict) -> tuple[np.ndarray, np.ndarray]:
    hh, ll = _prev_roll(b["high"], p["n"], "max"), _prev_roll(b["low"], p["n"], "min")
    va = _prev_roll(b["volume"], 20, "mean")
    spike = b["volume"] > p["k"] * va
    c = b["close"]
    side = np.where(spike & (c > hh), 1, np.where(spike & (c < ll), -1, 0))
    return side.astype(np.int8), 1.5 * cx["atr"]


def f_pullback(b: dict, p: dict, cx: dict) -> tuple[np.ndarray, np.ndarray]:
    ef, es = ema(b["close"], p["fast"]), ema(b["close"], p["slow"])
    c, h, lo = b["close"], b["high"], b["low"]
    ph, pl = np.roll(h, 1), np.roll(lo, 1)
    pef = np.roll(ef, 1)
    es_slope = es - np.roll(es, 5)
    up = (ef > es) & (es_slope > 0) & (c > es)
    dn = (ef < es) & (es_slope < 0) & (c < es)
    long_ = up & (pl <= pef) & (c > ph) & (c > ef)
    short = dn & (ph >= pef) & (c < pl) & (c < ef)
    side = np.where(long_, 1, np.where(short, -1, 0))
    side[:p["slow"] + 5] = 0
    return side.astype(np.int8), p["m"] * cx["atr"]


def f_momentum(b: dict, p: dict, cx: dict) -> tuple[np.ndarray, np.ndarray]:
    c = b["close"]
    n = p["n"]
    roc = c / np.roll(c, n) - 1.0
    r1 = np.diff(np.log(c), prepend=np.log(c[0]))
    sd = _prev_roll(r1, 100, "std") * math.sqrt(n)
    z = roc / sd
    rng = b["high"] - b["low"]
    expand = rng > 1.5 * np.roll(cx["atr"], 1)
    side = np.where(expand & (z > p["z"]), 1, np.where(expand & (z < -p["z"]), -1, 0))
    side[:max(n, 101)] = 0
    return side.astype(np.int8), 1.5 * cx["atr"]


def f_meanrev(b: dict, p: dict, cx: dict) -> tuple[np.ndarray, np.ndarray]:
    c = pd.Series(b["close"])
    mid = c.rolling(20).mean()
    sd = c.rolling(20).std()
    up, lo = (mid + p["k"] * sd).to_numpy(), (mid - p["k"] * sd).to_numpy()
    width = ((4 * sd) / mid).to_numpy()
    q = pd.Series(width).rolling(500, min_periods=200).quantile(p["q"]).shift(1).to_numpy()
    calm = width <= q
    cc = b["close"]
    side = np.where(calm & (cc < lo), 1, np.where(calm & (cc > up), -1, 0))
    return side.astype(np.int8), 1.5 * cx["atr"]


def f_session(b: dict, p: dict, cx: dict) -> tuple[np.ndarray, np.ndarray]:
    tf = b["tf"]
    nb = len(b["close"])
    side = np.zeros(nb, np.int8)
    stop = np.full(nb, np.nan)
    start_min = np.arange(nb, dtype=np.int64) * tf
    mod = start_min % 1440
    day0 = start_min - mod
    win = 240 // tf
    m = p["bars"]
    for s0 in SESSIONS:
        if s0 % tf:
            continue
        firsts = np.nonzero(mod == s0)[0]
        for k0 in firsts:
            if k0 + m + 1 >= nb or day0[k0 + m] != day0[k0]:
                continue
            seg = slice(k0, k0 + m)
            if not b["complete"][seg].all():
                continue
            hi, lo_ = b["high"][seg].max(), b["low"][seg].min()
            done_l = done_s = False
            for k in range(k0 + m, min(k0 + m + win, nb)):
                c = b["close"][k]
                if not done_l and c > hi:
                    side[k] = 1
                    stop[k] = (c - lo_) if p["stop"] == "range" else 1.5 * cx["atr"][k]
                    done_l = True
                    break
                if not done_s and c < lo_:
                    side[k] = -1
                    stop[k] = (hi - c) if p["stop"] == "range" else 1.5 * cx["atr"][k]
                    done_s = True
                    break
    return side, stop


def f_sweep(b: dict, p: dict, cx: dict) -> tuple[np.ndarray, np.ndarray]:
    L = p["n"]
    sl, sh = _prev_roll(b["low"], L, "min"), _prev_roll(b["high"], L, "max")
    c, h, lo = b["close"], b["high"], b["low"]
    a = cx["atr"]
    ok = np.ones(len(c), bool)
    if p["vol"]:
        ok = b["volume"] > p["vol"] * _prev_roll(b["volume"], 20, "mean")
    long_ = ok & (lo < sl) & (c > sl)
    short = ok & (h > sh) & (c < sh)
    both = long_ & short
    long_, short = long_ & ~both, short & ~both
    side = np.where(long_, 1, np.where(short, -1, 0)).astype(np.int8)
    stop = np.where(side == 1, c - lo + 0.1 * a, np.where(side == -1, h - c + 0.1 * a, np.nan))
    return side, stop


FAMILIES: dict[str, tuple[Callable, list[dict]]] = {
    "breakout_volume": (f_breakout, [{"n": 20, "k": 1.5}, {"n": 20, "k": 2.5}, {"n": 50, "k": 1.5}, {"n": 50, "k": 2.5}]),
    "trend_pullback": (f_pullback, [{"fast": 9, "slow": 21, "m": 1.0}, {"fast": 9, "slow": 21, "m": 2.0},
                                    {"fast": 20, "slow": 50, "m": 1.0}, {"fast": 20, "slow": 50, "m": 2.0}]),
    "momentum_burst": (f_momentum, [{"n": 3, "z": 2.0}, {"n": 3, "z": 3.0}, {"n": 6, "z": 2.0}, {"n": 6, "z": 3.0}]),
    "meanrev_lowvol": (f_meanrev, [{"k": 2.0, "q": 0.3}, {"k": 2.0, "q": 0.5}, {"k": 2.5, "q": 0.3}, {"k": 2.5, "q": 0.5}]),
    "session_breakout": (f_session, [{"bars": 2, "stop": "range"}, {"bars": 2, "stop": "atr"},
                                     {"bars": 4, "stop": "range"}, {"bars": 4, "stop": "atr"}]),
    "liquidity_sweep": (f_sweep, [{"n": 20, "vol": 0}, {"n": 20, "vol": 1.5}, {"n": 50, "vol": 0}, {"n": 50, "vol": 1.5}]),
}


def configs() -> list[dict]:
    out = []
    for tf in TFS:
        for fam, (_, plist) in FAMILIES.items():
            for pi, p in enumerate(plist):
                for T in TIME_STOPS:
                    out.append({"id": f"{tf}m|{fam}|p{pi}|T{T}", "tf": tf, "family": fam, "pi": pi, "params": p, "T": T})
    return out


# ================================================================================================ simulator (1m walk)
# Leg types: 0 = take-profit limit (maker), 1 = stop (taker + stop slippage), 2 = time exit (taker + slippage).

@njit(cache=True)
def simulate(o, h, lo, c, valid, entry_min, side, sig_px, sd, tp1_r, tp2_r, tmax, limit_mode, window):
    ns = entry_min.shape[0]
    n = o.shape[0]
    taken = np.zeros(ns, np.bool_)
    e_idx = np.full(ns, -1, np.int64)
    e_px = np.zeros(ns)
    x1 = np.zeros(ns)
    x2 = np.zeros(ns)
    t1 = np.zeros(ns, np.int8)
    t2 = np.zeros(ns, np.int8)
    i1 = np.zeros(ns, np.int64)
    i2 = np.zeros(ns, np.int64)
    busy = -1
    for k in range(ns):
        e = entry_min[k]
        if e <= busy or e >= n:
            continue
        s = side[k]
        P = sig_px[k]
        d = sd[k]
        j = -1
        E = 0.0
        for jj in range(e, min(e + window, n)):
            if not valid[jj]:
                continue
            if limit_mode:
                if (s == 1 and lo[jj] < P) or (s == -1 and h[jj] > P):
                    j = jj
                    E = P
                    break
            else:
                j = jj
                E = o[jj]
                break
        if j < 0:
            continue
        stp = E - s * d
        tp1 = E + s * tp1_r * d
        tp2 = E + s * tp2_r * d
        hit1 = False
        done = False
        end = min(j + tmax, n) - 1
        for i in range(j, end + 1):
            if not valid[i]:
                continue
            fill_bar = limit_mode and i == j
            # stop first
            if (s == 1 and lo[i] <= stp) or (s == -1 and h[i] >= stp):
                if fill_bar:
                    px = stp                             # filled inside this bar: the open came before the fill
                elif s == 1:
                    px = min(o[i], stp)
                else:
                    px = max(o[i], stp)
                if not hit1:
                    x1[k] = px
                    t1[k] = 1
                    i1[k] = i
                x2[k] = px
                t2[k] = 1
                i2[k] = i
                done = True
                break
            if fill_bar:
                continue                                 # targets only after the fill bar for limit entries
            if not hit1 and ((s == 1 and h[i] > tp1) or (s == -1 and lo[i] < tp1)):
                hit1 = True
                x1[k] = tp1
                t1[k] = 0
                i1[k] = i
                stp = E                                  # break-even
                if (s == 1 and lo[i] <= E) or (s == -1 and h[i] >= E):
                    x2[k] = E                            # pessimistic: the BE touch comes after TP1
                    t2[k] = 1
                    i2[k] = i
                    done = True
                    break
            if hit1 and ((s == 1 and h[i] > tp2) or (s == -1 and lo[i] < tp2)):
                x2[k] = tp2
                t2[k] = 0
                i2[k] = i
                done = True
                break
        if not done:
            if not hit1:
                x1[k] = c[end]
                t1[k] = 2
                i1[k] = end
            x2[k] = c[end]
            t2[k] = 2
            i2[k] = end
        taken[k] = True
        e_idx[k] = j
        e_px[k] = E
        busy = i2[k]
    return taken, e_idx, e_px, x1, t1, i1, x2, t2, i2


def run_sim(g: dict, b: dict, side: np.ndarray, stop: np.ndarray, mask: np.ndarray, T: int, limit: bool) -> pd.DataFrame:
    """Simulate the signals on bars where mask & side != 0; returns one row per trade (raw prices, no costs)."""
    sel = np.nonzero(mask & (side != 0))[0]
    if len(sel) == 0:
        return pd.DataFrame()
    em = b["entry_min"][sel]
    s = side[sel].astype(np.int64)
    P = b["close"][sel]
    d = stop[sel]
    r = simulate(g["open"], g["high"], g["low"], g["close"], g["valid"], em, s, P, d, TP1_R, TP2_R,
                 int(T * b["tf"]), bool(limit), ENTRY_WINDOW)
    taken, e_idx, e_px, x1, t1, i1, x2, t2, i2 = r
    if not taken.any():
        return pd.DataFrame()
    t = taken
    fc = g["fund_cum"]
    j, a1, a2 = e_idx[t], i1[t], i2[t]
    df = pd.DataFrame({
        "bar": sel[t], "side": s[t], "sig_min": em[t], "e_min": j, "E": e_px[t], "sd": d[t],
        "x1": x1[t], "t1": t1[t], "m1": a1, "x2": x2[t], "t2": t2[t], "m2": a2,
        "fund": 0.5 * (fc[a1 + 1] - fc[j]) + 0.5 * (fc[a2 + 1] - fc[j]),
        "limit": limit,
    })
    return df


def apply_costs(df: pd.DataFrame, fees: dict) -> pd.DataFrame:
    """Gross / net returns in % of notional and in R (1R = stop distance)."""
    if df.empty:
        return df
    out = df.copy()
    s, E = out["side"].to_numpy(float), out["E"].to_numpy(float)
    gross = s * (0.5 * (out["x1"] - E) + 0.5 * (out["x2"] - E)).to_numpy() / E
    entry_cost = np.where(out["limit"].to_numpy(bool), fees["maker"], fees["taker"] + fees["slip"])

    def leg(t):
        t = t.to_numpy()
        return np.where(t == 0, fees["maker"], np.where(t == 1, fees["taker"] + fees["slip_stop"], fees["taker"] + fees["slip"]))

    fund = s * out["fund"].to_numpy(float)
    cost = entry_cost + 0.5 * leg(out["t1"]) + 0.5 * leg(out["t2"]) + fund
    risk = out["sd"].to_numpy(float) / E
    out["gross_pct"] = gross
    out["cost_pct"] = cost
    out["net_pct"] = gross - cost
    out["gross_r"] = gross / risk
    out["cost_r"] = cost / risk
    out["net_r"] = (gross - cost) / risk
    return out


# ================================================================================================ statistics

def day_index(minutes: np.ndarray) -> np.ndarray:
    return (np.asarray(minutes) // 1440).astype(np.int64)


def block_boot(df: pd.DataFrame, col: str = "net_r", n_boot: int = BOOT, block: int = BLOCK_DAYS, seed: int = 7,
               day_range: tuple[int, int] | None = None) -> dict:
    """Moving-block bootstrap by calendar day of entry: mean per trade with 95 % CI and one-sided p(mean <= 0)."""
    if df is None or df.empty or len(df) < 5:
        return {"mean": float(df[col].mean()) if df is not None and len(df) else None, "ci95": None, "p_le0": None}
    days = df["day"].to_numpy()
    lo_d, hi_d = day_range if day_range else (int(days.min()), int(days.max()))
    D = hi_d - lo_d + 1
    days = np.clip(days, lo_d, hi_d)
    sums = np.bincount(days - lo_d, weights=df[col].to_numpy(float), minlength=D)[:D]
    cnts = np.bincount(days - lo_d, minlength=D)[:D].astype(float)
    rng = np.random.default_rng(seed)
    nb = int(math.ceil(D / block))
    starts = rng.integers(0, D, size=(n_boot, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n_boot, -1)[:, :D] % D
    bs, bc = sums[idx].sum(axis=1), cnts[idx].sum(axis=1)
    means = np.where(bc > 0, bs / np.maximum(bc, 1), 0.0)
    return {"mean": float(df[col].mean()), "ci95": [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))],
            "p_le0": float((means <= 0).mean())}


def max_dd(r: np.ndarray) -> float:
    if len(r) == 0:
        return 0.0
    cum = np.cumsum(r)
    peak = np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]
    return float((peak - cum).max())


def summary(df: pd.DataFrame, days: float | None = None, boot: bool = True, day_range=None) -> dict:
    if df is None or df.empty:
        return {"trades": 0}
    d = df.sort_values("m2")
    nr, gr = d["net_r"].to_numpy(), d["gross_r"].to_numpy()
    wins, losses = nr[nr > 0], nr[nr <= 0]
    gp = float(d.loc[d["gross_r"] > 0, "gross_r"].sum())
    out = {
        "trades": int(len(d)),
        "trades_per_day": round(len(d) / days, 2) if days else None,
        "win_rate": round(float((nr > 0).mean()), 4),
        "tp1_rate": round(float((d["t1"] == 0).mean()), 4),
        "gross_r": round(float(gr.mean()), 4),
        "net_r": round(float(nr.mean()), 4),
        "net_r_total": round(float(nr.sum()), 1),
        "gross_pct": round(float(d["gross_pct"].mean() * 100), 4),
        "net_pct": round(float(d["net_pct"].mean() * 100), 4),
        "cost_r": round(float(d["cost_r"].mean()), 4),
        "cost_pct": round(float(d["cost_pct"].mean() * 100), 4),
        "avg_win_r": round(float(wins.mean()), 3) if len(wins) else None,
        "avg_loss_r": round(float(losses.mean()), 3) if len(losses) else None,
        "profit_factor": round(float(wins.sum() / -losses.sum()), 3) if len(losses) and losses.sum() < 0 else None,
        "max_dd_r": round(max_dd(nr), 1),
        "avg_hold_min": round(float((d["m2"] - d["e_min"]).mean()), 1),
        "avg_risk_pct": round(float((d["sd"] / d["E"]).mean() * 100), 3),
        "fee_share_of_gross_profit": round(float(d["cost_r"].sum() / gp), 3) if gp > 0 else None,
        "long_share": round(float((d["side"] == 1).mean()), 3),
    }
    if boot:
        b = block_boot(d, day_range=day_range)
        out["net_r_ci95"] = [round(x, 4) for x in b["ci95"]] if b["ci95"] else None
        out["p_net_le0"] = round(b["p_le0"], 4) if b["p_le0"] is not None else None
    return out


def white_rc(mat: np.ndarray, n_boot: int = BOOT, block: int = BLOCK_DAYS, seed: int = 11) -> dict:
    """White's reality check on a days x configs matrix of daily net R: p-value of the best config's mean."""
    if mat.size == 0:
        return {}
    D = mat.shape[0]
    means = mat.mean(axis=0)
    stat = math.sqrt(D) * means.max()
    dm = mat - means
    rng = np.random.default_rng(seed)
    nb = int(math.ceil(D / block))
    cnt = 0
    for _ in range(n_boot // 2):
        starts = rng.integers(0, D, nb)
        idx = ((starts[:, None] + np.arange(block)[None, :]).ravel()[:D]) % D
        if math.sqrt(D) * dm[idx].mean(axis=0).max() >= stat:
            cnt += 1
    return {"best_daily_mean_r": float(means.max()), "p_value": cnt / (n_boot // 2), "configs": int(mat.shape[1]),
            "days": int(D)}


def deflated_sharpe(sr_best: float, srs: np.ndarray, t: int, skew: float, kurt: float) -> dict:
    nd = NormalDist()
    srs = srs[np.isfinite(srs)]
    N = max(len(srs), 2)
    v = float(np.var(srs)) if len(srs) > 1 else 0.0
    g = 0.5772156649
    sr0 = math.sqrt(v) * ((1 - g) * nd.inv_cdf(1 - 1 / N) + g * nd.inv_cdf(1 - 1 / (N * math.e)))
    den = 1 - skew * sr_best + (kurt - 1) / 4 * sr_best ** 2
    z = (sr_best - sr0) * math.sqrt(max(t - 1, 1)) / math.sqrt(max(den, 1e-9))
    return {"sr_per_trade": sr_best, "sr0_expected_max_under_null": sr0, "trials": N, "trades": t,
            "deflated_sharpe_prob": nd.cdf(z)}


# ================================================================================================ the study

class Study:
    def __init__(self, cache: Path, months: int, budget: float):
        self.cache, self.n_months, self.budget = cache, months, budget
        self.grids: dict[str, dict] = {}
        self.info: dict[str, Any] = {}
        self.trades: dict[str, list[pd.DataFrame]] = {}
        self.sig_cache: dict[tuple, tuple] = {}
        self.bars: dict[tuple, dict] = {}
        self.ctx: dict[tuple, dict] = {}

    def over_budget(self) -> bool:
        return time.time() - T_START > self.budget

    # ---- data
    def load(self) -> None:
        months = month_list(self.n_months)
        self.info["months"] = months
        for sym in COINS:
            k, f, info = load_coin(sym, months, self.cache)
            if k is None or len(k) < 50_000:
                log(f"{sym}: no futures archive data, skipped")
                self.info.setdefault("skipped", []).append(sym)
                continue
            self.grids[sym] = to_grid(k, f)
            g = self.grids[sym]
            info.update({"minutes": int(g["n"]), "valid_share": round(float(g["valid"].mean()), 5),
                         "first": datetime.fromtimestamp(g["t0"] / 1000, timezone.utc).isoformat()})
            self.info.setdefault("coins", {})[sym] = info
            log(f"{sym}: {info}")
        if "BTCUSDT" not in self.grids:
            raise RuntimeError("BTCUSDT data missing")

    # ---- per-minute context: 1h trend / volatility / BTC regime (closed 1h bars only)
    def hourly(self) -> None:
        self.h = {}
        for sym, g in self.grids.items():
            b = aggregate(g, 60)
            e = ema(b["close"], 50)
            slope = (e - np.roll(e, 3)) / e
            slope[:53] = 0.0
            a = atr(b) / b["close"]
            med = pd.Series(a).rolling(720, min_periods=100).median().to_numpy()
            self.h[sym] = {"slope": slope, "vol_hi": a > med, "qv": b["close"] * b["volume"]}

    def split_bounds(self, sym: str) -> tuple[int, int, int]:
        n = self.grids[sym]["n"]
        return int(n * SPLITS[0]), int(n * SPLITS[1]), n

    def context(self, sym: str, tf: int) -> dict:
        key = (sym, tf)
        if key in self.ctx:
            return self.ctx[key]
        b = self.bars[key]
        em = b["entry_min"]
        hi = em // 60 - 1                                # last 1h bar CLOSED at the signal time
        hs = self.h[sym]
        hb = self.h["BTCUSDT"]
        ok = hi >= 0
        hic = np.clip(hi, 0, len(hs["slope"]) - 1)
        # BTC: shift onto this coin's minute grid
        off = (self.grids[sym]["t0"] - self.grids["BTCUSDT"]["t0"]) // 3_600_000
        hb_i = np.clip(hi + off, 0, len(hb["slope"]) - 1)
        btc_slope = hb["slope"][hb_i]
        t_end = self.split_bounds(sym)[0]
        q = np.nanpercentile(btc_slope[(em < t_end) & ok], [33.3, 66.7]) if ((em < t_end) & ok).any() else [0, 0]
        regime = np.where(btc_slope > q[1], "up", np.where(btc_slope < q[0], "down", "sideways"))
        coin_slope = np.where(ok, hs["slope"][hic], 0.0)
        vol = np.where(ok, hs["vol_hi"][hic], False)
        hour = (em % 1440) // 60
        cx = {"atr": atr(b), "btc_regime": regime, "trend_sign": np.sign(coin_slope).astype(int),
              "vol": np.where(vol, "high", "low"), "hour": hour}
        self.ctx[key] = cx
        return cx

    def signals(self, sym: str, tf: int, fam: str, pi: int) -> tuple[np.ndarray, np.ndarray]:
        key = (sym, tf, fam, pi)
        if key not in self.sig_cache:
            b = self.bars[(sym, tf)]
            cx = self.context(sym, tf)
            fn, plist = FAMILIES[fam]
            side, stop = fn(b, plist[pi], cx)
            side = side.copy()
            bad = ~b["complete"] | ~np.isfinite(stop) | (stop <= 0)
            side[bad] = 0
            self.sig_cache[key] = (side, np.where(np.isfinite(stop), stop, 0.0))
        return self.sig_cache[key]

    def cost_ok(self, sym: str, tf: int, stop: np.ndarray, mult: float = COST_MULT) -> np.ndarray:
        return stop / self.bars[(sym, tf)]["close"] >= mult * RT_COST

    def annotate(self, df: pd.DataFrame, sym: str, tf: int, cfg: dict) -> pd.DataFrame:
        if df.empty:
            return df
        cx = self.context(sym, tf)
        t1, t2, _ = self.split_bounds(sym)
        bar = df["bar"].to_numpy()
        df["coin"] = sym
        df["tf"] = tf
        df["family"] = cfg["family"]
        df["cfg"] = cfg["id"]
        df["split"] = np.where(df["sig_min"] < t1, "tune", np.where(df["sig_min"] < t2, "select", "holdout"))
        df["btc_regime"] = cx["btc_regime"][bar]
        df["vol"] = cx["vol"][bar]
        df["with_trend"] = cx["trend_sign"][bar] == df["side"].to_numpy()
        df["hour"] = cx["hour"][bar]
        df["day"] = ((self.grids[sym]["t0"] // 60_000 + df["e_min"].to_numpy()) // 1440).astype(np.int64)
        df["abs_min"] = self.grids[sym]["t0"] // 60_000 + df["e_min"].to_numpy()
        df["abs_exit"] = self.grids[sym]["t0"] // 60_000 + df["m2"].to_numpy()
        return df

    def run_cfg(self, cfg: dict, coins=None, limit=False, mult=COST_MULT, extra=None, fees=FEES_BASE) -> pd.DataFrame:
        parts = []
        for sym in (coins or self.grids):
            tf = cfg["tf"]
            side, stop = self.signals(sym, tf, cfg["family"], cfg["pi"])
            mask = self.cost_ok(sym, tf, stop, mult)
            if extra is not None:
                mask = mask & extra(sym, tf, side)
            df = run_sim(self.grids[sym], self.bars[(sym, tf)], side, stop, mask, cfg["T"], limit)
            if not df.empty:
                parts.append(self.annotate(df, sym, tf, cfg))
        if not parts:
            return pd.DataFrame()
        return apply_costs(pd.concat(parts, ignore_index=True), fees)

    # ---- the pipeline
    def run(self) -> dict:
        res: dict[str, Any] = {"data": self.info}
        self.load()
        self.hourly()
        btc = self.grids["BTCUSDT"]
        t1, t2, n = self.split_bounds("BTCUSDT")
        day0 = btc["t0"] // 86_400_000
        self.day_ranges = {"tune": (day0, day0 + t1 // 1440), "select": (day0 + t1 // 1440, day0 + t2 // 1440),
                           "holdout": (day0 + t2 // 1440, day0 + n // 1440)}
        self.days = {k: max(v[1] - v[0], 1) for k, v in self.day_ranges.items()}
        res["periods"] = {k: {"from": str(date.fromordinal(date(1970, 1, 1).toordinal() + int(v[0]))),
                              "to": str(date.fromordinal(date(1970, 1, 1).toordinal() + int(v[1]))),
                              "days": self.days[k]} for k, v in self.day_ranges.items()}
        for sym, g in self.grids.items():
            for tf in TFS:
                self.bars[(sym, tf)] = aggregate(g, tf)

        # 1) every configuration, market entries, full history (holdout rows are not looked at until step 4)
        cfgs = configs()
        res["configs_tried"] = len(cfgs)
        all_tr: dict[str, pd.DataFrame] = {}
        for i, cfg in enumerate(cfgs):
            if self.over_budget():
                log(f"time budget reached after {i} configs")
                res["budget_hit"] = True
                break
            all_tr[cfg["id"]] = self.run_cfg(cfg)
            if i % 12 == 11:
                log(f"configs {i + 1}/{len(cfgs)} done")
        self.all_tr = all_tr

        def part(df, sp):
            return df[df["split"] == sp] if not df.empty else df

        # 2) tune: best parameters per family x timeframe (pooled coins, net R per trade, min trades)
        tune_tab = []
        for cid, df in all_tr.items():
            tdf = part(df, "tune")
            tune_tab.append({"cfg": cid, "trades": int(len(tdf)),
                             "net_r": float(tdf["net_r"].mean()) if len(tdf) else None,
                             "gross_r": float(tdf["gross_r"].mean()) if len(tdf) else None})
        tt = pd.DataFrame(tune_tab)
        chosen = {}
        for tf in TFS:
            for fam in FAMILIES:
                rows = tt[tt["cfg"].str.startswith(f"{tf}m|{fam}|")]
                okr = rows[rows["trades"] >= MIN_TUNE_TRADES].dropna(subset=["net_r"])
                pick = okr if len(okr) else rows.dropna(subset=["net_r"])
                if len(pick):
                    chosen[(tf, fam)] = pick.sort_values("net_r", ascending=False).iloc[0]["cfg"]
        res["tune"] = {"all_configs": tt.round(4).to_dict("records"), "chosen": {f"{k[0]}m|{k[1]}": v for k, v in chosen.items()}}

        # multiple-testing view of tuning: White's reality check + deflated Sharpe on the best tune config
        d0, d1 = self.day_ranges["tune"]
        mat = np.zeros((d1 - d0, len(all_tr)))
        srs, keys = [], list(all_tr)
        for j, cid in enumerate(keys):
            tdf = part(all_tr[cid], "tune")
            if len(tdf):
                dd = np.clip(tdf["day"].to_numpy() - d0, 0, d1 - d0 - 1)
                mat[:, j] = np.bincount(dd, weights=tdf["net_r"].to_numpy(), minlength=d1 - d0)
                srs.append(tdf["net_r"].mean() / (tdf["net_r"].std() or np.nan) if len(tdf) > 2 else np.nan)
            else:
                srs.append(np.nan)
        srs = np.array(srs, float)
        res["tune"]["white_reality_check"] = white_rc(mat)
        if np.isfinite(srs).any():
            jb = int(np.nanargmax(srs))
            tb = part(all_tr[keys[jb]], "tune")["net_r"]
            res["tune"]["deflated_sharpe_best"] = {"cfg": keys[jb], **deflated_sharpe(
                float(srs[jb]), srs, len(tb), float(tb.skew()), float(tb.kurt() + 3))}

        # 3) select: Bonferroni over the family x timeframe candidates
        n_cand = len(chosen)
        thr = ALPHA / max(n_cand, 1)
        sel_tab, selected = {}, []
        for (tf, fam), cid in chosen.items():
            sdf = part(all_tr[cid], "select")
            s = summary(sdf, self.days["select"], day_range=self.day_ranges["select"])
            p = s.get("p_net_le0")
            s["passes"] = bool(s.get("trades", 0) >= 30 and s.get("net_r", -1) > 0 and p is not None and p < thr)
            s["passes_uncorrected"] = bool(s.get("trades", 0) >= 30 and s.get("net_r", -1) > 0 and p is not None and p < ALPHA)
            sel_tab[cid] = s
            if s["passes"]:
                selected.append(cid)
        res["select"] = {"bonferroni_alpha": thr, "candidates": n_cand, "results": sel_tab, "selected": selected}
        log(f"selected: {selected}")

        # 4) holdout (once): the tuned candidates; 'selected' flags the ones that passed
        H = "holdout"
        hd, hr = self.days[H], self.day_ranges[H]
        hold = {}
        for (tf, fam), cid in chosen.items():
            s = summary(part(all_tr[cid], H), hd, day_range=hr)
            s["selected"] = cid in selected
            s["bonferroni_sig"] = bool(s.get("p_net_le0") is not None and s["p_net_le0"] < thr and s.get("net_r", -1) > 0)
            hold[cid] = s
        res["holdout"] = {"per_candidate": hold}
        chosen_ids = list(chosen.values())
        pooled = pd.concat([part(all_tr[c], H) for c in chosen_ids], ignore_index=True) if chosen_ids else pd.DataFrame()
        res["holdout"]["per_tf_all_candidates"] = {f"{tf}m": summary(pooled[pooled["tf"] == tf], hd, day_range=hr)
                                                   for tf in TFS if len(pooled)}
        sel_pool = pooled[pooled["cfg"].isin(selected)] if len(pooled) else pooled
        res["holdout"]["selected_pooled"] = summary(sel_pool, hd, day_range=hr) if len(sel_pool) else {"trades": 0}
        base = sel_pool if len(sel_pool) else pooled
        res["holdout"]["breakdowns_basis"] = "selected configs" if len(sel_pool) else \
            "no config passed selection: breakdowns of all 18 tuned candidates (diagnostic)"
        res["holdout"]["breakdowns"] = self.breakdowns(base, hd, hr)
        res["holdout"]["portfolio_max3"] = self.portfolio(base, hd, hr)
        res["holdout"]["gross_vs_net_pooled"] = {"gross_r": round(float(base["gross_r"].mean()), 4) if len(base) else None,
                                                 "net_r": round(float(base["net_r"].mean()), 4) if len(base) else None}
        log("holdout evaluated")

        # 5) baselines on the holdout (same stops / targets / costs rule)
        if not self.over_budget():
            res["baselines"] = self.baselines(pooled)
        # 6) levers
        if not self.over_budget():
            res["levers"] = self.levers(chosen, selected)
        res["verdict"] = self.verdict(res)
        return res

    def breakdowns(self, df: pd.DataFrame, hd, hr) -> dict:
        if df.empty:
            return {}
        sess = pd.cut(df["hour"], [-1, 6, 12, 20, 23], labels=["asia_00_07", "europe_07_13", "us_13_21", "late_21_24"])
        out = {}
        for name, key in (("tf", df["tf"].astype(str) + "m"), ("coin", df["coin"]), ("family", df["family"]),
                          ("side", np.where(df["side"] == 1, "long", "short")), ("btc_regime", df["btc_regime"]),
                          ("volatility", df["vol"]), ("with_1h_trend", np.where(df["with_trend"], "with", "against")),
                          ("session", sess.astype(str))):
            out[name] = {str(k): summary(g, hd, boot=(name in ("tf", "family")), day_range=hr)
                         for k, g in df.groupby(np.asarray(key))}
        return out

    def portfolio(self, df: pd.DataFrame, hd, hr) -> dict:
        """All coins of a config together, at most 3 open positions (first come first served by entry time)."""
        if df.empty:
            return {}
        out = {}
        for cid, g in list(df.groupby("cfg")) + [("ALL_TOGETHER", df)]:
            g = g.sort_values("abs_min")
            open_ex: list[int] = []
            keep = np.zeros(len(g), bool)
            for i, (a, x) in enumerate(zip(g["abs_min"].to_numpy(), g["abs_exit"].to_numpy())):
                open_ex = [e for e in open_ex if e >= a]
                if len(open_ex) < 3:
                    keep[i] = True
                    open_ex.append(x)
            out[cid] = summary(g[keep], hd, day_range=hr)
        return out

    def baselines(self, pooled: pd.DataFrame) -> dict:
        out = {}
        rng = np.random.default_rng(5)
        for tf in TFS:
            nsig = len(pooled[pooled["tf"] == tf]) if len(pooled) else 0
            for name in ("random_entry", "always_long", "always_short"):
                parts = []
                for sym in self.grids:
                    b = self.bars[(sym, tf)]
                    cx = self.context(sym, tf)
                    nb = len(b["close"])
                    stop = 1.5 * cx["atr"]
                    if name == "random_entry":
                        prob = min(1.0, max(nsig, 50) / (len(self.grids) * nb * (1 - SPLITS[1])))   # same rate as the candidates
                        side = np.where(rng.random(nb) < prob, np.where(rng.random(nb) < 0.5, 1, -1), 0).astype(np.int8)
                    else:
                        side = np.full(nb, 1 if name == "always_long" else -1, np.int8)
                    side[~b["complete"]] = 0
                    side[:50] = 0
                    mask = self.cost_ok(sym, tf, stop) & (b["entry_min"] >= self.split_bounds(sym)[1])
                    df = run_sim(self.grids[sym], b, side, stop, mask, 30, False)
                    if not df.empty:
                        parts.append(self.annotate(df, sym, tf, {"family": name, "id": f"{tf}m|{name}"}))
                df = apply_costs(pd.concat(parts, ignore_index=True), FEES_BASE) if parts else pd.DataFrame()
                out[f"{tf}m|{name}"] = summary(df, self.days["holdout"], day_range=self.day_ranges["holdout"])
        log("baselines done")
        return out

    def levers(self, chosen: dict, selected: list) -> dict:
        """Each lever on the tuned candidates of every timeframe: net R per trade, select and holdout, vs the base."""
        cfgs = {c["id"]: c for c in configs()}
        ids = list(chosen.values())
        base = {cid: self.all_tr[cid] for cid in ids}
        # liquid coins by tune quote volume
        qv = {}
        for sym, g in self.grids.items():
            t1 = self.split_bounds(sym)[0]
            qv[sym] = float(np.sum(g["close"][:t1] * g["volume"][:t1]))
        liquid = sorted(qv, key=qv.get, reverse=True)[:LIQUID_N]
        # favourable regimes: btc_regime x vol buckets with positive net R on tune+select, per timeframe
        fav = {}
        for tf in TFS:
            ts = pd.concat([d[(d["tf"] == tf) & (d["split"] != "holdout")] for d in base.values() if len(d)],
                           ignore_index=True)
            if len(ts):
                m = ts.groupby(["btc_regime", "vol"])["net_r"].agg(["mean", "count"])
                fav[tf] = [f"{a}|{b}" for (a, b), r in m.iterrows() if r["mean"] > 0 and r["count"] >= 30]
            else:
                fav[tf] = []

        def with_trend(sym, tf, side):
            return self.context(sym, tf)["trend_sign"] == side

        def favourable(sym, tf, side):
            cx = self.context(sym, tf)
            key = np.char.add(np.char.add(cx["btc_regime"].astype(str), "|"), cx["vol"].astype(str))
            return np.isin(key, fav[tf])

        def eu_us(sym, tf, side):
            h = self.context(sym, tf)["hour"]
            return (h >= 7) & (h < 21)

        variants = {
            "base_market_taker": lambda c: base[c["id"]],
            "limit_entry_maker": lambda c: self.run_cfg(c, limit=True),
            "tp1_ge_5x_cost": lambda c: self.run_cfg(c, mult=5.0),
            "with_1h_trend_only": lambda c: self.run_cfg(c, extra=with_trend),
            "favourable_regimes_only": lambda c: self.run_cfg(c, extra=favourable),
            "liquid_coins_only": lambda c: base[c["id"]][base[c["id"]]["coin"].isin(liquid)] if len(base[c["id"]]) else base[c["id"]],
            "eu_us_session_only": lambda c: self.run_cfg(c, extra=eu_us),
            "vip_fees": lambda c: apply_costs(base[c["id"]], FEES_VIP) if len(base[c["id"]]) else base[c["id"]],
            "zero_costs_reference": lambda c: apply_costs(base[c["id"]], FEES_ZERO) if len(base[c["id"]]) else base[c["id"]],
        }
        out: dict[str, Any] = {"liquid_coins": liquid, "favourable_regimes": {f"{k}m": v for k, v in fav.items()},
                               "note": "levers are fixed before the holdout; 'combined' uses only levers that improved "
                                       "net R on the SELECT period (zero_costs is a reference, never combined)"}
        res_v: dict[str, dict] = {}
        frames: dict[str, pd.DataFrame] = {}
        for vname, fn in variants.items():
            if self.over_budget():
                out["budget_hit"] = True
                break
            dfs = [fn(cfgs[c]) for c in ids]
            df = pd.concat([d for d in dfs if len(d)], ignore_index=True) if any(len(d) for d in dfs) else pd.DataFrame()
            frames[vname] = df
            row = {}
            for sp in ("select", "holdout"):
                p = df[df["split"] == sp] if len(df) else df
                row[sp] = {"all": summary(p, self.days[sp], boot=(sp == "holdout"), day_range=self.day_ranges[sp])}
                for tf in TFS:
                    q = p[p["tf"] == tf] if len(p) else p
                    row[sp][f"{tf}m"] = summary(q, self.days[sp], boot=False)
                if selected and len(p):
                    row[sp]["selected"] = summary(p[p["cfg"].isin(selected)], self.days[sp], boot=False)
            res_v[vname] = row
            log(f"lever {vname} done")
        out["variants"] = res_v
        # combined: levers that helped on select (net R per trade, all timeframes)
        b_sel = res_v.get("base_market_taker", {}).get("select", {}).get("all", {}).get("net_r")
        good = [v for v, r in res_v.items() if v not in ("base_market_taker", "zero_costs_reference", "vip_fees")
                and b_sel is not None and (r["select"]["all"].get("net_r") or -9) > b_sel and r["select"]["all"].get("trades", 0) >= 100]
        out["combined_levers"] = good
        if good and not self.over_budget():
            filt = [f for name, f in (("with_1h_trend_only", with_trend), ("favourable_regimes_only", favourable),
                                       ("eu_us_session_only", eu_us)) if name in good]

            def extra(sym, tf, side):
                m = np.ones(len(side), bool)
                for f in filt:
                    m &= f(sym, tf, side)
                return m
            coins = liquid if "liquid_coins_only" in good else None
            dfs = [self.run_cfg(cfgs[c], coins=coins, limit="limit_entry_maker" in good,
                                mult=5.0 if "tp1_ge_5x_cost" in good else COST_MULT, extra=extra if filt else None)
                   for c in ids]
            df = pd.concat([d for d in dfs if len(d)], ignore_index=True) if any(len(d) for d in dfs) else pd.DataFrame()
            comb = {}
            for sp in ("select", "holdout"):
                p = df[df["split"] == sp] if len(df) else df
                comb[sp] = {"all": summary(p, self.days[sp], day_range=self.day_ranges[sp]),
                            **{f"{tf}m": summary(p[p["tf"] == tf] if len(p) else p, self.days[sp], day_range=self.day_ranges[sp]) for tf in TFS}}
                if len(p):
                    comb[sp]["vip_fees"] = summary(apply_costs(p, FEES_VIP), self.days[sp], day_range=self.day_ranges[sp])
                    comb[sp]["by_family"] = {f: summary(g, self.days[sp], boot=False) for f, g in p.groupby("family")}
            out["combined"] = comb
        return out

    def verdict(self, res: dict) -> dict:
        sel = res.get("select", {}).get("selected", [])
        hold = res.get("holdout", {}).get("per_candidate", {})
        sig = [c for c, s in hold.items() if s.get("bonferroni_sig")]
        pos = [c for c, s in hold.items() if (s.get("net_r") or -1) > 0 and s.get("trades", 0) >= 30]
        pos_sel = [c for c in sel if (hold.get(c, {}).get("net_r") or -1) > 0]
        conf = [c for c in sel if hold.get(c, {}).get("net_r_ci95") and hold[c]["net_r_ci95"][0] > 0]
        txt = []
        if not sel:
            txt.append("No family/timeframe passed the selection test (positive net R with Bonferroni-corrected confidence).")
        else:
            txt.append(f"{len(sel)} configuration(s) passed selection; {len(pos_sel)} stayed positive on the holdout, "
                       f"{len(conf)} with a 95% CI above zero.")
        txt.append(f"Holdout: {len(pos)} of {len(hold)} tuned candidates net-positive, {len(sig)} significant after Bonferroni.")
        return {"selected": sel, "selected_positive_on_holdout": pos_sel, "selected_ci_above_zero": conf,
                "holdout_significant_any": sig, "holdout_positive_any": pos, "text": " ".join(txt),
                "beats_costs_with_confidence": bool(conf)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", default="data/scalp_cache")
    ap.add_argument("--out", default="results/scalp.json")
    ap.add_argument("--budget", type=float, default=6600.0)
    ap.add_argument("--months", type=int, default=12)
    a = ap.parse_args(argv)
    doc: dict[str, Any] = {"ok": False, "command": "scalp", "started": datetime.now(timezone.utc).isoformat(),
                           "numba": HAVE_NUMBA,
                           "assumptions": {"taker": TAKER, "maker": MAKER, "slippage": SLIP, "stop_slippage": SLIP_STOP,
                                           "vip": {"taker": VIP_TAKER, "maker": VIP_MAKER},
                                           "round_trip_cost_ref": RT_COST, "costs_rule": f"1R >= {COST_MULT} x {RT_COST}",
                                           "tp1_r": TP1_R, "tp2_r": TP2_R, "tp_split": "50/50, stop to break-even after TP1",
                                           "time_stops_bars": TIME_STOPS, "entry_window_min": ENTRY_WINDOW,
                                           "splits": {"tune": "0-60%", "select": "60-80%", "holdout": "80-100%"},
                                           "funding": "archive rate in force, pro-rata per minute (fallback 0.01%/8h)"}}
    try:
        st = Study(Path(a.cache), a.months, a.budget)
        doc["result"] = st.run()
        doc["ok"] = True
    except Exception as e:                               # noqa: BLE001 - the JSON must say what went wrong
        doc["error"] = f"{type(e).__name__}: {e}"
        doc["traceback"] = traceback.format_exc()[-4000:]
    doc["elapsed_s"] = round(time.time() - T_START, 1)
    doc["progress"] = LOG[-300:]
    txt = json.dumps(doc, default=lambda o: o.item() if hasattr(o, "item") else str(o), indent=1)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(txt)
    print(json.dumps({"ok": doc["ok"], "error": doc.get("error"), "elapsed_s": doc["elapsed_s"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
