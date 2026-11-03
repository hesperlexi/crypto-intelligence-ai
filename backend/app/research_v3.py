"""`python -m app.research aiv3 --mode dev|final`: AI research v3 (Nov 2026, owner-approved items 1-3). READ-ONLY.

1. Harness = the LIVE record's rules. Candidate calls come from the models' walk-forward out-of-sample predictions
   (bundle["oos"], as research_engine) on every coin / timeframe with an active model. Each call is simulated exactly as
   the live record would store and follow it: the analysis dict goes through `tracking._plan` (v2.13 honest entry: a
   market call is entered at the price when it is published - here the open of the 15m candle in which the engine
   publishes, DECISION_LATENCY_MS after the bar closes - targets rebuilt in R from it; BUY ON PULLBACK / confirm /
   pullback rules stay PENDING limits; the live nightly entry rule of the timeframe), the 15m leverage policy
   (`futures.signal_leverage`, `analysis.leverage_gate`), then `tracking.evaluate_signal` on the 15m candles opened
   after publication (gap-aware stop fills, trade-through limit fills, break-even after TP1, TP1 after TP2, the call's
   time limit `tracking.horizon_for`, expiry at the last close) and `tracking.net_fields` (0.15 % round trip + the stored
   hourly funding of the coin on the open share, default 0.01 %/8 h). Targets are the live ones: TP1 1R, TP2 / TP3 picked
   by `engine/setup.build_setup`'s rule (max historical first-passage p x R, capped by S/R) from base rates of the bars
   known at the decision (stop distance snapped to 0.05 ATR). R = net % / risk % of the recorded entry.
   One call at a time per coin / timeframe + the re-entry cooldown and cap (`tracking.entry_gate`), news guard.
2. Validation. Per timeframe one calendar cut: the last HOLDOUT_SHARE of the out-of-sample span is the final holdout,
   evaluated only in `--mode final` (dev mode never computes a holdout number). Development rows: decided before the cut
   AND closed before it (purge). Every learned / selected piece is fitted with purged + embargoed expanding walk-forward
   folds inside development (embargo = the trade horizon); thresholds and calibration use out-of-fold predictions only;
   final models are refitted on all development rows. Every configuration tried is registered with its development
   result. On the holdout: block bootstrap by coin x week, White's reality check + Hansen's SPA over the family of new
   configurations, Holm-adjusted p-values, against zero (costs) and against the current pipeline.
3. Meta-labelling (item 1): per timeframe, pooled over coins (coin id categorical), HistGradientBoosting on everything
   known at the decision (model probabilities, technical / regime / multi-timeframe state, BTC context, relative
   strength, volatility, plan geometry, base rates, funding and crowd data). Labels: the NET outcome under the live rules
   (win = net > 0; regressor on net R). Used (a) as a filter of the pipeline's calls and (b) as the direction / entry
   decision maker on a regular grid of bars.
4. Honest confidence (item 2): isotonic calibration of P(net win) on out-of-fold predictions; reliability on the holdout
   next to the live "confidence" (next-bar hit rate).
5. Stricter promotion (item 3): trade_filter v1, runner, target model (retrained per coin / timeframe on development
   data with their own exams), trade_filter2 (pooled, plus its enable rate on permuted labels), the live entry rule vs
   the v2.5 rule, and the stored deriv / htf gate tests (Holm / Benjamini-Hochberg across all series).
"""
from __future__ import annotations

import logging
import os
import time
import zlib
from typing import Any

import numpy as np
import pandas as pd

from .config import ENGINE_VERSION, MODEL_TIMEFRAMES, MTF_TIMEFRAMES, settings
from .data.base import tf_ms
from .db import dumps
from .redact import error_text

log = logging.getLogger("research.v3")

HOLDOUT_SHARE = 0.20
CV_FOLDS = 5
DECISION_LATENCY_MS = 60_000           # the engine publishes ~1 min after the bar closes (5-minute ticks)
STRIDE = {"15m": 4, "1h": 2, "4h": 2, "12h": 1, "1d": 1, "3d": 1}   # grid of bars for baselines / direction maker
MAX_GRID_ROWS = 1600                   # per series (grid rows are thinned evenly above this)
G_STEP = 0.05                          # base-rate tables: stop distance snapped to 0.05 ATR
BASE_HORIZON = 30                      # engine/setup.build_setup default horizon of the base rates
TP2_RANGE = (1.25, 1.5, 1.75, 2.0)
TP3_RANGE = (2.0, 2.25, 2.5, 2.75, 3.0)
FILTER_GRID = (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)    # keep fractions tried on development (out-of-fold)
DIR_GRID = (0.05, 0.1, 0.2, 0.3, 0.5)                 # share of grid rows the direction maker may act on
MIN_DEV_TRADES = 40
P15 = 900_000


# ---- small stubs: live code paths that read the database, fed from memory ------------------------------------------------

class _RuleDB:
    """`series_nightly.entry_rule` reads `entry_policy1|TF`: answer with the rule being replayed."""

    def __init__(self, mode: str, k: float):
        self.v = {"chosen": f"{mode}:{k}", "at": int(time.time() * 1000)}

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self.v if key.startswith("entry_policy1|") else default


class FundingDB:
    """`tracking.funding_pct` reads stored hourly funding (derivs funding_1h) with one query per call: served from a
    preloaded array instead (same rows, same arithmetic)."""

    def __init__(self, ts: np.ndarray | None = None, value: np.ndarray | None = None):
        self.ts = np.asarray(ts if ts is not None else [], np.int64)
        self.value = np.asarray(value if value is not None else [], float)
        o = np.argsort(self.ts, kind="stable")
        self.ts, self.value = self.ts[o], self.value[o]

    @classmethod
    def load(cls, db: Any, symbol: str) -> "FundingDB":
        try:
            rows = db.query("SELECT ts, value FROM derivs WHERE symbol = ? AND kind = 'funding_1h' ORDER BY ts", (symbol,))
        except Exception:
            rows = []
        return cls(np.array([int(r["ts"]) for r in rows], np.int64), np.array([float(r["value"]) for r in rows], float))

    def query(self, sql: str, args: tuple) -> list[dict[str, Any]]:
        _, lo, hi = args
        i, j = np.searchsorted(self.ts, lo, side="right"), np.searchsorted(self.ts, hi, side="right")
        return [{"ts": int(t), "value": float(v)} for t, v in zip(self.ts[i:j], self.value[i:j])]


# ---- live targets: base rates known at the decision -------------------------------------------------------------------------

class BaseRates:
    """`ml.distribution.first_passage_base_rate` for every entry bar at once, per side and stop distance (in ATR):
    the best favourable excursion reached before the stop (stop first inside a bar) within BASE_HORIZON bars. A decision
    at frame position p only uses entries i <= p - BASE_HORIZON (whose whole horizon had closed by then)."""

    def __init__(self, high, low, close, atr, regime, horizon: int = BASE_HORIZON):
        self.h, self.l, self.c = (np.asarray(x, float) for x in (high, low, close))
        self.a = np.asarray(atr, float)
        self.H = horizon
        self.n = len(self.c)
        reg = np.sign(np.nan_to_num(np.asarray(regime, float)))
        self.ok = np.isfinite(self.a) & (self.a > 0)
        self.cond = {1: reg == 1, -1: reg == -1}
        self._tab: dict[tuple[int, float], tuple[np.ndarray, np.ndarray]] = {}

    def table(self, side: int, g: float) -> tuple[np.ndarray, np.ndarray] | None:
        key = (side, round(float(g), 6))
        if key in self._tab:
            return self._tab[key]
        N = self.n - self.H
        if N <= 0:
            return None
        e, a = self.c[:N], np.where(self.ok[:N], self.a[:N], np.nan)
        mfe = np.zeros(N)
        alive = np.ones(N, bool)
        stopped = np.zeros(N, bool)
        with np.errstate(invalid="ignore"):
            for k in range(1, self.H + 1):
                hi, lo = self.h[k:k + N], self.l[k:k + N]
                adv, fav = ((e - lo) / a, (hi - e) / a) if side > 0 else ((hi - e) / a, (e - lo) / a)
                hit = alive & (adv >= g)
                stopped |= hit
                alive &= ~hit
                mfe = np.where(alive, np.maximum(mfe, np.nan_to_num(fav, nan=-np.inf)), mfe)
        self._tab[key] = (mfe, stopped)
        return self._tab[key]

    def rates(self, p: int, side: int, g: float, ups: np.ndarray) -> dict[str, Any]:
        """Probability of reaching each `ups` (in ATR) before the stop `g` ATR away, and of being stopped first, from
        the entries known at frame position p (same-direction regime first, all bars when fewer than 50)."""
        last = p + 1 - self.H                  # first_passage_base_rate on ind[:p+1]: entries idx < n - horizon
        tab = self.table(side, g)
        if tab is None or last <= 0:
            return {"p": None, "stopped": None, "n": 0}
        mfe, stopped = tab[0][:last], tab[1][:last]
        ok = self.ok[:last]
        sel = ok & self.cond[side][:last]
        if sel.sum() < 50:
            sel = ok
        if sel.sum() < 50:
            return {"p": None, "stopped": None, "n": int(sel.sum())}
        m, s = mfe[sel], stopped[sel]
        reach = m[:, None] >= np.asarray(ups, float)[None, :]
        return {"p": reach.mean(axis=0), "stopped": (s[:, None] & ~reach).mean(axis=0), "n": int(sel.sum())}


def walls_of(zones: dict[str, list[dict]], side: int, ideal: float, dist: float) -> list[float]:
    ahead = zones["resistance"] if side > 0 else zones["support"]
    w = sorted(side * ((z["low"] if side > 0 else z["high"]) - ideal) / dist for z in ahead)
    return [x for x in w if x > 1.0]


def pick_targets(br: BaseRates, p: int, side: int, dist: float, atr: float, walls: list[float],
                 lift: dict[float, float] | None = None, snap: bool = True) -> dict[str, Any]:
    """TP2 / TP3 multiples as engine/setup.build_setup picks them, and its base-rate validity check."""
    g = dist / atr
    if snap:
        g = max(G_STEP, round(g / G_STEP) * G_STEP)
    mults = sorted(set((1.0,) + TP2_RANGE + TP3_RANGE))
    rr = br.rates(p, side, g, np.array(mults) * g)
    prob = {m: (None if rr["p"] is None else float(rr["p"][i])) for i, m in enumerate(mults)}
    stop1 = None if rr["stopped"] is None else float(rr["stopped"][mults.index(1.0)])

    def best(options, floor):
        cands = [m for m in options if m >= floor - 1e-9]
        wall = next((w for w in walls if w > floor), None)
        if wall is not None:
            capped = [m for m in cands if m <= wall + 1e-9]
            cands = capped or cands[:1]
        b = None
        for m in cands:
            pr = prob[m]
            k = (lift or {}).get(float(m))
            if k is not None and pr is not None:
                pr = float(min(0.99, pr * k))
            sc = (pr or 0.0) * m
            if b is None or sc > b[0] + 1e-9:
                b = (sc, m)
        return b[1]
    m2 = best(TP2_RANGE, TP2_RANGE[0])
    m3 = best(TP3_RANGE, max(TP3_RANGE[0], m2 + 0.25))
    p1 = prob[1.0]
    exp_r = (p1 - stop1) if p1 is not None else None
    return {"m2": float(m2), "m3": float(m3), "p1": p1, "stop1": stop1, "exp_r": exp_r, "n": rr["n"],
            "valid": not (exp_r is not None and exp_r < -0.15)}


# ---- the harness: one call under the live record's rules ----------------------------------------------------------------

def simulate_call(*, symbol: str, tf: str, side: int, decision: str, created: int, price: float, last_close: float,
                  ideal: float, stop: float, atr: float, mults: tuple[float, float, float], mode: str, k: float,
                  p15: pd.DataFrame | None, own: pd.DataFrame | None, now: int, funding: Any = None,
                  grade: str | None = None, runner_rr: float | None = None, horizon: int | None = None) -> dict[str, Any]:
    """Record one call exactly as `tracking.record_call` would and follow it with `tracking.evaluate_signal`.
    `price` = the live price at publication (`a["price"]`), `last_close` = the decision bar's close. Returns
    {'recorded': False, 'reason'} | {'recorded': True, 'status', 'filled', 'closed_ts', 'r_net', ...}."""
    from .engine.futures import signal_leverage
    from .services import tracking as T
    H = int(horizon or T.horizon_for(tf))
    dist0 = abs(ideal - stop)
    setup = {"side_int": side, "ideal_entry": ideal, "stop": stop, "atr": atr, "valid": True,
             "risk_reward": float(sum(w * m for w, m in zip((0.5, 0.25, 0.25), mults))),
             "targets": [{"price": float(ideal + side * m * dist0), "rr": float(m)} for m in mults]}
    a = {"decision": decision, "price": float(price), "last_close": float(last_close), "timeframe": tf, "setup": setup,
         "symbol": symbol, "grade": grade}
    pl = T._plan(a, _RuleDB(mode, k))
    if pl.get("entry") is None:
        return {"recorded": False, "reason": pl.get("skip") or "no entry"}
    if signal_leverage(pl["entry"], pl["stop"], symbol=symbol, grade=grade, timeframe=tf) is None:
        return {"recorded": False, "reason": "stop too wide for 10x"}
    run = None
    if runner_rr:
        run = T._runner_for({"on": True, "rr": float(runner_rr), "target": float(ideal + side * runner_rr * dist0)}, pl)
    filled = pl["fill_status"] == "FILLED"
    s = {"id": "sim", "created_at": int(created), "symbol": symbol, "timeframe": tf, "side": int(pl["side"]),
         "entry": float(pl["entry"]), "stop": float(pl["stop"]), "tp1": pl["tps"][0], "tp2": pl["tps"][1],
         "tp3": pl["tps"][2], "atr": pl["atr"], "decision": decision, "fill_status": pl["fill_status"],
         "filled_at": int(created) if filled else None,
         "payload": dumps({"horizon_bars": H, "entry_rule": pl["entry_rule"], "manage": {"managed": False},
                           "runner": run})}
    step = tf_ms(tf)
    end = int(created) + step * H
    w15 = None
    if p15 is not None and len(p15):
        ts = p15["ts"].to_numpy(np.int64)
        i, j = np.searchsorted(ts, created), np.searchsorted(ts, end)
        if i < len(ts) and int(ts[i]) <= int(created) + P15:      # 15m candles from the start of the window
            w15 = p15.iloc[i:j]
    wown = None
    if w15 is None and own is not None and len(own):
        ts = own["ts"].to_numpy(np.int64)
        i = np.searchsorted(ts, created)
        wown = own.iloc[i:i + H]
    res = T.evaluate_signal(s, w15, wown, int(now), H, {"managed": False}, None)
    st = res.get("status", "OPEN")
    base = {"recorded": True, "fill_status": pl["fill_status"], "entry": float(pl["entry"]), "stop": float(pl["stop"]),
            "entry_mode": (pl.get("entry_rule") or {}).get("mode") or "limit"}
    if st == "VOID":
        return {**base, "status": "VOID", "filled": False, "closed_ts": int(res.get("closed_at") or end), "finished": True}
    if st == "NOT_FILLED":
        return {**base, "status": st, "filled": False, "closed_ts": int(res["closed_at"]), "finished": True}
    if st == "OPEN":
        return {**base, "status": "OPEN", "filled": res.get("fill_status", pl["fill_status"]) == "FILLED",
                "closed_ts": None, "finished": False}
    entry = float(res.get("entry") or pl["entry"])
    gross = float(res["return_pct"])
    nf = T.net_fields(funding, symbol, int(pl["side"]), gross, res.get("exposure"))
    risk = abs(entry - float(pl["stop"])) / entry * 100
    fill_ts = int(res.get("filled_at") or s["filled_at"] or created)
    return {**base, "status": st, "filled": True, "finished": True, "closed_ts": int(res["closed_at"]),
            "entry": entry, "gross_pct": gross, "net_pct": nf["return_net_pct"], "funding_pct": nf["funding_pct"],
            "cost_pct": nf["cost_pct"], "risk_pct": risk, "r_net": nf["return_net_pct"] / risk if risk else 0.0,
            "r_gross": gross / risk if risk else 0.0, "tp1": int(res.get("tp1_hit") or 0), "exit": res.get("exit_reason"),
            "hold_h": (int(res["closed_at"]) + P15 - fill_ts) / 3_600_000}


# ---- one call at a time (tracking.entry_gate) ---------------------------------------------------------------------------

def take_live(ts: np.ndarray, closed: np.ndarray, side: np.ndarray, exit_reason: np.ndarray, step: int,
              cooldown: int | None = None, window: int | None = None, rmax: int | None = None) -> np.ndarray:
    """Indices (time order) of the calls the record keeps: nothing while a call is open or pending (until its exit
    candle has closed), the cooldown after the last close, at most `rmax` same-direction re-entries after a stop exit
    within `window` bars. `closed`: exit candle open time (NaN / inf for a call still open at the end of the data)."""
    cd = (settings.reentry_cooldown_bars if cooldown is None else cooldown) * step
    win = (settings.reentry_window_bars if window is None else window) * step
    rmax = settings.reentry_max if rmax is None else rmax
    out: list[int] = []
    busy = -np.inf
    last_close = None
    hist: list[tuple[int, float, int, str]] = []          # created, closed, side, exit reason
    for i in np.argsort(ts, kind="stable"):
        t = int(ts[i])
        if t < busy:
            continue
        if last_close is not None and np.isfinite(last_close) and t < last_close + P15 + cd:
            continue
        sd = int(side[i])
        exits = [h for h in hist if h[2] == sd and np.isfinite(h[1]) and h[1] >= t - win and h[3] in ("stop", "giveback")]
        if exits:
            first = min(exits, key=lambda h: h[1])
            n = sum(1 for h in hist if h[2] == sd and h[0] > first[1])
            if n >= rmax:
                continue
        out.append(int(i))
        c = float(closed[i]) if closed[i] is not None and np.isfinite(closed[i]) else np.inf
        busy = c + P15
        last_close = c
        hist.append((t, c, sd, str(exit_reason[i])))
    return np.array(out, int)


# ---- per series: candidate calls -------------------------------------------------------------------------------------------

def stored_entry_rule(db: Any, tf: str) -> tuple[str, float]:
    """The live entry rule of a timeframe as stored by the nightly job (ENTRY_RULES on), ignoring its 3-day expiry."""
    if not settings.entry_rules:
        return "old", 0.0
    try:
        e = db.get_setting(f"entry_policy1|{tf}", None) or {}
        mode, k = (e.get("chosen") or "old:0.0").split(":")
        return mode, float(k)
    except Exception:
        return "old", 0.0


def _ctx_features(ctx, d, j: int, side: int, pl: dict, tg: dict, decision: str) -> dict[str, float]:
    P = ctx.P[j]
    sm = float(d["side_model"][j])
    conf = float(d["confidence"][j]) if np.isfinite(d["confidence"][j]) else np.nan
    f = {"p_down": P[0], "p_neu": P[1], "p_up": P[2], "p_side": P[2] if side > 0 else P[0], "margin": abs(P[2] - P[0]),
         "model_agrees": float(sm == side), "conf_side": conf if sm == side else (1 - conf if np.isfinite(conf) else np.nan),
         "side": float(side), "tech_side": side * ctx.tech[j], "regime_side": side * ctx.regime_score[j],
         "btc_regime_side": side * ctx.btc_regime[j], "btc_tech_side": side * ctx.btc_tech[j],
         "vol_state": ctx.vol_state[j], "atr_pct": ctx.atr[j] / ctx.close[j] * 100 if ctx.close[j] else np.nan,
         "stop_atr": pl["dist"] / ctx.atr[j] if ctx.atr[j] else np.nan, "risk_pct": pl["dist"] / pl["ideal"] * 100,
         "extended": float(pl["extended"]), "pending": float(decision == "BUY ON PULLBACK"),
         "tp2_r": tg["m2"], "tp3_r": tg["m3"], "base_p1": tg["p1"] if tg["p1"] is not None else np.nan,
         "base_stop1": tg["stop1"] if tg["stop1"] is not None else np.nan,
         "grade_code": {"A": 2.0, "B": 1.0}.get(str(d["grade"][j]), 0.0) if d["trade"][j] and d["side"][j] == side else 0.0,
         "pipe_side": float(bool(d["trade"][j]) and int(d["side"][j]) == side)}
    for c in ("sc_trend", "sc_momentum", "sc_volume", "sc_structure", "sc_volatility"):
        f[f"{c}_side"] = side * ctx.comps[c][j]
    for t in MTF_TIMEFRAMES:
        f[f"mtf_{t}_side"] = side * ctx.mtf_dir[t][j] if t in ctx.mtf_dir else np.nan
    return {k: float(v) if v is not None else np.nan for k, v in f.items()}


SIGNED_X = ("ret_1", "ret_5", "ret_20", "d_ema21", "d_ema50", "d_ema200", "macd_hist_n", "di_diff", "btc_ret_1", "btc_ret_5",
            "btc_tech", "rel_strength_20", "fund_1h", "fund_8h", "fund_z", "prem", "prem_24h", "ls_top", "ls_acct",
            "taker_24h", "oi_chg_1d", "struct_trend", "htf_regime")


def build_series(rt: Any, symbol: str, tf: str, cfg: dict[str, Any], cache: dict) -> dict[str, Any]:
    """Every candidate call of one coin / timeframe (the pipeline's calls and both sides of a regular grid of bars),
    each simulated with the live rules, with its decision-time features; plus the per-series retraining of the old
    AI pieces on development data (holdout calls scored)."""
    from . import research_engine as RE
    from .features.dataset import InsufficientData, make_features
    from .ml import series_policy as SP, series_sim as S, trainer, trade_filter2 as TF2
    from .services import analysis as A, tracking as T
    t0 = time.time()
    bundle = trainer.load_bundle(symbol, tf, rt.db)
    if bundle is None:
        return {"key": f"{symbol} {tf}", "skip": "no active model"}
    frames = cache.get(symbol)
    if frames is None:
        frames = cache[symbol] = RE._series_frames(rt, symbol, tf)
    if tf not in frames:
        return {"key": f"{symbol} {tf}", "skip": "no frame"}
    btc = frames.get(tf) if symbol == "BTC/USDT" else None
    if btc is None and symbol != "BTC/USDT":
        try:
            btc = cache.setdefault("__btc__", {}).get(tf) or rt.frame("BTC/USDT", tf)
            cache["__btc__"][tf] = btc
        except InsufficientData:
            btc = None
    ctx = SP.build_context(symbol, tf, bundle, frames, btc)
    if ctx is None or ctx.n < 200:
        return {"key": f"{symbol} {tf}", "skip": "too few out-of-sample bars"}
    fr = frames[tf]
    ind = fr.ind
    step = tf_ms(tf)
    cut = int(cfg["cuts"][tf])
    H = T.horizon_for(tf)
    p15 = rt.candles(symbol, "15m")
    own = rt.candles(symbol, tf)
    now = max(int(p15["ts"].iloc[-1]) + P15 if len(p15) else 0, int(own["ts"].iloc[-1]) + step if len(own) else 0)
    funding = FundingDB.load(rt.db, symbol)
    mode, k = cfg["entry_rules"].get(tf, ("old", 0.0))
    news = cfg.get("news")
    deriv = rt.deriv_frame(symbol)
    X = make_features(fr, btc if symbol != "BTC/USDT" else None, None, deriv)
    xcols = list(X.columns)
    Xv = X.to_numpy(np.float32)
    signed_idx = [xcols.index(c) for c in SIGNED_X if c in xcols]
    br = BaseRates(ind["high"], ind["low"], ind["close"], ind["atr"], ind["regime_score"])
    ref = (ctx.ts + 2 * step) <= cut                     # next-bar outcome known before the cut
    d = SP.decide(ctx, ref)
    rtc = SP.round_trip()
    p15_ts = p15["ts"].to_numpy(np.int64) if len(p15) else np.zeros(0, np.int64)
    p15_open = p15["open"].to_numpy(float) if len(p15) else np.zeros(0)
    own_ts, own_open = own["ts"].to_numpy(np.int64), own["open"].to_numpy(float)
    ema21, ema50 = ind["ema_21"].to_numpy(float), ind["ema_50"].to_numpy(float)
    rng = np.random.default_rng(zlib.crc32(f"{symbol}|{tf}".encode()))
    rand_side = np.where(rng.random(ctx.n) < 0.5, 1, -1)
    usable = ~np.isin(d["reason"], ("insufficient", "extreme_vol")) & np.isfinite(ctx.atr) & (ctx.atr > 0)
    grid = np.flatnonzero(usable & (np.arange(ctx.n) % STRIDE.get(tf, 1) == 0))
    if len(grid) > MAX_GRID_ROWS:
        grid = grid[np.linspace(0, len(grid) - 1, MAX_GRID_ROWS).round().astype(int)]
    pipe = np.flatnonzero(d["trade"])
    rows = np.union1d(grid, pipe)
    in_grid = np.zeros(ctx.n, bool)
    in_grid[grid] = True
    recs: list[dict[str, Any]] = []
    feats: list[np.ndarray] = []
    fnames: list[str] | None = None
    tf2: dict[int, np.ndarray] = {}
    skipped = {"plan": 0, "costs": 0, "base_rate": 0, "leverage": 0, "news": 0, "not_recorded": 0, "void": 0}
    for j in rows:
        dts = int(ctx.decision_ts[j])
        if news is not None and news(dts):
            skipped["news"] += 1
            continue
        created = dts + DECISION_LATENCY_MS
        i15 = np.searchsorted(p15_ts, created, side="right") - 1
        if 0 <= i15 < len(p15_ts) and int(p15_ts[i15]) + P15 > created:
            price = float(p15_open[i15])                  # price when the engine publishes (~1 min after the close)
        else:
            io = np.searchsorted(own_ts, dts)
            price = float(own_open[io]) if io < len(own_ts) else float(ctx.close[j])
        pos = int(ctx.rows[j])
        zones = ctx.zones(int(j))
        for side in (1, -1):
            is_pipe = bool(d["trade"][j]) and int(d["side"][j]) == side
            if not is_pipe and not in_grid[j]:
                continue
            pl = d["plan"][j] if is_pipe else S.plan(side, float(ctx.close[j]), float(ctx.atr[j]), float(ctx.ema21[j]),
                                                     zones, float(ctx.last_sl[j]), float(ctx.last_sh[j]))
            if not pl or not pl.get("valid"):
                skipped["plan"] += 1
                continue
            if pl["dist"] / pl["ideal"] < SP.COST_MULT * rtc:
                skipped["costs"] += 1
                continue
            tg = pick_targets(br, pos, side, pl["dist"], float(ctx.atr[j]), walls_of(zones, side, pl["ideal"], pl["dist"]))
            if not tg["valid"]:
                skipped["base_rate"] += 1
                continue
            decision = "BUY ON PULLBACK" if side > 0 and pl["extended"] else ("BUY" if side > 0 else "SELL")
            grade = str(d["grade"][j]) if is_pipe else "A"
            if A.leverage_gate({"valid": True, "stop": pl["stop"], "ideal_entry": pl["ideal"]}, price, symbol, grade, tf):
                skipped["leverage"] += 1
                continue
            kw = dict(symbol=symbol, tf=tf, side=side, decision=decision, created=created, price=price,
                      last_close=float(ctx.close[j]), ideal=pl["ideal"], stop=pl["stop"], atr=float(ctx.atr[j]),
                      mults=(1.0, tg["m2"], tg["m3"]), p15=p15, own=own, now=now, funding=funding, grade=grade, horizon=H)
            sim = simulate_call(mode=mode, k=k, **kw)
            if not sim.get("recorded"):
                skipped["not_recorded"] += 1
                continue
            if sim["status"] == "VOID":
                skipped["void"] += 1
                continue
            rec = {"j": int(j), "pos": pos, "ts": dts, "side": side, "pipe": is_pipe, "grid": bool(in_grid[j]),
                   "grade": str(d["grade"][j]) if is_pipe else "", "decision": decision,
                   "conf": float(d["confidence"][j]) if np.isfinite(d["confidence"][j]) else np.nan,
                   "model_side": int(d["side_model"][j]), "trend_side": int(np.sign(ema21[pos] - ema50[pos])) if
                   np.isfinite(ema21[pos] - ema50[pos]) else 0, "rand_side": int(rand_side[j]), **_sim_fields(sim)}
            if is_pipe and (mode, k) != ("old", 0.0):        # item 5: the v2.5 entry rule on the same call
                rec["old_rule"] = _sim_fields(simulate_call(mode="old", k=0.0, **kw))
            if is_pipe:
                tf2[len(recs)] = TF2.features(ctx, d, int(j))
                rec["_kw"] = kw                               # kept in the worker only (old-piece re-simulation)
                rec["_tg"] = (pl, zones)
            cf = _ctx_features(ctx, d, int(j), side, pl, tg, decision)
            xr = Xv[pos].astype(float).copy()
            if signed_idx:
                xr[signed_idx] = xr[signed_idx] * side
            if fnames is None:
                fnames = list(cf) + [f"x_{c}" for c in xcols]
            feats.append(np.concatenate([np.array(list(cf.values()), float), xr]).astype(np.float32))
            recs.append(rec)
    out = {"key": f"{symbol} {tf}", "symbol": symbol, "tf": tf, "n_oos": int(ctx.n), "span": [int(ctx.ts[0]), int(ctx.ts[-1])],
           "now": now, "entry_rule": f"{mode}:{k}", "skipped": skipped, "fnames": fnames or [],
           "F": np.vstack(feats) if feats else np.zeros((0, 0), np.float32),
           "pipe_calls": int(len(pipe)), "grid_rows": int(len(grid)),
           "bundle_addons": {n: bool((bundle.get(n) or {}).get("enabled")) for n in ("trade_filter", "runner_model", "target_model")},
           "uses_htf": bundle.get("uses_htf"), "uses_btc": bool(bundle.get("uses_btc")),
           "edge_confirmed": bool(ctx.edge_confirmed)}
    try:
        out["old_pieces"] = old_pieces(bundle, ctx, fr, frames, btc, deriv, recs, cut, step, (mode, k), br)
    except Exception as exc:                            # an old piece must never break the series
        out["old_pieces"] = {"error": error_text(exc, 200)}
    for r in recs:
        r.pop("_kw", None)
        r.pop("_tg", None)
    out["recs"] = recs
    out["tf2"] = {i: v.astype(np.float32) for i, v in tf2.items()}
    out["seconds"] = round(time.time() - t0, 1)
    return out


def _sim_fields(sim: dict[str, Any]) -> dict[str, Any]:
    if not sim.get("recorded"):
        return {"recorded": False}
    return {"recorded": True, "status": sim["status"], "filled": bool(sim["filled"]), "finished": bool(sim["finished"]),
            "closed": float(sim["closed_ts"]) if sim.get("closed_ts") is not None else np.inf,
            "r_net": sim.get("r_net", np.nan), "r_gross": sim.get("r_gross", np.nan), "net_pct": sim.get("net_pct", np.nan),
            "funding_pct": sim.get("funding_pct", np.nan), "risk_pct": sim.get("risk_pct", np.nan),
            "tp1": sim.get("tp1", 0), "exit": sim.get("exit") or "", "hold_h": sim.get("hold_h", np.nan),
            "entry_mode": sim.get("entry_mode")}


def old_pieces(bundle, ctx, fr, frames, btc, deriv, recs, cut, step, rule: tuple[str, float],
               br: BaseRates) -> dict[str, Any]:
    """trade_filter v1, runner and target model retrained on this series' DEVELOPMENT out-of-sample rows only (their
    own A/B/C exams decide whether they switch on), then applied to the holdout pipeline calls (re-simulated with the
    live harness when they change the exits or targets)."""
    from .features.dataset import make_features
    from .ml import runner_model, target_model, trade_filter, trainer
    names = bundle.get("feature_names") or []
    htf = frames.get(bundle["uses_htf"]) if bundle.get("uses_htf") else None
    Xb = make_features(fr, btc if bundle.get("uses_btc") and ctx.symbol != "BTC/USDT" else None, htf, deriv)
    missing = [c for c in names if c not in Xb.columns]
    if missing or not names:
        return {"error": f"model features unavailable ({len(missing)} missing)"}
    Xb = Xb[names].to_numpy(float)
    ind = fr.ind
    hi, lo, cl, at = (ind[c].to_numpy(float) for c in ("high", "low", "close", "atr"))
    dev = (ctx.ts + (trade_filter.HORIZON + 1) * step) <= cut      # their 30-bar labels end before the cut
    rows = ctx.rows[dev]
    Xd, Pd = Xb[rows], ctx.P[dev]
    cost = trainer._cost()
    out: dict[str, Any] = {}
    pieces = {}
    for name, fn in (("trade_filter", lambda: trade_filter.train(Xd, Pd, rows, hi, lo, cl, at, cost)),
                     ("runner_model", lambda: runner_model.train(Xd, Pd, rows, hi, lo, cl, at, cost)),
                     ("target_model", lambda: target_model.train(Xd, Pd, rows, hi, lo, cl, at))):
        try:
            pieces[name] = fn()
        except Exception as exc:
            pieces[name] = {"enabled": False, "reason": error_text(exc, 120)}
        out[name] = {"enabled_dev": bool(pieces[name].get("enabled")), "reason": pieces[name].get("reason"),
                     "exam": pieces[name].get("exam")}
    hold = [i for i, r in enumerate(recs) if r["pipe"] and r["ts"] >= cut and r.get("recorded")]
    per: dict[int, dict[str, Any]] = {}
    for i in hold:
        r = recs[i]
        x = Xb[r["pos"]]
        P = ctx.P[r["j"]]
        probs = {"down": float(P[0]), "neutral": float(P[1]), "up": float(P[2])}
        e: dict[str, Any] = {}
        tv = trade_filter.score(pieces["trade_filter"], x, probs)
        if tv:
            e["v1_keep"] = bool((tv["p_long"] if r["side"] > 0 else tv["p_short"]) >= tv["threshold"])
        rv = runner_model.score(pieces["runner_model"], x, probs)
        run_rr = None
        if rv and (rv["p_long"] if r["side"] > 0 else rv["p_short"]) >= rv["threshold"]:
            run_rr = float(rv.get("run_r") or 4.0)
            e["runner"] = _sim_fields(simulate_call(runner_rr=run_rr, mode=rule[0], k=rule[1], **r["_kw"]))
        lf = target_model.lifts(pieces["target_model"], x, probs)
        if lf:
            pl, zones = r["_tg"]
            side = r["side"]
            tg = pick_targets(br, r["pos"], side, pl["dist"], float(ctx.atr[r["j"]]), walls_of(zones, side, pl["ideal"], pl["dist"]),
                              lift=lf["long" if side > 0 else "short"])
            kw = dict(r["_kw"])
            if (1.0, tg["m2"], tg["m3"]) != tuple(kw["mults"]):
                kw["mults"] = (1.0, tg["m2"], tg["m3"])
                e["target"] = _sim_fields(simulate_call(mode=rule[0], k=rule[1], **kw))
                if run_rr:
                    e["target_runner"] = _sim_fields(simulate_call(mode=rule[0], k=rule[1], runner_rr=run_rr, **kw))
        if e:
            per[i] = e
    out["holdout_calls"] = per
    return out


# ---- per timeframe: strategies, meta-model, statistics -------------------------------------------------------------------

def _frame(series: list[dict[str, Any]]) -> tuple[pd.DataFrame, np.ndarray, list[str]]:
    names: list[str] = []
    for s in series:
        for n in s.get("fnames") or []:
            if n not in names:
                names.append(n)
    rows, mats = [], []
    for s in series:
        recs = s.get("recs") or []
        if not recs:
            continue
        F = s["F"]
        M = np.full((len(recs), len(names)), np.nan, np.float32)
        idx = [names.index(n) for n in s["fnames"]]
        M[:, idx] = F
        mats.append(M)
        op = (s.get("old_pieces") or {}).get("holdout_calls") or {}
        for i, r in enumerate(recs):
            rr = {k: v for k, v in r.items() if k not in ("old_rule",)}
            rr["symbol"], rr["key"] = s["symbol"], s["key"]
            orr = r.get("old_rule")
            rr["old_rule_r"] = orr.get("r_net", np.nan) if orr and orr.get("recorded") else np.nan
            rr["old_rule_filled"] = bool(orr.get("filled")) if orr and orr.get("recorded") else None
            rr["old_rule_closed"] = orr.get("closed", np.inf) if orr and orr.get("recorded") else np.inf
            rr["old_rule_exit"] = orr.get("exit", "") if orr and orr.get("recorded") else ""
            e = op.get(i) or op.get(str(i)) or {}
            rr["v1_keep"] = e.get("v1_keep")
            for nm in ("runner", "target", "target_runner"):
                x = e.get(nm)
                rr[f"{nm}_r"] = x.get("r_net", np.nan) if x and x.get("recorded") and x.get("filled") else np.nan
                rr[f"{nm}_closed"] = x.get("closed", np.inf) if x and x.get("recorded") else np.inf
                rr[f"{nm}_exit"] = x.get("exit", "") if x else ""
                rr[f"{nm}_ok"] = bool(x and x.get("recorded"))
            tf2 = s.get("tf2") or {}
            v = tf2.get(i, tf2.get(str(i)))
            rr["_tf2"] = v
            rows.append(rr)
    df = pd.DataFrame(rows)
    F = np.vstack(mats) if mats else np.zeros((0, len(names)), np.float32)
    return df, F, names


def trades_of(df: pd.DataFrame, mask: np.ndarray, step: int, r_col: str = "r_net", closed_col: str = "closed",
              exit_col: str = "exit", filled_col: str = "filled") -> pd.DataFrame:
    """The calls the record would keep among `mask` (per series one at a time), returning only filled, finished
    trades (with their R)."""
    keep = []
    sub = df[mask]
    for _, g in sub.groupby("key", sort=False):
        idx = take_live(g["ts"].to_numpy(np.int64), g[closed_col].to_numpy(float), g["side"].to_numpy(int),
                        g[exit_col].to_numpy(object), step)
        keep.extend(g.index[idx])
    t = df.loc[keep]
    t = t[t[filled_col].astype(bool) & np.isfinite(t[r_col].to_numpy(float))]
    return t.sort_values("ts")


def summarize(t: pd.DataFrame, months: float, watch: set[str], r_col: str = "r_net", boot: bool = True) -> dict[str, Any]:
    from .ml import meta_v3 as MV, series_sim as S
    r = t[r_col].to_numpy(float) if len(t) else np.zeros(0)
    st = S.stats(list(r))
    out = {"n": st["n"], "win_rate_net": st["win_rate"], "avg_r": st["expectancy_r"], "profit_factor": st["profit_factor"],
           "max_dd_r": st["max_drawdown_r"], "total_r": st["total_r"],
           "trades_per_month": round(len(r) / months, 2) if months > 0 else None,
           "trades_per_month_watchlist": round(int(t["symbol"].isin(watch).sum()) / months, 2) if months > 0 and len(t) else 0.0,
           "tp1_rate": float(t["tp1"].mean()) if len(t) else None,
           "avg_net_pct": float(t["net_pct"].mean()) if len(t) and "net_pct" in t and r_col == "r_net" else None}
    if boot and len(r):
        b = MV.bootstrap_mean(r, MV.block_keys(t["symbol"], t["ts"]))
        out.update(ci95=b["ci95"], lb95=b["lb95"], p_le_0=b["p_le_0"], blocks=b.get("blocks"))
    return out


def _fit_predict(F, y, cat, Ftest, kind: str, seed: int = 0):
    from .ml import meta_v3 as MV
    cols = np.isfinite(F).any(axis=0)                  # a column empty in the training rows carries nothing (and breaks binning)
    m = (MV.make_classifier if kind == "clf" else MV.make_regressor)(cat[cols] if cat is not None else None, seed)
    m.fit(F[:, cols], y)
    T_ = Ftest[:, cols]
    return m.predict_proba(T_)[:, 1] if kind == "clf" else m.predict(T_), m


def evaluate_tf(tf: str, series: list[dict[str, Any]], cut: int, final: bool, watch: set[str], registry: list,
                cfg: dict[str, Any]) -> dict[str, Any]:
    from .ml import meta_v3 as MV, trade_filter2 as TF2
    from .services import analysis as A, tracking as T
    t0 = time.time()
    step = tf_ms(tf)
    H = T.horizon_for(tf)
    df, F, names = _frame(series)
    if df.empty:
        return {"error": "no candidate calls"}
    df = df.reset_index(drop=True)
    ok = df["recorded"].astype(bool).to_numpy()
    df, F = df[ok].reset_index(drop=True), F[ok]
    ts = df["ts"].to_numpy(np.int64)
    closed = df["closed"].to_numpy(float)
    finished_fill = df["filled"].astype(bool).to_numpy() & np.isfinite(df["r_net"].to_numpy(float))
    dev = (ts < cut) & (closed < cut)
    hold = ts >= cut
    end = int(max(s["now"] for s in series if "now" in s))
    dev_start = int(ts.min())
    months_dev = max((cut - dev_start) / (30.44 * 86_400_000), 1e-9)
    months_hold = max((end - cut) / (30.44 * 86_400_000), 1e-9)
    # coin id: categorical (stable codes over the whole run)
    codes = {s: i for i, s in enumerate(cfg["symbols"])}
    names = names + ["coin"]
    F = np.column_stack([F, df["symbol"].map(codes).fillna(len(codes)).to_numpy(np.float32)]).astype(np.float32)
    cat = np.zeros(len(names), bool)
    cat[-1] = True
    a_only = tf in A.A_ONLY_TFS
    pipe = df["pipe"].astype(bool).to_numpy()
    gradeA = (df["grade"] == "A").to_numpy()
    current = pipe & (gradeA if a_only else True)
    grid = df["grid"].astype(bool).to_numpy()
    side = df["side"].to_numpy(int)
    strategies: dict[str, np.ndarray] = {
        "current_core": current, "pipeline_ab": pipe,
        "baseline_random": grid & (side == df["rand_side"].to_numpy(int)),
        "baseline_trend_ema21_50": grid & (side == df["trend_side"].to_numpy(int)),
        "baseline_always_long": grid & (side == 1),
    }
    out: dict[str, Any] = {"cut": cut, "end": end, "horizon_bars": H, "a_only": a_only, "candidates": int(len(df)),
                           "dev_rows": int(dev.sum()), "holdout_rows": int(hold.sum()),
                           "months_dev": round(months_dev, 2), "months_holdout": round(months_hold, 2),
                           "series": len(series), "features": len(names)}

    def reg(name: str, params: dict[str, Any], dev_stats: dict[str, Any] | None):
        registry.append({"tf": tf, "config": name, "params": params, "dev": dev_stats})

    # ---- development: purged + embargoed walk-forward out-of-fold predictions -----------------------------------
    trn = dev & finished_fill
    yw = (df["r_net"].to_numpy(float) > 0).astype(int)
    yr = np.clip(df["r_net"].to_numpy(float), -2.0, 4.0)
    ti = np.flatnonzero(trn)
    folds = MV.purged_folds(ts[ti], closed[ti], CV_FOLDS, embargo_ms=H * step, min_train=300)
    oof_p = np.full(len(df), np.nan)
    oof_r = np.full(len(df), np.nan)
    dev_any = np.flatnonzero(dev)
    fold_info = []
    for fi, (tr, va) in enumerate(folds):
        tr_rows = ti[tr]
        lo_, hi_ = int(ts[ti[va]].min()), int(ts[ti[va]].max())
        va_rows = dev_any[(ts[dev_any] >= lo_) & (ts[dev_any] <= hi_)]     # incl. unfilled pendings (scored, not labelled)
        if len(np.unique(yw[tr_rows])) < 2:
            continue
        p, _ = _fit_predict(F[tr_rows], yw[tr_rows], cat, F[va_rows], "clf", fi)
        rr_, _ = _fit_predict(F[tr_rows], yr[tr_rows], cat, F[va_rows], "reg", fi)
        oof_p[va_rows], oof_r[va_rows] = p, rr_
        fold_info.append({"train": int(len(tr_rows)), "valid": int(len(va_rows)), "valid_from": lo_, "valid_to": hi_})
    out["folds"] = fold_info
    has_oof = np.isfinite(oof_p)
    cal = MV.Calibrator().fit(oof_p[has_oof & finished_fill], yw[has_oof & finished_fill])
    oof_pc = np.where(has_oof, cal(np.nan_to_num(oof_p)), np.nan)
    out["dev_calibration_oof"] = MV.reliability(oof_pc[has_oof & finished_fill], yw[has_oof & finished_fill])
    oof_mask = has_oof & dev

    def dev_eval(mask):
        t = trades_of(df, mask & oof_mask, step)
        return summarize(t, months_dev * (oof_mask.sum() / max(dev.sum(), 1)), watch)

    # baselines and the current pipeline on the same out-of-fold part of development (reference for the choices)
    dev_tables = {k: dev_eval(m) for k, m in strategies.items()}
    for k, m in strategies.items():
        reg(k, {"fixed": True}, dev_tables[k])
    # filter thresholds (calibrated P scale) chosen on out-of-fold development calls of the pipeline (grades A+B)
    pp = oof_pc[pipe & oof_mask]
    choices: dict[str, Any] = {}
    if len(pp) >= 50:
        t50 = float(np.nanquantile(pp, 0.5))
        choices["filter_q50"] = t50
        best, bscore = None, -np.inf
        for keep in FILTER_GRID:
            thr = float(np.nanquantile(pp, 1 - keep))
            st = dev_eval(pipe & (oof_pc >= thr))
            reg("filter_grid", {"keep": keep, "threshold": thr}, st)
            sc = st.get("lb95") if st["n"] >= MIN_DEV_TRADES and st.get("lb95") is not None else -np.inf
            if sc > bscore:
                best, bscore = (keep, thr), sc
        if best:
            choices["filter_best"] = best[1]
            choices["filter_best_keep"] = best[0]
    # direction maker on the grid: the better side per bar, acting on the top share of scores
    gp = pd.DataFrame({"row": np.arange(len(df)), "key": df["key"], "j": df["j"], "p": oof_pc, "r": oof_r})[grid & oof_mask]
    dir_p_rows = gp.loc[gp.groupby(["key", "j"])["p"].idxmax()] if len(gp) else gp
    dir_r_rows = gp.loc[gp.groupby(["key", "j"])["r"].idxmax()] if len(gp) else gp
    if len(dir_p_rows) >= 50:
        best, bscore = None, -np.inf
        for share in DIR_GRID:
            thr = float(np.nanquantile(dir_p_rows["p"], 1 - share))
            m = np.zeros(len(df), bool)
            m[dir_p_rows["row"][dir_p_rows["p"] >= thr].to_numpy(int)] = True
            st = dev_eval(m)
            reg("direction_grid", {"share": share, "threshold": thr}, st)
            sc = st.get("lb95") if st["n"] >= MIN_DEV_TRADES and st.get("lb95") is not None else -np.inf
            if sc > bscore:
                best, bscore = (share, thr), sc
        if best:
            choices["direction_best"] = best[1]
            choices["direction_best_share"] = best[0]
    # fixed-rule configurations, development result for the registry
    if "filter_q50" in choices:
        reg("filter_q50_ab", {"threshold": choices["filter_q50"]}, dev_eval(pipe & (oof_pc >= choices["filter_q50"])))
    reg("filter_er_pos_ab", {"rule": "predicted net R > 0"}, dev_eval(pipe & (oof_r > 0)))
    if "filter_best" in choices:
        reg("filter_best_ab", {"threshold": choices["filter_best"]}, dev_eval(pipe & (oof_pc >= choices["filter_best"])))
        reg("combined_best", {"threshold": choices["filter_best"]}, dev_eval(current & (oof_pc >= choices["filter_best"])))
    reg("combined_er_pos", {"rule": "current + predicted net R > 0"}, dev_eval(current & (oof_r > 0)))
    m = np.zeros(len(df), bool)
    if len(dir_r_rows):
        m[dir_r_rows["row"][dir_r_rows["r"] > 0].to_numpy(int)] = True
    reg("direction_er_pos", {"rule": "side with the higher predicted net R, if > 0"}, dev_eval(m))
    if "direction_best" in choices:
        m = np.zeros(len(df), bool)
        m[dir_p_rows["row"][dir_p_rows["p"] >= choices["direction_best"]].to_numpy(int)] = True
        reg("direction_best", {"threshold": choices["direction_best"]}, dev_eval(m))
    out["dev_choices"] = choices
    out["dev"] = dev_tables
    # trade_filter2 null enable rate (exam on permuted labels) + dev retrain
    tf2_rows = np.flatnonzero(pipe & dev & finished_fill & df["_tf2"].notna().to_numpy())
    tf2 = None
    if len(tf2_rows):
        F2 = np.vstack(df["_tf2"].to_numpy()[tf2_rows]).astype(float)
        R2 = df["r_net"].to_numpy(float)[tf2_rows]
        tf2 = TF2.train(F2, R2, ts[tf2_rows])
        rng = np.random.default_rng(1)
        null = [bool(TF2.train(F2, rng.permutation(R2), ts[tf2_rows]).get("enabled")) for _ in range(cfg.get("null_perms", 20))]
        out["trade_filter2_dev"] = {"enabled": bool(tf2.get("enabled")), "reason": tf2.get("reason"), "exam": tf2.get("exam"),
                                    "n": tf2.get("n"), "null_enable_rate": float(np.mean(null)) if null else None,
                                    "null_runs": len(null)}
    out["seconds_dev"] = round(time.time() - t0, 1)
    if not final:
        out["holdout"] = "not evaluated (dev mode)"
        return out

    # ================= FINAL: refit on all development rows, evaluate the holdout ONCE ==================================
    hold_rows = np.flatnonzero(hold)
    trn_rows = np.flatnonzero(trn)
    p_h, clf = _fit_predict(F[trn_rows], yw[trn_rows], cat, F[hold_rows], "clf", 99)
    r_h, _ = _fit_predict(F[trn_rows], yr[trn_rows], cat, F[hold_rows], "reg", 99)
    ph = np.full(len(df), np.nan)
    rh = np.full(len(df), np.nan)
    ph[hold_rows], rh[hold_rows] = cal(p_h), r_h
    strat = dict(strategies)
    if "filter_q50" in choices:
        strat["filter_q50_ab"] = pipe & (ph >= choices["filter_q50"])
    strat["filter_er_pos_ab"] = pipe & (rh > 0)
    if "filter_best" in choices:
        strat["filter_best_ab"] = pipe & (ph >= choices["filter_best"])
        strat["combined_best"] = current & (ph >= choices["filter_best"])
    strat["combined_er_pos"] = current & (rh > 0)
    gh = pd.DataFrame({"row": np.arange(len(df)), "key": df["key"], "j": df["j"], "p": ph, "r": rh})[grid & hold]
    if len(gh):
        best_p = gh.loc[gh.groupby(["key", "j"])["p"].idxmax()]
        best_r = gh.loc[gh.groupby(["key", "j"])["r"].idxmax()]
        m = np.zeros(len(df), bool)
        m[best_r["row"][best_r["r"] > 0].to_numpy(int)] = True
        strat["direction_er_pos"] = m
        if "direction_best" in choices:
            m = np.zeros(len(df), bool)
            m[best_p["row"][best_p["p"] >= choices["direction_best"]].to_numpy(int)] = True
            strat["direction_best"] = m
    trades = {k: trades_of(df, m & hold, step) for k, m in strat.items()}
    # ---- old AI pieces (item 5) on the holdout: each on top of the current pipeline -----------------------------
    v1 = df["v1_keep"].to_numpy(object)
    trades["old_trade_filter_v1"] = trades_of(df, current & hold & np.array([x is not False for x in v1]), step)
    if tf2 is not None and tf2.get("enabled"):
        sc = np.array([TF2.score(tf2, np.asarray(v, float)) if v is not None and isinstance(v, np.ndarray) else None
                       for v in df["_tf2"].to_numpy()], dtype=object)
        keep2 = np.array([s is None or s >= tf2["threshold"] for s in sc])
        trades["old_trade_filter2"] = trades_of(df, current & hold & keep2, step)
    else:
        trades["old_trade_filter2"] = trades["current_core"]
    for nm in ("runner", "target", "target_runner"):
        alt = df.copy()
        use = alt[f"{nm}_ok"].to_numpy(bool)
        alt.loc[use, "r_net"] = alt.loc[use, f"{nm}_r"]
        alt.loc[use, "closed"] = alt.loc[use, f"{nm}_closed"]
        alt.loc[use, "exit"] = alt.loc[use, f"{nm}_exit"]
        trades[f"old_{nm}"] = trades_of(alt, current & hold, step)
    if df["old_rule_filled"].notna().any():
        alt = df.copy()
        use = alt["old_rule_filled"].notna().to_numpy()
        alt.loc[use, "r_net"] = alt.loc[use, "old_rule_r"]
        alt.loc[use, "closed"] = alt.loc[use, "old_rule_closed"]
        alt.loc[use, "exit"] = alt.loc[use, "old_rule_exit"]
        alt.loc[use, "filled"] = alt.loc[use, "old_rule_filled"].astype(bool)
        trades["old_entry_rule_v25"] = trades_of(alt, current & hold, step)
    # current pipeline with every add-on its own (development) exam switched on
    full = df.copy()
    done = np.zeros(len(full), bool)
    for nm in ("target_runner", "target", "runner"):          # both add-ons on a call: the combined re-simulation
        use = full[f"{nm}_ok"].to_numpy(bool) & ~done
        full.loc[use, "r_net"] = full.loc[use, f"{nm}_r"]
        full.loc[use, "closed"] = full.loc[use, f"{nm}_closed"]
        full.loc[use, "exit"] = full.loc[use, f"{nm}_exit"]
        done |= use
    fm = current & hold & np.array([x is not False for x in v1])
    if tf2 is not None and tf2.get("enabled"):
        fm &= keep2
    trades["current_full"] = trades_of(full, fm, step)
    table = {k: summarize(t, months_hold, watch) for k, t in trades.items()}
    out["holdout"] = table
    # ---- multiple testing: new AI configurations (family) vs zero and vs the current pipeline ------------------------
    fam_new = [k for k in trades if k.startswith(("filter_", "combined_", "direction_"))]
    fam_old = [k for k in trades if k.startswith("old_")]
    pack = lambda t: (t["r_net"].to_numpy(float), MV.block_keys(t["symbol"], t["ts"]))  # noqa: E731
    cur = pack(trades["current_core"])
    out["tests"] = {
        "new_vs_zero": MV.family_test({k: pack(trades[k]) for k in fam_new}),
        "new_vs_current": MV.family_test({k: pack(trades[k]) for k in fam_new}, bench=cur),
        "old_vs_current": MV.family_test({k: pack(trades[k]) for k in fam_old}, bench=cur),
        "baselines_and_current_vs_zero": MV.family_test({k: pack(trades[k]) for k in
                                                          ("current_core", "current_full", "pipeline_ab", "baseline_random",
                                                           "baseline_trend_ema21_50", "baseline_always_long")}),
    }
    # ---- honest confidence (item 4) on the holdout ---------------------------------------------------------------
    lab = hold & finished_fill
    conf = df["conf"].to_numpy(float)
    conf_side = np.where(df["model_side"].to_numpy(int) == side, conf, 1 - conf)
    base = float(yw[trn_rows].mean()) if len(trn_rows) else 0.5
    calib = {}
    for nm, m in (("pipeline_calls", lab & pipe), ("current_calls", lab & current), ("all_candidates", lab)):
        calib[nm] = {"meta_v3_calibrated": MV.reliability(ph[m], yw[m]),
                     "live_confidence_next_bar": MV.reliability(conf_side[m], yw[m]),
                     "dev_base_rate": MV.reliability(np.full(int(m.sum()), base), yw[m])}
    out["calibration_holdout"] = calib
    out["seconds"] = round(time.time() - t0, 1)
    return out


def verdict(tf: str, ev: dict[str, Any]) -> dict[str, Any]:
    """Promotion rule: a new configuration passes on the holdout when (1) its Holm-adjusted one-sided p-value against
    zero (costs) AND against the current pipeline are both < 0.05 (block bootstrap coin x week), (2) the family's reality
    check / SPA p-values are < 0.05, and (3) it has at least 30 holdout trades."""
    if not isinstance(ev.get("holdout"), dict):
        return {"evaluated": False}
    t = ev.get("tests") or {}
    z, c = (t.get("new_vs_zero") or {}), (t.get("new_vs_current") or {})
    passed = []
    for k, v in (z.get("strategies") or {}).items():
        vc = (c.get("strategies") or {}).get(k) or {}
        n = (ev["holdout"].get(k) or {}).get("n", 0)
        if (v.get("p_holm") is not None and v["p_holm"] < 0.05 and vc.get("p_holm") is not None and vc["p_holm"] < 0.05
                and (z.get("spa_p") or 1) < 0.05 and (c.get("spa_p") or 1) < 0.05 and n >= 30):
            passed.append(k)
    old = t.get("old_vs_current") or {}
    old_ok = [k for k, v in (old.get("strategies") or {}).items()
              if v.get("p_holm") is not None and v["p_holm"] < 0.05 and v.get("diff", 0) > 0]
    cur = ev["holdout"].get("current_core") or {}
    return {"evaluated": True, "new_configs_passing": passed, "old_pieces_surviving": old_ok,
            "current_core_avg_r": cur.get("avg_r"), "current_core_ci95": cur.get("ci95"),
            "current_beats_costs": bool(cur.get("lb95") is not None and cur["lb95"] > 0)}


# ---- stored deriv / htf gate tests under multiple-testing correction ------------------------------------------------------

def gates_reexam(db: Any) -> dict[str, Any]:
    from .ml import meta_v3 as MV
    out = {}
    for prefix in ("deriv_gate2|", "htf_gate1|"):
        try:
            rows = db.query("SELECT key, value FROM app_settings WHERE key LIKE ?", (prefix + "%",))
        except Exception as exc:
            out[prefix] = {"error": error_text(exc, 120)}
            continue
        from .db import loads
        tests = {}
        on = 0
        for r in rows:
            v = loads(r["value"], {}) or {}
            if v.get("on"):
                on += 1
            p = v.get("p_value")
            if p is not None:
                tests[r["key"]] = float(p)
        holm = MV.holm(tests)
        ps = sorted(tests.items(), key=lambda kv: kv[1])
        m = len(ps)
        bh_ok = set()
        for i, (k, p) in enumerate(ps):
            if p <= 0.05 * (i + 1) / m:
                bh_ok = {kk for kk, _ in ps[:i + 1]}
        out[prefix.rstrip("|")] = {"series_stored": len(rows), "on": on, "tested": m,
                                   "raw_p_below_0.05": sum(1 for p in tests.values() if p < 0.05),
                                   "survive_holm_0.05": sorted(k for k, p in holm.items() if p is not None and p < 0.05),
                                   "survive_bh_fdr_0.05": sorted(bh_ok),
                                   "on_but_not_surviving_holm": sum(1 for r in rows if (loads(r["value"], {}) or {}).get("on")
                                                                    and not ((holm.get(r["key"]) or 1) < 0.05))}
    return out


# ---- orchestration -----------------------------------------------------------------------------------------------------------

def cuts_from_db(db: Any, tfs: list[str]) -> dict[str, int]:
    """Calendar cut per timeframe: the last HOLDOUT_SHARE of the out-of-sample span (start = median series start of the
    stored out-of-sample rows, estimated from n_oos / data_end of the active models; end = the newest data_end)."""
    out = {}
    for tf in tfs:
        rows = db.query("SELECT n_oos, data_end FROM model_versions WHERE active = 1 AND timeframe = ?", (tf,))
        if not rows:
            continue
        step = tf_ms(tf)
        starts = [int(r["data_end"]) - (min(int(r["n_oos"] or 0), 6000) - 1) * step for r in rows]
        t1 = max(int(r["data_end"]) for r in rows)
        t0 = int(np.median(starts))
        out[tf] = int((t0 + (1 - HOLDOUT_SHARE) * (t1 - t0)) // step * step)
    return out


_W: dict[str, Any] = {}


def _init_worker(db_url: str, exchange: str, threads: int | None = 1) -> None:
    from .db import Database
    from .services.runtime import Runtime
    if threads:
        try:                         # one OpenMP / BLAS thread per worker process (oversubscription made fits ~5x slower)
            from threadpoolctl import threadpool_limits
            _W["limits"] = threadpool_limits(threads)
        except Exception:
            pass

    class _Prov:
        name = exchange
    db = Database(db_url)
    _W["rt"] = Runtime(db, _Prov())


def _job(args: tuple[str, list[str], dict[str, Any], float]) -> list[dict[str, Any]]:
    symbol, tfs, cfg, deadline = args
    from . import research_engine as RE
    rt = _W["rt"]
    cfg = {**cfg, "news": RE._news_fn(rt.db)}
    cache: dict = {}
    res = []
    for tf in tfs:
        if time.time() > deadline:
            res.append({"key": f"{symbol} {tf}", "skip": "time budget"})
            continue
        try:
            res.append(build_series(rt, symbol, tf, cfg, cache))
        except Exception as exc:
            log.exception("%s %s", symbol, tf)
            res.append({"key": f"{symbol} {tf}", "error": error_text(exc, 300)})
    return res


def run(db_url: str, mode: str = "dev", budget_s: float = 14400, symbols: list[str] | None = None,
        tfs: list[str] | None = None, workers: int | None = None, prior_final_runs: int = 0) -> dict[str, Any]:
    from concurrent.futures import ProcessPoolExecutor
    import multiprocessing as mp

    from .db import Database
    from .services.runtime import Runtime
    t0 = time.time()
    final = mode == "final"
    db = Database(db_url)
    ex = db.one("SELECT exchange, COUNT(*) AS n FROM market_data GROUP BY exchange ORDER BY n DESC LIMIT 1")
    exchange = ex["exchange"] if ex else "binance"

    class _Prov:
        name = exchange
    rt = Runtime(db, _Prov())
    tfs = tfs or list(MODEL_TIMEFRAMES)
    syms = symbols or [r["symbol"] for r in db.query("SELECT DISTINCT symbol FROM model_versions WHERE active = 1 ORDER BY symbol")]
    try:
        watch = set(rt.symbols())
    except Exception:
        watch = set()
    if not watch:
        from .worker import TEST_COINS
        watch = set(TEST_COINS)
    cuts = cuts_from_db(db, tfs)
    tfs = [t for t in tfs if t in cuts]
    cfg = {"cuts": cuts, "entry_rules": {tf: stored_entry_rule(db, tf) for tf in tfs}, "symbols": syms,
           "null_perms": int(os.environ.get("AIV3_NULL_PERMS", "20"))}
    deadline = t0 + budget_s * 0.75                        # phase 1 share of the budget
    order = sorted(syms, key=lambda s: (s != "BTC/USDT", s))
    tasks = [(s, [tf for tf in ("3d", "1d", "12h", "4h", "1h", "15m") if tf in tfs], cfg, deadline) for s in order]
    nw = workers or max(1, min(os.cpu_count() or 1, 4))
    results: list[dict[str, Any]] = []
    if nw > 1:
        ctxm = mp.get_context("fork")
        with ProcessPoolExecutor(nw, mp_context=ctxm, initializer=_init_worker, initargs=(db_url, exchange)) as pool:
            for res in pool.map(_job, tasks):
                results.extend(res)
    else:
        _init_worker(db_url, exchange, None)
        for t in tasks:
            results.extend(_job(t))
    t1 = time.time()
    ok = [r for r in results if "recs" in r]
    registry: list[dict[str, Any]] = []
    per_tf, verdicts = {}, {}
    for tf in tfs:
        ser = [r for r in ok if r["tf"] == tf]
        if not ser:
            per_tf[tf] = {"error": "no series"}
            continue
        try:
            per_tf[tf] = evaluate_tf(tf, ser, cuts[tf], final, watch, registry, cfg)
        except Exception as exc:
            log.exception("evaluate %s", tf)
            per_tf[tf] = {"error": error_text(exc, 400)}
        verdicts[tf] = verdict(tf, per_tf[tf])
    old_summary: dict[str, Any] = {}
    for tf in tfs:
        ser = [r for r in ok if r["tf"] == tf]
        agg = {}
        for nm in ("trade_filter", "runner_model", "target_model"):
            agg[nm] = {"enabled_in_live_bundle": sum(1 for r in ser if (r.get("bundle_addons") or {}).get(nm)),
                       "enabled_by_own_exam_on_dev": sum(1 for r in ser if ((r.get("old_pieces") or {}).get(nm) or {}).get("enabled_dev")),
                       "series": len(ser),
                       "errors": sum(1 for r in ser if (r.get("old_pieces") or {}).get("error"))}
        old_summary[tf] = agg
    body = {
        "engine_version": ENGINE_VERSION, "mode": mode, "holdout_evaluated": final,
        "prior_final_runs_on_record": prior_final_runs,
        "method": (__doc__ or "").strip(), "cuts": cuts, "holdout_share": HOLDOUT_SHARE, "cv_folds": CV_FOLDS,
        "entry_rules_live": {tf: f"{m}:{k}" for tf, (m, k) in cfg["entry_rules"].items()},
        "a_only_tfs": list(__import__("app.services.analysis", fromlist=["A_ONLY_TFS"]).A_ONLY_TFS),
        "symbols": syms, "watchlist": sorted(watch), "costs": {"round_trip_pct": __import__("app.services.tracking",
                                                                                          fromlist=["cost_pct"]).cost_pct(),
                                                               "funding": "stored hourly funding_1h, default 0.01 %/8 h"},
        "series": {r["key"]: {k: r.get(k) for k in ("n_oos", "span", "entry_rule", "skipped", "pipe_calls", "grid_rows",
                                                    "bundle_addons", "uses_htf", "edge_confirmed", "seconds")} |
                   {"candidates": len(r["recs"]), "old_pieces": {k: v for k, v in (r.get("old_pieces") or {}).items()
                                                                 if k != "holdout_calls"}} for r in ok},
        "skipped_series": [{k: r.get(k) for k in ("key", "skip", "error")} for r in results if "recs" not in r],
        "per_timeframe": per_tf, "verdicts": verdicts, "registry": registry, "registry_size": len(registry),
        "old_pieces_summary": old_summary, "gates": gates_reexam(db),
        "seconds": {"candidates": round(t1 - t0, 1), "total": round(time.time() - t0, 1)}, "workers": nw,
        "approximations": [
            "model agreement per member is not stored out-of-sample: treated as passing (as research_engine)",
            "no order book in history: liquidity component left out",
            "base rates use the stop distance snapped to 0.05 ATR",
            "the safety switch, the series gate (off live), the reentry_regime check and per-member limits are not replayed",
            "publication ~1 min after the bar close: entry = open of that 15m candle; exits follow from the next 15m candle (live A1)",
            "the direction reference / confidence uses development rows (incl. the row itself on development)",
            "base models' own hyper-parameters and deriv/htf feature gates were chosen on data that overlaps the holdout",
            "earlier research (v2.6-v2.14) looked at the last 30 % of each series, which overlaps this holdout: it is fresh "
            "for the new methods, not for the past owner decisions",
            "grid rows (baselines / direction maker) are every k-th bar (STRIDE), not every bar"],
    }
    return body
