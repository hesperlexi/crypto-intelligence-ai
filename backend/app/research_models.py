"""`python -m app.research models`: v2.7 model research on the restored engine state (read-only).

Two model upgrades compared with the CURRENT live pipeline (v2.6: the per-coin ensemble's walk-forward out-of-sample
predictions -> series_policy.decide -> entry rule chosen per timeframe on the tuning part (ENTRY_RULES on) -> pooled
trade filter per timeframe trained on tuning trades and switched on only where its own exam passes (TRADE_FILTER2 on)):

  A    trade-outcome labels. For every bar and side the engine's own plan (series_sim.plan = engine/setup.build_setup:
       ATR / structure stop in [1, 3] ATR, TP ladder 1R / 1.75R / 2.5R) is entered at the bar's close and followed with
       the record's rules over the 30-bar horizon. Targets: P(TP1 before the stop) (classifier) and the realised R after
       costs (regressor), one pair per side. Per coin models. Decision: the side whose P clears a threshold chosen per
       timeframe on the tuning part, with a positive predicted R after costs; plan validity, costs rule, extreme
       volatility and the news guard as live.
  B    pooled direction model: one LightGBM per timeframe on all coins together (features z-scored per coin on a rolling
       500-bar window, coin one-hot, BTC context), same next-bar target as today; its probabilities replace the
       ensemble's and go through the CURRENT pipeline unchanged (decide, entry choice, filter2).
  A+B  trade-outcome labels with pooled models.
  diag_percoin_direction (diagnostic, not a candidate): the B recipe per coin, to separate "pooled" from "one LightGBM
       instead of the ensemble".

Discipline (identical for every variant): the series' rows, their tuning / test split (first 70 % of the series'
out-of-sample span chooses, the last 30 % - after a gap of one horizon - is the untouched test) and the trade
simulation (series_sim.follow on 15m candles, 50/25/25, break-even after TP1, TP1 after TP2, RESEARCH_COST_PCT) are the
ones of `python -m app.research engine`. New models are walk-forward: the out-of-sample span of each timeframe is cut
into K chunks; the model predicting chunk [b_k, b_k+1) is fitted only on rows whose label had fully closed by b_k
(purge / embargo of horizon + 1 bars). Thresholds and options are chosen on tuning rows only.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

from .config import ENGINE_VERSION, settings
from .data.base import tf_ms
from .ml import series_policy as SP, series_sim as S, trade_filter2 as TF2

log = logging.getLogger("research.models")
TUNE_SHARE = 0.7
H = SP.HORIZON_BARS
TFS_DEFAULT = ["1h", "4h", "12h", "1d", "3d"]           # 15m is paused live (PAUSED_TFS): left out unless asked for
TF_RUN_ORDER = ["3d", "1d", "12h", "4h", "1h", "15m"]
K_CHUNKS = {"15m": 6, "1h": 6, "4h": 6, "12h": 6, "1d": 6, "3d": 5}
MAX_TRAIN_PER_COIN = 20000                               # most recent rows per coin in a fit
MAX_TRAIN_POOLED = 120000                                # most recent rows over all coins in a pooled fit
MIN_TRAIN = 300
ZWIN, ZMIN = 500, 100                                    # rolling per-coin normalisation (pooled models)
THR_GRID = (0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70)
ENTRY_OPTIONS = [("old", 0.0), ("market", 0.0), ("confirm", 0.0), ("confirm", 0.1), ("confirm", 0.25),
                 ("pullback", 0.25), ("pullback", 0.5)]
VARIANTS = ["current", "A", "B", "AB"]
WEEK = 7 * 86_400_000


# ---- models ------------------------------------------------------------------------------------------------------------

def _lgbm_ok() -> bool:
    try:
        import lightgbm  # noqa: F401
        return True
    except Exception:
        return False


def _clf(n: int, multiclass: bool = False):
    if _lgbm_ok():
        from lightgbm import LGBMClassifier
        from .ml.models import N_JOBS
        return LGBMClassifier(n_estimators=200, num_leaves=15, learning_rate=0.04, subsample=0.8, subsample_freq=1,
                              colsample_bytree=0.7, min_child_samples=max(20, n // 300), reg_lambda=2.0, n_jobs=N_JOBS,
                              random_state=0, verbose=-1)
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(max_iter=200, learning_rate=0.04, max_leaf_nodes=15,
                                          min_samples_leaf=max(20, n // 300), l2_regularization=2.0, random_state=0)


def _reg(n: int):
    if _lgbm_ok():
        from lightgbm import LGBMRegressor
        from .ml.models import N_JOBS
        return LGBMRegressor(n_estimators=150, num_leaves=15, learning_rate=0.04, subsample=0.8, subsample_freq=1,
                             colsample_bytree=0.7, min_child_samples=max(20, n // 300), reg_lambda=2.0, n_jobs=N_JOBS,
                             random_state=0, verbose=-1)
    from sklearn.ensemble import HistGradientBoostingRegressor
    return HistGradientBoostingRegressor(max_iter=150, learning_rate=0.04, max_leaf_nodes=15,
                                         min_samples_leaf=max(20, n // 300), l2_regularization=2.0, random_state=0)


# ---- labels ------------------------------------------------------------------------------------------------------------

def trade_labels(ctx_all: SP.Context, high: np.ndarray, low: np.ndarray, close: np.ndarray, cost_pct: float,
                 rows: np.ndarray | None = None, horizon: int = H) -> dict[str, np.ndarray]:
    """For each frame row i (ctx_all covers every frame row: ctx_all.rows == arange) and side: the engine's plan at the
    close of bar i, entered at market there, followed on bars i+1 .. i+horizon with the record's rules.
    y_* = 1 when TP1 was reached before the stop (status TP1 / TP2 / TP3), r_* = realised R after costs.
    NaN when the label is not complete on the data (i + horizon beyond the last bar) or no plan exists."""
    n = len(close)
    out = {k: np.full(n, np.nan) for k in ("y_long", "y_short", "r_long", "r_short")}
    idx = np.arange(n) if rows is None else np.asarray(rows, int)
    for i in idx:
        if i + horizon >= n or not np.isfinite(ctx_all.atr[i]) or ctx_all.atr[i] <= 0:
            continue
        hi, lo, cl = high[i + 1:i + 1 + horizon], low[i + 1:i + 1 + horizon], close[i + 1:i + 1 + horizon]
        z = ctx_all.zones(int(i))
        for side, ky, kr in ((1, "y_long", "r_long"), (-1, "y_short", "r_short")):
            pl = S.plan(side, float(close[i]), float(ctx_all.atr[i]), float(ctx_all.ema21[i]), z,
                        float(ctx_all.last_sl[i]), float(ctx_all.last_sh[i]))
            if "stop" not in pl:
                continue
            entry, stop = float(close[i]), float(pl["stop"])
            if side * (entry - stop) <= 0:
                continue
            o = S.follow(side, entry, stop, S.ladder(side, entry, stop), hi, lo, cl, complete=True)
            if o is None:
                continue
            out[ky][i] = 1.0 if o.status in ("TP1", "TP2", "TP3") else 0.0
            out[kr][i] = o.net_r(cost_pct)
    ctx_all.zone_cache.clear()
    return out


def direction_labels(ind: pd.DataFrame, band: float | None = None) -> np.ndarray:
    """The current target (features/dataset.make_dataset): next bar DOWN 0 / NEUTRAL 1 / UP 2 around +/- band sigma."""
    band = settings.neutral_band_sigma if band is None else band
    c = ind["close"]
    fwd = (c.shift(-1) / c - 1).to_numpy(float)
    thr = (band * ind["sigma_bar"]).to_numpy(float)
    y = np.where(fwd > thr, 2.0, np.where(fwd < -thr, 0.0, 1.0))
    return np.where(np.isfinite(fwd) & np.isfinite(thr), y, np.nan)


def rolling_z(X: pd.DataFrame, win: int = ZWIN, min_periods: int = ZMIN) -> pd.DataFrame:
    """Per-coin causal normalisation: each value against the mean / std of the same coin's last `win` bars (incl. itself)."""
    r = X.rolling(win, min_periods=min_periods)
    z = (X - r.mean()) / r.std().replace(0, np.nan)
    return z.clip(-8, 8)


# ---- series data -------------------------------------------------------------------------------------------------------

@dataclass
class Series:
    symbol: str
    tf: str
    ctx: SP.Context                   # CURRENT context (rows = the bundle's out-of-sample bars)
    paths: SP.Paths
    tune: np.ndarray
    test: np.ndarray
    cut: int
    ts: np.ndarray                    # every frame row
    X: np.ndarray                     # raw features, every frame row
    Xz: np.ndarray                    # per-coin z-scored features
    labels: dict[str, np.ndarray]     # trade labels (every frame row)
    ydir: np.ndarray
    first: int                        # first frame row with labels computed
    cols: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.symbol} {self.tf}"


def _features(rt, symbol: str, tf: str, frame, cache: dict) -> pd.DataFrame:
    from .features.dataset import HTF_OF, InsufficientData, make_features
    btc = frame if symbol == "BTC/USDT" else cache.get(("BTC/USDT", tf))
    if btc is None and symbol != "BTC/USDT":
        try:
            btc = cache[("BTC/USDT", tf)] = rt.frame("BTC/USDT", tf)
        except Exception:
            btc = None
    htf = None
    if tf in HTF_OF:
        try:
            htf = rt.frame(symbol, HTF_OF[tf])
        except (InsufficientData, Exception):
            htf = None
    return make_features(frame, btc, htf)


def prepare(rt, symbol: str, tf: str, cost: float, cache: dict) -> Series | None:
    from . import research_engine as RE
    b = RE.build(rt, symbol, tf, cache)
    if b is None:
        return None
    ctx, paths = b
    tune, test, cut = RE._split(ctx)
    if tune.sum() < 150 or test.sum() < 30:
        return None
    frame = cache[symbol][tf]
    ind = frame.ind
    ts = ind["ts"].to_numpy(np.int64)
    n = len(ts)
    Xdf = _features(rt, symbol, tf, frame, cache)
    first = max(0, int(ctx.rows[0]) - MAX_TRAIN_PER_COIN - H - 1)
    allb = {"oos": {"ts": ts, "P_ens": np.full((n, 3), 1 / 3), "fwd_ret": np.zeros(n)}, "edge": {}}
    call = SP.build_context(symbol, tf, allb, {tf: frame}, None)
    labels = trade_labels(call, ind["high"].to_numpy(float), ind["low"].to_numpy(float), ind["close"].to_numpy(float),
                          cost, rows=np.arange(first, n))
    return Series(symbol, tf, ctx, paths, tune, test, cut, ts, Xdf.to_numpy(float),
                  rolling_z(Xdf).to_numpy(float), labels, direction_labels(ind), first, list(Xdf.columns))


def align_columns(items: list[Series]) -> list[str]:
    """Same feature columns for every series of a timeframe (a coin without e.g. a higher-timeframe frame gets those
    columns as missing values), so pooled fits can stack them."""
    cols = list(dict.fromkeys(c for s in items for c in s.cols))
    for s in items:
        if s.cols == cols:
            continue
        pos = {c: i for i, c in enumerate(s.cols)}
        for attr in ("X", "Xz"):
            old = getattr(s, attr)
            new = np.full((old.shape[0], len(cols)), np.nan)
            for j, c in enumerate(cols):
                if c in pos:
                    new[:, j] = old[:, pos[c]]
            setattr(s, attr, new)
        s.cols = cols
    return cols


# ---- walk-forward fitting ------------------------------------------------------------------------------------------------

def boundaries(items: list[Series], k: int) -> np.ndarray:
    """Chunk edges over the timeframe's out-of-sample span (calendar time, shared by all coins)."""
    t0 = min(int(s.ctx.ts[0]) for s in items)
    t1 = max(int(s.ctx.ts[-1]) for s in items) + 1
    return np.linspace(t0, t1, k + 1).astype(np.int64)


def walk_forward(items: list[Series], bounds: np.ndarray, kind: str, pooled: bool, cols: list[str] | None = None,
                 fitlog: list | None = None, max_pooled: int = MAX_TRAIN_POOLED) -> dict[str, dict[str, np.ndarray]]:
    """Predictions on every CURRENT out-of-sample row (ctx rows) of each series. kind "trade": p_long, p_short, r_long,
    r_short; kind "dir": P (n, 3). The model for chunk k only sees rows whose label closed by bounds[k]."""
    step = tf_ms(items[0].tf)
    emb = (H + 1) * step
    out: dict[str, dict[str, np.ndarray]] = {}
    for s in items:
        n = s.ctx.n
        out[s.key] = ({"p_long": np.full(n, np.nan), "p_short": np.full(n, np.nan), "r_long": np.full(n, np.nan),
                       "r_short": np.full(n, np.nan)} if kind == "trade" else {"P": np.full((n, 3), np.nan)})
    syms = sorted({s.symbol for s in items})
    groups = [items] if pooled else [[s] for s in items]

    def mat(s: Series, rows: np.ndarray) -> np.ndarray:
        X = s.Xz[rows] if pooled else s.X[rows]
        if pooled:
            oh = np.zeros((len(rows), len(syms)))
            oh[:, syms.index(s.symbol)] = 1.0
            X = np.hstack([X, oh])
        return X

    for grp in groups:
        for k in range(len(bounds) - 1):
            lo, hi = int(bounds[k]), int(bounds[k + 1])
            targets = {s.key: np.flatnonzero((s.ctx.ts >= lo) & (s.ctx.ts < hi)) for s in grp}
            if not any(len(v) for v in targets.values()):
                continue
            parts = []
            for s in grp:
                ok = (s.ts + emb <= lo)
                ok[:s.first] = False
                if kind == "trade":
                    ok &= np.isfinite(s.labels["y_long"]) & np.isfinite(s.labels["y_short"])
                else:
                    ok &= np.isfinite(s.ydir)
                r = np.flatnonzero(ok)[-MAX_TRAIN_PER_COIN:]
                if len(r):
                    parts.append((s, r))
            n_all = sum(len(r) for _, r in parts)
            if n_all < MIN_TRAIN:
                if fitlog is not None:
                    fitlog.append({"group": grp[0].key if not pooled else f"pooled {grp[0].tf}", "chunk": k, "rows": n_all,
                                   "skipped": "too few training rows"})
                continue
            X = np.vstack([mat(s, r) for s, r in parts])
            tts = np.concatenate([s.ts[r] for s, r in parts])
            lab = {}
            if kind == "trade":
                for c in ("y_long", "y_short", "r_long", "r_short"):
                    lab[c] = np.concatenate([s.labels[c][r] for s, r in parts])
            else:
                lab["y"] = np.concatenate([s.ydir[r] for s, r in parts])
            sub = None
            if len(tts) > max_pooled:                       # keep the most recent rows
                sub = np.argsort(tts, kind="stable")[-max_pooled:]
                X, tts = X[sub], tts[sub]
                lab = {c: v[sub] for c, v in lab.items()}
            t_fit = time.time()
            models = {}
            if kind == "trade":
                for side in ("long", "short"):
                    y = lab[f"y_{side}"].astype(int)
                    if len(set(y)) < 2:
                        continue
                    models[f"p_{side}"] = _clf(len(y)).fit(X, y)
                    models[f"r_{side}"] = _reg(len(y)).fit(X, lab[f"r_{side}"])
            else:
                y = lab["y"].astype(int)
                if len(set(y)) == 3:
                    models["P"] = _clf(len(y), multiclass=True).fit(X, y)
            for s in grp:
                rows = targets[s.key]
                if not len(rows) or not models:
                    continue
                Xp = mat(s, s.ctx.rows[rows])
                for name, m in models.items():
                    if name.startswith("p_"):
                        out[s.key][name][rows] = m.predict_proba(Xp)[:, 1]
                    elif name.startswith("r_"):
                        out[s.key][name][rows] = m.predict(Xp)
                    else:
                        out[s.key]["P"][rows] = m.predict_proba(Xp)
            if fitlog is not None:
                fitlog.append({"group": grp[0].key if not pooled else f"pooled {grp[0].tf}", "chunk": k,
                               "rows": int(len(tts)), "subsampled_from": int(n_all) if sub is not None else None,
                               "seconds": round(time.time() - t_fit, 1)})
    return out


# ---- decisions -------------------------------------------------------------------------------------------------------------

def trade_side(p_long: np.ndarray, p_short: np.ndarray, r_long: np.ndarray, r_short: np.ndarray, thr: float) -> np.ndarray:
    """+1 / -1 / 0 per row: the side whose P(TP1 before stop) clears `thr` with a positive predicted R after costs
    (the more likely one when both do)."""
    okL = np.nan_to_num(p_long, nan=-1) >= thr
    okL &= np.nan_to_num(r_long, nan=-1) > 0
    okS = np.nan_to_num(p_short, nan=-1) >= thr
    okS &= np.nan_to_num(r_short, nan=-1) > 0
    both = okL & okS
    side = np.where(okL, 1, 0) + np.where(okS, -1, 0)
    side = np.where(both, np.where(np.nan_to_num(p_long) >= np.nan_to_num(p_short), 1, -1), side)
    return side.astype(int)


def own_edge(s: Series, P: np.ndarray) -> bool:
    """Edge flag of replacement probabilities, judged on the TUNING rows only: lower multiclass Brier than the tuning
    rows' class base rates (the analogue of the bundle's edge test, which gates the ml term of the composite)."""
    y = s.ydir[s.ctx.rows[s.tune]]
    Pt = P[s.tune]
    ok = np.isfinite(y)
    if ok.sum() < 100:
        return False
    Y = np.eye(3)[y[ok].astype(int)]
    prior = Y.mean(axis=0)
    return bool(((Pt[ok] - Y) ** 2).sum(axis=1).mean() < ((prior - Y) ** 2).sum(axis=1).mean())


class TradeCands:
    """Simulated outcome of a trade-label call at (row, side), memoised (market entry, live plan / costs / vol gates)."""

    def __init__(self, s: Series, cost: float, news: Callable[[int], bool] | None):
        self.s, self.cost, self.news, self.memo = s, cost, news, {}
        self.rt = SP.round_trip()

    def one(self, j: int, side: int) -> dict[str, Any] | None:
        key = (j, side)
        if key not in self.memo:
            ctx = self.s.ctx
            res = None
            if not (self.news is not None and self.news(int(ctx.decision_ts[j]))) and ctx.vol_state[j] != 3:
                pl = S.plan(side, float(ctx.close[j]), float(ctx.atr[j]), float(ctx.ema21[j]), ctx.zones(j),
                            float(ctx.last_sl[j]), float(ctx.last_sh[j]))
                if pl["valid"] and pl["dist"] / pl["ideal"] >= SP.COST_MULT * self.rt:
                    r = SP.simulate(ctx, self.s.paths, j, side, pl, "market", 0.0, self.cost)
                    if r is not None and r.get("filled"):
                        res = {"j": j, "ts": int(ctx.decision_ts[j]), "side": side, **r}
            self.memo[key] = res
        return self.memo[key]

    def trades(self, mask: np.ndarray, side: np.ndarray) -> list[dict[str, Any]]:
        cs = [c for j in np.flatnonzero(mask & (side != 0)) if (c := self.one(int(j), int(side[j]))) is not None]
        return SP.taken(self.s.ctx, cs)


def run_trade_variant(items: list[Series], preds: dict[str, dict[str, np.ndarray]], cost: float, news) -> dict[str, Any]:
    """Threshold chosen per timeframe on the tuning rows (pooled over coins: best 80 % lower bound of the expectancy with
    >= 30 trades, and only when the tuning mean is positive), then applied to the test rows."""
    tc = {s.key: TradeCands(s, cost, news) for s in items}
    table = []
    for thr in THR_GRID:
        r = []
        for s in items:
            p = preds[s.key]
            side = trade_side(p["p_long"], p["p_short"], p["r_long"], p["r_short"], thr)
            r += [t["r"] for t in tc[s.key].trades(s.tune, side)]
        table.append({"thr": thr, "n": len(r), "mean_r": float(np.mean(r)) if r else None,
                      "lb80": S.bootstrap_lb(r, 0.8) if len(r) >= 30 else None})
    ok = [t for t in table if t["lb80"] is not None]
    best = max(ok, key=lambda t: t["lb80"]) if ok else None
    on = bool(best and best["mean_r"] is not None and best["mean_r"] > 0)
    test = {}
    for s in items:
        if not on:
            test[s.key] = []
            continue
        p = preds[s.key]
        side = trade_side(p["p_long"], p["p_short"], p["r_long"], p["r_short"], best["thr"])
        test[s.key] = tc[s.key].trades(s.test, side)
    return {"choice": {"threshold": best["thr"] if best else None, "trading": on,
                       "reason": None if on else "no threshold with a positive expectancy on the tuning rows",
                       "table": table}, "test": test}


def run_current(items: list[Series], cost: float, news, P_override: dict[str, np.ndarray] | None = None) -> dict[str, Any]:
    """The v2.6 live pipeline on these series (optionally with other direction probabilities): decide on tuning
    reference, entry rule chosen per timeframe like the nightly job, pooled filter2 trained on tuning trades."""
    ctxs = {}
    for s in items:
        ctx = s.ctx
        if P_override is not None:
            import copy
            ctx = copy.copy(ctx)
            P = P_override[s.key].copy()
            bad = ~np.isfinite(P).all(axis=1)
            P[bad] = 1 / 3
            ctx.P = P
            ctx.edge_confirmed = own_edge(s, P)
        ctxs[s.key] = ctx
    entry_tune, cands, decs = {}, {}, {}
    F, R, T = [], [], []
    for s in items:
        ctx = ctxs[s.key]
        d = decs[s.key] = SP.decide(ctx, s.tune)
        t_early = int(ctx.ts[0]) + int((s.cut - int(ctx.ts[0])) * 0.7)
        entry_tune[s.key] = {}
        for mode, k in ENTRY_OPTIONS:
            c = SP.candidates(ctx, s.paths, s.tune | s.test, d, entry_mode=mode, k=k, cost_pct=cost, news=news)
            cands[(s.key, mode, k)] = c
            tr = SP.taken(ctx, [x for x in c if s.tune[x["j"]]])
            entry_tune[s.key][f"{mode}:{k}"] = {"early": [t["r"] for t in tr if t["ts"] < t_early],
                                                "late": [t["r"] for t in tr if t["ts"] >= t_early]}
        for c in cands[(s.key, "old", 0.0)]:
            if c["filled"] and s.tune[c["j"]] and c["closed_ts"] < s.cut:
                F.append(TF2.features(ctx, d, c["j"]))
                R.append(c["r"])
                T.append(c["ts"])
    # entry rule (research_engine: best lb80 on the early tuning trades, confirmed on the late ones)
    tab = {}
    for mode, k in ENTRY_OPTIONS:
        e = sum((entry_tune[s.key][f"{mode}:{k}"]["early"] for s in items), [])
        l_ = sum((entry_tune[s.key][f"{mode}:{k}"]["late"] for s in items), [])
        tab[f"{mode}:{k}"] = {"n_early": len(e), "lb80_early": S.bootstrap_lb(e, 0.8) if len(e) >= 30 else None,
                              "n_late": len(l_), "mean_late": float(np.mean(l_)) if l_ else None}
    old = tab["old:0.0"]
    cand = [(k, v) for k, v in tab.items() if v["lb80_early"] is not None and v["n_early"] >= 0.3 * max(old["n_early"], 1)]
    best = max(cand, key=lambda kv: kv[1]["lb80_early"])[0] if cand else "old:0.0"
    confirmed = bool(best != "old:0.0" and tab[best]["mean_late"] is not None and old["mean_late"] is not None
                     and tab[best]["mean_late"] > old["mean_late"])
    chosen = best if confirmed else "old:0.0"
    f = TF2.train(np.array(F) if F else np.zeros((0, len(TF2.FEATURES))), np.array(R), np.array(T))
    mode, k = chosen.split(":")
    test = {}
    for s in items:
        ctx, d = ctxs[s.key], decs[s.key]
        c = [x for x in cands[(s.key, mode, float(k))] if s.test[x["j"]]]
        keep = None
        if f.get("enabled"):
            keep = lambda x, ctx=ctx, d=d: TF2.score(f, TF2.features(ctx, d, x["j"])) >= f["threshold"]  # noqa: E731
        test[s.key] = SP.taken(ctx, c, keep)
    return {"choice": {"entry": chosen, "filter2": {k_: v for k_, v in f.items() if k_ != "model"}}, "test": test}


# ---- statistics ------------------------------------------------------------------------------------------------------------

def _boot(base: dict[str, list], var: dict[str, list], unit: str, n_boot: int = 2000, seed: int = 0) -> dict[str, Any]:
    """Share of resamples (of series, or of calendar weeks of the decision time) where the variant's test expectancy beats
    the base's. Both variants are resampled with the same units (paired)."""
    if unit == "series":
        units = sorted(set(base) | set(var))
        ub = {u: [t["r"] for t in base.get(u, [])] for u in units}
        uv = {u: [t["r"] for t in var.get(u, [])] for u in units}
    else:
        ub, uv = {}, {}
        for res, dst in ((base, ub), (var, uv)):
            for ts_ in res.values():
                for t in ts_:
                    dst.setdefault(int(t["ts"]) // WEEK, []).append(t["r"])
        units = sorted(set(ub) | set(uv))
    if not units:
        return {"units": 0, "share_better": None, "mean_gain_r": None}
    sb = np.array([sum(ub.get(u, [])) for u in units]); nb = np.array([len(ub.get(u, [])) for u in units])
    sv = np.array([sum(uv.get(u, [])) for u in units]); nv = np.array([len(uv.get(u, [])) for u in units])
    rng = np.random.default_rng(seed)
    W = rng.multinomial(len(units), np.full(len(units), 1 / len(units)), size=n_boot).astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        mb = (W @ sb) / (W @ nb)
        mv = (W @ sv) / (W @ nv)
    ok = np.isfinite(mb) & np.isfinite(mv)
    if not ok.any():
        return {"units": len(units), "share_better": None, "mean_gain_r": None}
    g = mv[ok] - mb[ok]
    return {"units": len(units), "share_better": float((g > 0).mean()), "mean_gain_r": float(g.mean()),
            "gain_q10_q90": [float(np.quantile(g, 0.1)), float(np.quantile(g, 0.9))]}


def _auc(y: np.ndarray, p: np.ndarray) -> float | None:
    ok = np.isfinite(y) & np.isfinite(p)
    if ok.sum() < 50 or len(set(y[ok])) < 2:
        return None
    from sklearn.metrics import roc_auc_score
    return float(roc_auc_score(y[ok], p[ok]))


# ---- driver ------------------------------------------------------------------------------------------------------------------

def evaluate(rt, symbols: list[str], tfs: list[str], deadline: float, cost: float, diag: bool = True,
             checkpoint: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    from . import research_engine as RE
    news = RE._news_fn(rt.db)
    cache: dict = {}
    results: dict[str, dict[str, list]] = {v: {} for v in VARIANTS + (["diag_percoin_direction"] if diag else [])}
    weeks: dict[str, float] = {}
    choices: dict[str, Any] = {}
    fitlog: list = []
    skipped: list[str] = []
    model_skill: dict[str, Any] = {}
    series_info: dict[str, Any] = {}
    for tf in [t for t in TF_RUN_ORDER if t in tfs]:
        if time.time() > deadline:
            skipped.append(f"{tf}: budget reached before this timeframe")
            continue
        t_tf = time.time()
        items = []
        for s in symbols:
            try:
                it = prepare(rt, s, tf, cost, cache)
            except Exception as exc:
                log.warning("prepare %s %s: %s", s, tf, exc)
                skipped.append(f"{s} {tf}: {type(exc).__name__}: {exc}"[:200])
                continue
            if it is None:
                skipped.append(f"{s} {tf}: no model / too few out-of-sample bars")
                continue
            items.append(it)
        if not items:
            continue
        align_columns(items)
        log.info("%s: %d series prepared in %.0fs", tf, len(items), time.time() - t_tf)
        bounds = boundaries(items, K_CHUNKS.get(tf, 6))
        try:
            pA = walk_forward(items, bounds, "trade", pooled=False, fitlog=fitlog)
            pAB = walk_forward(items, bounds, "trade", pooled=True, fitlog=fitlog)
            pB = walk_forward(items, bounds, "dir", pooled=True, fitlog=fitlog)
            pD = walk_forward(items, bounds, "dir", pooled=False, fitlog=fitlog) if diag else None
        except Exception as exc:
            log.exception("fits %s", tf)
            skipped.append(f"{tf}: fitting failed: {type(exc).__name__}: {exc}"[:200])
            continue
        cur = run_current(items, cost, news)
        a = run_trade_variant(items, pA, cost, news)
        ab = run_trade_variant(items, pAB, cost, news)
        b = run_current(items, cost, news, {k: v["P"] for k, v in pB.items()})
        d = run_current(items, cost, news, {k: v["P"] for k, v in pD.items()}) if diag else None
        choices[tf] = {"current": cur["choice"], "A": a["choice"], "B": b["choice"], "AB": ab["choice"],
                       "chunk_edges": [int(x) for x in bounds]}
        if diag:
            choices[tf]["diag_percoin_direction"] = d["choice"]
        for s in items:
            weeks[s.key] = RE._weeks(s.ctx, s.test)
            results["current"][s.key] = cur["test"][s.key]
            results["A"][s.key] = a["test"][s.key]
            results["AB"][s.key] = ab["test"][s.key]
            results["B"][s.key] = b["test"][s.key]
            if diag:
                results["diag_percoin_direction"][s.key] = d["test"][s.key]
            rows = s.ctx.rows[s.test]
            yl, ys = s.labels["y_long"][rows], s.labels["y_short"][rows]
            model_skill[s.key] = {
                "test_auc_tp1_long": {"A": _auc(yl, pA[s.key]["p_long"][s.test]), "AB": _auc(yl, pAB[s.key]["p_long"][s.test])},
                "test_auc_tp1_short": {"A": _auc(ys, pA[s.key]["p_short"][s.test]), "AB": _auc(ys, pAB[s.key]["p_short"][s.test])},
                "test_base_rate_tp1": {"long": float(np.nanmean(yl)) if np.isfinite(yl).any() else None,
                                       "short": float(np.nanmean(ys)) if np.isfinite(ys).any() else None}}
            series_info[s.key] = {"oos_bars": int(s.ctx.n), "tune_bars": int(s.tune.sum()), "test_bars": int(s.test.sum()),
                                  "cut": int(s.cut), "test_weeks": round(weeks[s.key], 1),
                                  "no_prediction_rows": {"A": int((~np.isfinite(pA[s.key]["p_long"])).sum()),
                                                         "AB": int((~np.isfinite(pAB[s.key]["p_long"])).sum()),
                                                         "B": int((~np.isfinite(pB[s.key]["P"]).all(axis=1)).sum())}}
        log.info("%s done in %.0fs", tf, time.time() - t_tf)
        del items
        if checkpoint is not None:
            try:
                checkpoint({**_summarise(results, weeks), "series": series_info, "skipped": skipped, "choices": choices,
                            "model_skill": model_skill, "fits": fitlog, "partial": True})
            except Exception as exc:
                log.warning("checkpoint failed: %s", exc)
    return {**_summarise(results, weeks), "series": series_info, "skipped": skipped, "choices": choices,
            "model_skill": model_skill, "fits": fitlog}


def _summarise(results: dict[str, dict[str, list]], weeks: dict[str, float]) -> dict[str, Any]:
    from . import research_engine as RE
    names = list(results)
    tables = {v: RE._table(results[v], weeks) for v in names} if weeks else {}
    boot = {v: {"by_series": _boot(results["current"], results[v], "series"),
                "by_week": _boot(results["current"], results[v], "week")} for v in names if v != "current"}
    verdict = {}
    if tables:
        c = tables["current"]["overall"]
        for v in ("A", "B", "AB"):
            o = tables[v]["overall"]
            better = bool(o["n"] and c["n"] and o["expectancy_r"] is not None and c["expectancy_r"] is not None
                          and o["expectancy_r"] > c["expectancy_r"])
            dd_ok = bool(o["n"] and o["max_drawdown_r"] <= c["max_drawdown_r"] + 1e-9)
            shares = [boot[v][u]["share_better"] for u in ("by_series", "by_week")]
            sure = bool(all(x is not None for x in shares) and min(shares) >= 0.8)
            verdict[v] = {"better_expectancy": better, "drawdown_not_worse": dd_ok, "bootstrap_ge_80": sure,
                          "clear_win": better and dd_ok and sure}
    return {"test": tables, "bootstrap_vs_current": boot, "verdict": verdict}


def run(db_url: str, budget_s: float, cost: float, symbols: list[str] | None = None, tfs: list[str] | None = None,
        diag: bool = True, checkpoint: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    from .db import Database
    from .services.runtime import Runtime

    class _Prov:
        name = "binance"

    db = Database(db_url)
    rt = Runtime(db, _Prov())
    ex = db.one("SELECT exchange, COUNT(*) AS n FROM market_data GROUP BY exchange ORDER BY n DESC LIMIT 1")
    if ex:
        _Prov.name = ex["exchange"]
    syms = symbols or [r["symbol"] for r in db.query("SELECT DISTINCT symbol FROM model_versions WHERE active = 1 ORDER BY symbol")]
    t0 = time.time()
    body = evaluate(rt, syms, tfs or TFS_DEFAULT, t0 + budget_s, cost, diag, checkpoint)
    body.update({"engine_version": ENGINE_VERSION, "cost_pct_round_trip": cost, "tune_share": TUNE_SHARE,
                 "symbols": syms, "timeframes": tfs or TFS_DEFAULT, "seconds": round(time.time() - t0, 1),
                 "learner": "lightgbm" if _lgbm_ok() else "sklearn HistGradientBoosting (lightgbm missing)",
                 "settings": {"chunks": K_CHUNKS, "max_train_per_coin": MAX_TRAIN_PER_COIN,
                              "max_train_pooled": MAX_TRAIN_POOLED, "horizon_bars": H, "embargo_bars": H + 1,
                              "threshold_grid": THR_GRID, "zscore_window": ZWIN},
                 "method": __doc__.strip().split("\n\n", 1)[1] if __doc__ else None,
                 "approximations": [
                     "CURRENT is the research_engine replica of the live pipeline (see its approximations): ensemble "
                     "agreement checks treated as passed, no order book, fixed TP ladder 1R / 1.75R / 2.5R",
                     "new models use the base feature set + BTC context + the higher-timeframe block (no futures / crowd "
                     "columns: too little history); BTC uses its own bars as BTC context",
                     "B: the edge flag that gates the ml term of the composite is re-judged for the new probabilities on the "
                     "tuning rows (Brier below the class base rates) instead of the bundle's edge test",
                     "A / A+B use market entries (the label's entry); no grades, so the pooled filter2 is not applied",
                     "pooled fits keep the most recent rows when above max_train_pooled (logged in fits[].subsampled_from)"]})
    return body
