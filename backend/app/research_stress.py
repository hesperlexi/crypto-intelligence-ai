"""`python -m app.research aiv3stress`: do the AI add-ons PROTECT in difficult markets? (owner follow-up, 4 Nov 2026).
READ-ONLY, EXPLORATORY.

Same harness as research_v3 (live record rules, net of the 0.15 % round trip and stored funding), on the FULL out-of-sample
history of every coin / timeframe (crash days are rare, so this overlaps the earlier v3 development AND holdout: the
results are exploratory, not a promotion test). The baseline (OFF) is the current pipeline (grade-A-only timeframes as
live, live entry rule). Each add-on is switched ON on top of it:

* trade_filter v1, runner model, target model (per coin / timeframe) and trade_filter2 (pooled per timeframe) are
  CROSS-FITTED in time: trained on one half of the out-of-sample history (labels purged by the trade horizon), scoring the
  calls of the other half - so no call is scored by a model that saw its outcome. "deployed" = only where the piece's own
  exam switches it on (as live); "forced" = the fitted piece applied even when its exam says off (its chosen keep share,
  else 50 % / 30 %).
* deriv / htf gates: on every series where the stored gate is ON, the base model is retrained (fast model set) with and
  without the futures / higher-timeframe features; both versions go through the same pipeline and harness.

Stress windows (defined on BTC, applied to the decision time of each call):
  btc_drop       BTC daily close-to-close <= -5 %: that day and the following 3 days;
  high_vol       BTC ATR % on the call's timeframe in the top decile of the analysed span (per timeframe);
  reversal       |BTC 24 h return| >= 4 % followed within 48 h by an opposite move >= 3 %: the 24 h before through 48 h after;
  liq_cascade    BTC open interest -5 % or more within 24 h with |BTC 24 h return| >= 3 % (only where OI history exists);
  any_stress     union; normal = none of them.
`volatility-only` mode: the add-on is ON only while an EX-ANTE stress state holds at the decision (BTC ATR % above its
expanding 90th percentile on that timeframe, or a >= 5 % BTC daily drop in the last 3 completed days), OFF otherwise.
Per add-on x timeframe x window: trades, net R / trade, worst trade, max drawdown (R), ON - OFF with a block-bootstrap
95 % CI (coin x week), loss avoided (filters: minus the net R of the OFF trades the add-on blocked; exit add-ons and gates:
sum of ON minus OFF), one-sided p (ON better), Holm across add-ons x modes x windows x timeframes.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import numpy as np
import pandas as pd

from .config import ENGINE_VERSION, MODEL_TIMEFRAMES
from .data.base import tf_ms
from .redact import error_text

log = logging.getLogger("research.stress")
DAY = 86_400_000
HOUR = 3_600_000
WINDOWS = ("btc_drop", "high_vol", "reversal", "liq_cascade", "any_stress", "normal", "all")
STRESS = ("btc_drop", "high_vol", "reversal", "liq_cascade", "any_stress")
FORCED_KEEP = {"trade_filter": 0.5, "runner_model": 0.3, "trade_filter2": 0.5}


# ---- cross-fitted add-ons per series ------------------------------------------------------------------------------------

def _labels_v1(X, P, rows, hi, lo, cl, at, cost):
    from .ml import trade_filter as TFv1
    side = np.where(P[:, 2] >= P[:, 0], 1, -1)
    margin = np.abs(P[:, 2] - P[:, 0])
    R = np.array([TFv1.trade_r(hi, lo, cl, at, int(r), int(s), cost) if m >= TFv1.MIN_MARGIN else None
                  for r, s, m in zip(rows, side, margin)], dtype=object)
    ok = np.array([v is not None for v in R]) & np.isfinite(X).all(axis=1)
    return side, ok, R


def _forced_v1(X, P, rows, hi, lo, cl, at, cost, keep):
    from .ml import trade_filter as TFv1
    side, ok, R = _labels_v1(X, P, rows, hi, lo, cl, at, cost)
    if ok.sum() < 200:
        return None
    F = TFv1._features(X[ok], P[ok], side[ok])
    y = (R[ok].astype(float) > 0).astype(int)
    if len(set(y)) < 2:
        return None
    m = TFv1._model().fit(F, y)
    return {"model": m, "threshold": float(np.quantile(m.predict_proba(F)[:, 1], 1 - keep))}


def _forced_runner(X, P, rows, hi, lo, cl, at, cost, keep):
    from .ml import runner_model as RM, trade_filter as TFv1
    side = np.where(P[:, 2] >= P[:, 0], 1, -1)
    margin = np.abs(P[:, 2] - P[:, 0])
    keep_k, y = [], []
    for k, (i, s, m) in enumerate(zip(rows, side, margin)):
        i = int(i)
        if m < TFv1.MIN_MARGIN or i + RM.HORIZON >= len(cl) or not np.isfinite(at[i]) or at[i] <= 0 or not np.isfinite(X[k]).all():
            continue
        entry, dist = cl[i], RM.STOP_ATR * at[i]
        a, _ = RM.exits_r(hi, lo, cl, entry, dist, int(s), i, RM.HORIZON)
        b, _ = RM.exits_r(hi, lo, cl, entry, dist, int(s), i, RM.HORIZON, run=True)
        keep_k.append(k)
        y.append(int(b > a))
    if len(keep_k) < 200 or len(set(y)) < 2:
        return None
    kk = np.array(keep_k)
    F = TFv1._features(X[kk], P[kk], side[kk])
    m = RM._model().fit(F, np.array(y))
    return {"model": m, "threshold": float(np.quantile(m.predict_proba(F)[:, 1], 1 - keep)), "run_r": RM.RUN_R}


def _forced_target(X, P, rows, hi, lo, cl, at):
    from .ml import target_model as TM, trade_filter as TFv1
    side = np.where(P[:, 2] >= P[:, 0], 1, -1)
    margin = np.abs(P[:, 2] - P[:, 0])
    labs, kk = [], []
    for k, (r, s, m) in enumerate(zip(rows, side, margin)):
        if m < TFv1.MIN_MARGIN or not np.isfinite(X[k]).all():
            continue
        lab = TM.reach_labels(hi, lo, cl, at, int(r), int(s))
        if lab is not None:
            labs.append(lab)
            kk.append(k)
    if len(kk) < 200:
        return None
    kk = np.array(kk)
    F = TFv1._features(X[kk], P[kk], side[kk])
    Y = np.vstack(labs)
    models = {}
    for j, r in enumerate(TM.R_GRID):
        if Y[:, j].sum() >= 20 and len(set(Y[:, j])) == 2:
            mm = TM._model().fit(F, Y[:, j])
            models[r] = {"model": mm, "mean": float(mm.predict_proba(F)[:, 1].mean())}
    return {"enabled": True, "models": models} if models else None


def crossfit_pieces(bundle, ctx, fr, frames, btc, deriv, recs, step, rule, br, skip: bool = False) -> dict[str, Any]:
    """Two time halves of the out-of-sample rows: pieces trained on one half (labels purged by the trade horizon)
    score the pipeline calls of the other half. Results are written into each rec under 'xf'."""
    from . import research_v3 as R3
    from .features.dataset import make_features
    from .ml import runner_model, target_model, trade_filter, trainer
    from .services import tracking as T
    if skip:
        return {"skipped": True}
    names = bundle.get("feature_names") or []
    htf = frames.get(bundle["uses_htf"]) if bundle.get("uses_htf") else None
    Xb = make_features(fr, btc if bundle.get("uses_btc") and ctx.symbol != "BTC/USDT" else None, htf, deriv)
    if not names or any(c not in Xb.columns for c in names):
        return {"error": "model features unavailable"}
    Xb = Xb[names].to_numpy(float)
    ind = fr.ind
    hi, lo, cl, at = (ind[c].to_numpy(float) for c in ("high", "low", "close", "atr"))
    cost = trainer._cost()
    purge = max(trade_filter.HORIZON + 1, T.horizon_for(ctx.tf) + 1) * step
    mid = int(np.median(ctx.ts))
    info: dict[str, Any] = {}
    halves = {"first": (ctx.ts <= mid - purge, lambda t: t >= mid),
              "second": (ctx.ts >= mid + purge, lambda t: t < mid)}
    for hname, (trmask, scores) in halves.items():
        rows = ctx.rows[trmask]
        Xd, Pd = Xb[rows], ctx.P[trmask]
        dep, forced = {}, {}
        for nm, fn in (("trade_filter", lambda: trade_filter.train(Xd, Pd, rows, hi, lo, cl, at, cost)),
                       ("runner_model", lambda: runner_model.train(Xd, Pd, rows, hi, lo, cl, at, cost)),
                       ("target_model", lambda: target_model.train(Xd, Pd, rows, hi, lo, cl, at))):
            try:
                dep[nm] = fn()
            except Exception as exc:
                dep[nm] = {"enabled": False, "reason": error_text(exc, 100)}
        try:
            forced["trade_filter"] = _forced_v1(Xd, Pd, rows, hi, lo, cl, at, cost,
                                                dep["trade_filter"].get("keep_fraction") or FORCED_KEEP["trade_filter"])
            forced["runner_model"] = _forced_runner(Xd, Pd, rows, hi, lo, cl, at, cost,
                                                    dep["runner_model"].get("keep_fraction") or FORCED_KEEP["runner_model"])
            forced["target_model"] = _forced_target(Xd, Pd, rows, hi, lo, cl, at)
        except Exception as exc:
            info[f"{hname}_forced_error"] = error_text(exc, 120)
        info[hname] = {nm: bool(v.get("enabled")) for nm, v in dep.items()} | {"train_rows": int(trmask.sum())}
        for r in recs:
            if not r["pipe"] or not scores(r["ts"]) or "_kw" not in r:
                continue
            x = Xb[r["pos"]]
            P = ctx.P[r["j"]]
            probs = {"down": float(P[0]), "neutral": float(P[1]), "up": float(P[2])}
            xf = r.setdefault("xf", {})
            for mode, pieces in (("dep", dep), ("forced", forced)):
                tfp = pieces.get("trade_filter")
                if mode == "forced" and tfp:
                    tfp = {**tfp, "enabled": True, "keep_fraction": None}
                tv = trade_filter.score(tfp, x, probs) if tfp else None
                xf[f"v1_{mode}"] = None if not tv else bool((tv["p_long"] if r["side"] > 0 else tv["p_short"]) >= tv["threshold"])
                rp = pieces.get("runner_model")
                if mode == "forced" and rp:
                    rp = {**rp, "enabled": True}
                rv = runner_model.score(rp, x, probs) if rp else None
                run_rr = None
                if rv and (rv["p_long"] if r["side"] > 0 else rv["p_short"]) >= rv["threshold"]:
                    run_rr = float(rv.get("run_r") or 4.0)
                    xf[f"runner_{mode}"] = R3._sim_fields(R3.simulate_call(runner_rr=run_rr, mode=rule[0], k=rule[1], **r["_kw"]))
                tp = pieces.get("target_model")
                lf = target_model.lifts(tp, x, probs) if tp else None
                if lf:
                    pl, zones = r["_tg"]
                    tg = R3.pick_targets(br, r["pos"], r["side"], pl["dist"], float(ctx.atr[r["j"]]),
                                         R3.walls_of(zones, r["side"], pl["ideal"], pl["dist"]),
                                         lift=lf["long" if r["side"] > 0 else "short"])
                    if (1.0, tg["m2"], tg["m3"]) != tuple(r["_kw"]["mults"]):
                        kw = {**r["_kw"], "mults": (1.0, tg["m2"], tg["m3"])}
                        xf[f"target_{mode}"] = R3._sim_fields(R3.simulate_call(mode=rule[0], k=rule[1], **kw))
    return {"crossfit": info, "mid": mid}


# ---- stress windows ------------------------------------------------------------------------------------------------------------

def _merge(iv: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(int(a), int(b)) for a, b in out]


def in_windows(ts: np.ndarray, iv: list[tuple[int, int]]) -> np.ndarray:
    if not iv:
        return np.zeros(len(ts), bool)
    a = np.array([x for x, _ in iv], np.int64)
    b = np.array([y for _, y in iv], np.int64)
    k = np.searchsorted(a, ts, side="right") - 1
    return (k >= 0) & (ts < b[np.maximum(k, 0)])


def market_windows(d1: pd.DataFrame, h1: pd.DataFrame, oi: pd.DataFrame | None) -> dict[str, Any]:
    """Interval lists (start, end) in ms of the market-wide stress windows, from BTC candles / open interest."""
    out: dict[str, Any] = {}
    c = d1["close"].to_numpy(float)
    t = d1["ts"].to_numpy(np.int64)
    ret = np.r_[np.nan, c[1:] / c[:-1] - 1]
    drops = t[ret <= -0.05]
    out["btc_drop"] = _merge([(int(x), int(x) + 4 * DAY) for x in drops])
    out["btc_drop_days"] = [int(x) for x in drops]
    hc, hh, hl, ht = (h1[k].to_numpy(float if k != "ts" else np.int64) for k in ("close", "high", "low", "ts"))
    r24 = np.full(len(hc), np.nan)
    r24[24:] = hc[24:] / hc[:-24] - 1
    rev = []
    for i in np.flatnonzero(np.abs(np.nan_to_num(r24)) >= 0.04):
        j = min(len(hc), i + 49)
        if j <= i + 1:
            continue
        if r24[i] > 0 and np.min(hl[i + 1:j]) / hc[i] - 1 <= -0.03:
            rev.append((int(ht[i]) - 23 * HOUR, int(ht[i]) + 49 * HOUR))
        elif r24[i] < 0 and np.max(hh[i + 1:j]) / hc[i] - 1 >= 0.03:
            rev.append((int(ht[i]) - 23 * HOUR, int(ht[i]) + 49 * HOUR))
    out["reversal"] = _merge(rev)
    liq = []
    oi_days = 0.0
    if oi is not None and len(oi) and "oi" in oi and oi["oi"].notna().sum() > 48:
        o = oi.dropna(subset=["oi"]).sort_values("ts")
        ots, ov = o["ts"].to_numpy(np.int64), o["oi"].to_numpy(float)
        oi_days = (ots[-1] - ots[0]) / DAY
        k = np.searchsorted(ots, ots - 24 * HOUR)
        ch = ov / ov[np.minimum(k, len(ov) - 1)] - 1
        ih = np.searchsorted(ht, ots, side="right") - 1
        r = np.where(ih >= 0, r24[np.maximum(ih, 0)], np.nan)
        for x in ots[(ch <= -0.05) & (np.abs(np.nan_to_num(r)) >= 0.03)]:
            liq.append((int(x) - 24 * HOUR, int(x) + 24 * HOUR))
    out["liq_cascade"] = _merge(liq)
    out["oi_history_days"] = round(float(oi_days), 1)
    return out


def _days(mask_ts: np.ndarray) -> int:
    return int(len(np.unique(mask_ts // DAY))) if len(mask_ts) else 0


# ---- evaluation -------------------------------------------------------------------------------------------------------------------

def _cell(on: pd.DataFrame, off: pd.DataFrame, blocked_r: float | None, kind: str) -> dict[str, Any]:
    from .ml import meta_v3 as MV, series_sim as S

    def st(t):
        r = t["r_net"].to_numpy(float) if len(t) else np.zeros(0)
        s = S.stats(list(r))
        return {"n": s["n"], "avg_r": s["expectancy_r"], "worst_r": float(r.min()) if len(r) else None,
                "max_dd_r": s["max_drawdown_r"], "total_r": s["total_r"], "win_rate": s["win_rate"]}
    a, b = st(on), st(off)
    out = {"on": a, "off": b}
    if a["n"] and b["n"]:
        f = MV.family_test({"on": (on["r_net"].to_numpy(float), MV.block_keys(on["symbol"], on["ts"]))},
                           bench=(off["r_net"].to_numpy(float), MV.block_keys(off["symbol"], off["ts"])), n_boot=1000)
        x = f["strategies"].get("on") or {}
        out["diff"] = x.get("diff")
        out["diff_ci95"] = x.get("ci95")
        out["p_on_better"] = x.get("p")
    if kind == "filter":
        # minus the net R of the OFF trades this filter blocked (positive = losses avoided)
        out["loss_avoided_r"] = -blocked_r if blocked_r is not None else None
        out["blocked_trades_net_r"] = blocked_r
    else:
        out["loss_avoided_r"] = a["total_r"] - b["total_r"]       # exit add-ons / gates: total ON minus total OFF
    return out


def evaluate_tf(tf: str, series: list[dict[str, Any]], gate_series: dict[str, list[dict[str, Any]]], win: dict[str, Any],
                btc_frame: Any, watch: set[str]) -> dict[str, Any]:
    from . import research_v3 as R3
    from .ml import trade_filter2 as TF2
    from .services import analysis as A
    step = tf_ms(tf)
    df, _, _ = R3._frame(series)
    if df.empty:
        return {"error": "no calls"}
    df = df[df["recorded"].astype(bool)].reset_index(drop=True)
    ts = df["ts"].to_numpy(np.int64)
    current = df["pipe"].astype(bool).to_numpy() & ((df["grade"] == "A").to_numpy() if tf in A.A_ONLY_TFS else True)
    # ---- windows on this timeframe ------------------------------------------------------------------------------
    bi = btc_frame.ind
    bts = (bi["ts"].to_numpy(np.int64) + step)
    atrp = (bi["atr"] / bi["close"]).to_numpy(float)
    span = (bts >= ts.min()) & (bts <= ts.max() + step)
    thr = float(np.nanquantile(atrp[span], 0.9)) if span.any() else np.inf
    k = np.searchsorted(bts, ts, side="right") - 1
    cur_atr = np.where(k >= 0, atrp[np.maximum(k, 0)], np.nan)
    exp_thr = pd.Series(atrp).expanding(min_periods=200).quantile(0.9).to_numpy()
    cur_exp = np.where(k >= 0, exp_thr[np.maximum(k, 0)], np.nan)
    masks = {"btc_drop": in_windows(ts, win["btc_drop"]), "high_vol": np.nan_to_num(cur_atr) >= thr,
             "reversal": in_windows(ts, win["reversal"]), "liq_cascade": in_windows(ts, win["liq_cascade"])}
    masks["any_stress"] = masks["btc_drop"] | masks["high_vol"] | masks["reversal"] | masks["liq_cascade"]
    masks["normal"] = ~masks["any_stress"]
    masks["all"] = np.ones(len(ts), bool)
    drop_days = np.array(win["btc_drop_days"], np.int64)
    recent_drop = np.array([bool(((drop_days + DAY <= t) & (drop_days + 4 * DAY > t)).any()) for t in ts]) if len(drop_days) else np.zeros(len(ts), bool)
    exante = (np.nan_to_num(cur_atr) >= np.nan_to_num(cur_exp, nan=np.inf)) | recent_drop
    hv_bars = bts[span & (atrp >= thr)]
    days = {"btc_drop": _days(np.array([t for a, b in win["btc_drop"] for t in range(a, b, DAY)], np.int64)),
            "high_vol": _days(hv_bars),
            "reversal": _days(np.array([t for a, b in win["reversal"] for t in range(a, b, HOUR)], np.int64)),
            "liq_cascade": _days(np.array([t for a, b in win["liq_cascade"] for t in range(a, b, HOUR)], np.int64))}
    t0, t1 = int(ts.min()), int(ts.max())
    for kk in ("btc_drop", "reversal", "liq_cascade"):          # only days inside this timeframe's analysed span
        iv = [(max(a, t0), min(b, t1)) for a, b in win[kk] if b > t0 and a < t1]
        days[kk] = _days(np.array([t for a, b in iv for t in range(a, b, HOUR)], np.int64))
    out: dict[str, Any] = {"span": [t0, t1], "stress_days": days, "analysed_days": int((t1 - t0) // DAY),
                           "calls_in_window": {w: int((m & current).sum()) for w, m in masks.items()},
                           "high_vol_threshold_atr_pct": thr * 100, "exante_share": float(exante[current].mean()) if current.any() else None}
    off_trades = R3.trades_of(df, current, step)

    def evaluate_variant(name: str, d2: pd.DataFrame, mask_on: np.ndarray, kind: str, blocked: np.ndarray | None,
                         off_t: pd.DataFrame = off_trades, ts_of=ts, masks_of=masks) -> dict[str, Any]:
        on_t = R3.trades_of(d2, mask_on, step)
        res = {}
        for w in WINDOWS:
            m = masks_of[w]
            on_w = on_t[m[on_t.index.to_numpy()]] if len(on_t) else on_t
            off_w = off_t[m[off_t.index.to_numpy()]] if len(off_t) else off_t
            br = None
            if kind == "filter" and blocked is not None and len(off_t):
                bl = off_w[blocked[off_w.index.to_numpy()]]
                br = float(bl["r_net"].sum())
            res[w] = _cell(on_w, off_w, br, kind)
        return res

    variants: dict[str, Any] = {}
    xf = df["xf"] if "xf" in df else pd.Series([None] * len(df))
    xf = [x if isinstance(x, dict) else {} for x in xf]
    for mode in ("dep", "forced"):
        keep = np.array([x.get(f"v1_{mode}") is not False for x in xf])
        variants[f"trade_filter_v1|{mode}"] = ("filter", df, current & keep, ~keep)
        for nm in ("runner", "target"):
            alt = df.copy()
            use = np.array([bool((x.get(f"{nm}_{mode}") or {}).get("recorded")) for x in xf])
            for col in ("r_net", "closed", "exit", "filled"):
                arr = alt[col].to_numpy(object).copy()
                for i in np.flatnonzero(use):
                    arr[i] = xf[i][f"{nm}_{mode}"].get(col)
                alt[col] = arr
            alt["r_net"] = alt["r_net"].astype(float)
            alt["closed"] = alt["closed"].astype(float)
            alt["filled"] = alt["filled"].astype(bool)
            variants[f"{nm}_model|{mode}"] = ("exit", alt, current, None)
    # trade_filter2: pooled, cross-fitted by time halves of this timeframe
    f2 = df["_tf2"].to_numpy()
    has = np.array([isinstance(v, np.ndarray) for v in f2])
    fin = df["filled"].astype(bool).to_numpy() & np.isfinite(df["r_net"].to_numpy(float))
    mid = int(np.median(ts))
    from .services.tracking import horizon_for
    purge = horizon_for(tf) * step
    k2 = {"dep": np.ones(len(df), bool), "forced": np.ones(len(df), bool)}
    tf2_info = {}
    for hname, trm, scm in (("first", (ts < mid - purge), ts >= mid), ("second", (ts >= mid + purge), ts < mid)):
        rows = np.flatnonzero(trm & has & fin & df["pipe"].astype(bool).to_numpy())
        if len(rows) < 50:
            tf2_info[hname] = {"rows": int(len(rows))}
            continue
        F = np.vstack(f2[rows]).astype(float)
        Rr = df["r_net"].to_numpy(float)[rows]
        fit = TF2.train(F, Rr, ts[rows])
        y = (Rr > 0).astype(int)
        forced = None
        if len(set(y)) == 2:
            mdl = TF2._model().fit(F, y)
            forced = {"model": mdl, "enabled": True,
                      "threshold": float(np.quantile(mdl.predict_proba(F)[:, 1], 1 - (fit.get("keep_fraction") or FORCED_KEEP["trade_filter2"])))}
        tf2_info[hname] = {"rows": int(len(rows)), "enabled": bool(fit.get("enabled")), "reason": fit.get("reason")}
        sc_rows = np.flatnonzero(scm & has)
        for mode, f in (("dep", fit if fit.get("enabled") else None), ("forced", forced)):
            if f is None:
                continue
            for i in sc_rows:
                s = TF2.score(f, np.asarray(f2[i], float))
                if s is not None and s < f["threshold"]:
                    k2[mode][i] = False
    for mode in ("dep", "forced"):
        variants[f"trade_filter2|{mode}"] = ("filter", df, current & k2[mode], ~k2[mode])
    # volatility-only mode: each add-on ON only in an ex-ante stress state
    for name, (kind, d2, m_on, blocked) in list(variants.items()):
        if kind == "filter":
            m2 = np.where(exante, m_on, current)
            variants[f"{name}|stress_only"] = (kind, d2, m2, blocked & exante if blocked is not None else None)
        else:
            alt = d2.copy()
            for col in ("r_net", "closed", "exit", "filled"):
                arr = alt[col].to_numpy(object).copy()
                arr[~exante] = df[col].to_numpy(object)[~exante]
                alt[col] = arr
            alt["r_net"], alt["closed"] = alt["r_net"].astype(float), alt["closed"].astype(float)
            alt["filled"] = alt["filled"].astype(bool)
            variants[f"{name}|stress_only"] = (kind, alt, current, None)
    res = {}
    for name, (kind, d2, m_on, blocked) in variants.items():
        try:
            res[name] = evaluate_variant(name, d2, m_on, kind, blocked)
        except Exception as exc:
            res[name] = {"error": error_text(exc, 200)}
    # deriv / htf gates: ON vs OFF base models on the gated series only
    for gname, pair in gate_series.items():
        on_s = [s for s in pair if s.get("tf") == tf and s["key"].endswith("|on") and s.get("recs")]
        off_s = [s for s in pair if s.get("tf") == tf and s["key"].endswith("|off") and s.get("recs")]
        if not on_s or not off_s:
            continue
        try:
            d_on, _, _ = R3._frame(on_s)
            d_off, _, _ = R3._frame(off_s)
            gm = {}
            for dd in (d_on, d_off):
                dd.reset_index(drop=True, inplace=True)
            def mk(dd):
                t_ = dd["ts"].to_numpy(np.int64)
                kk_ = np.searchsorted(bts, t_, side="right") - 1
                ca = np.where(kk_ >= 0, atrp[np.maximum(kk_, 0)], np.nan)
                m = {"btc_drop": in_windows(t_, win["btc_drop"]), "high_vol": np.nan_to_num(ca) >= thr,
                     "reversal": in_windows(t_, win["reversal"]), "liq_cascade": in_windows(t_, win["liq_cascade"])}
                m["any_stress"] = m["btc_drop"] | m["high_vol"] | m["reversal"] | m["liq_cascade"]
                m["normal"] = ~m["any_stress"]
                m["all"] = np.ones(len(t_), bool)
                cur = dd["pipe"].astype(bool).to_numpy() & ((dd["grade"] == "A").to_numpy() if tf in A.A_ONLY_TFS else True)
                return m, cur
            m_on, c_on = mk(d_on)
            m_off, c_off = mk(d_off)
            t_on, t_off = R3.trades_of(d_on, c_on, step), R3.trades_of(d_off, c_off, step)
            for w in WINDOWS:
                a = t_on[m_on[w][t_on.index.to_numpy()]] if len(t_on) else t_on
                b = t_off[m_off[w][t_off.index.to_numpy()]] if len(t_off) else t_off
                gm[w] = _cell(a, b, None, "gate")
            res[f"{gname}|dep"] = gm
            res[f"{gname}|dep"]["series"] = sorted({s["key"].rsplit("|", 1)[0] for s in on_s})
        except Exception as exc:
            res[f"{gname}|dep"] = {"error": error_text(exc, 200)}
    out["variants"] = res
    out["trade_filter2_crossfit"] = tf2_info
    out["off_all"] = R3.summarize(off_trades, max((t1 - t0) / (30.44 * DAY), 1e-9), watch)
    return out


def holm_all(per_tf: dict[str, Any]) -> dict[str, Any]:
    from .ml import meta_v3 as MV
    p = {}
    for tf, v in per_tf.items():
        for name, cells in (v.get("variants") or {}).items():
            if not isinstance(cells, dict) or "error" in cells:
                continue
            for w in STRESS + ("normal",):
                c = cells.get(w) or {}
                if c.get("p_on_better") is not None:
                    p[f"{tf}|{name}|{w}"] = c["p_on_better"]
    return MV.holm(p)


def verdicts(per_tf: dict[str, Any], holm: dict[str, Any]) -> dict[str, Any]:
    """Per add-on: 'yes' if ON beats OFF in a stress window with Holm p < 0.05 (any timeframe / mode); 'no' if in the
    any_stress window the ON - OFF estimate is <= 0 on every timeframe with >= 20 OFF trades there; else 'inconclusive'."""
    out = {}
    addons = sorted({n.split("|")[0] for v in per_tf.values() for n in (v.get("variants") or {})})
    for a in addons:
        sig, ests = [], []
        for tf, v in per_tf.items():
            for name, cells in (v.get("variants") or {}).items():
                if name.split("|")[0] != a or not isinstance(cells, dict) or "error" in cells:
                    continue
                for w in STRESS:
                    hp = holm.get(f"{tf}|{name}|{w}")
                    c = cells.get(w) or {}
                    if hp is not None and hp < 0.05 and (c.get("diff") or 0) > 0:
                        sig.append(f"{tf} {name} {w}")
                c = cells.get("any_stress") or {}
                if (c.get("off") or {}).get("n", 0) >= 20 and c.get("diff") is not None:
                    ests.append((tf, name, round(c["diff"], 3), c.get("diff_ci95")))
        verdict = "yes" if sig else ("no" if ests and all(e[2] <= 0 for e in ests) else "inconclusive")
        out[a] = {"protects_in_stress": verdict, "significant": sig, "any_stress_estimates": ests}
    return out


# ---- orchestration --------------------------------------------------------------------------------------------------------------

_W: dict[str, Any] = {}


def _job(args) -> list[dict[str, Any]]:
    from . import research_engine as RE, research_v3 as R3
    kind, symbol, tfs, cfg, deadline = args
    rt = R3._W["rt"]
    cfg = {**cfg, "news": RE._news_fn(rt.db)}
    cache: dict = {}
    res = []
    for tf in tfs:
        if time.time() > deadline:
            res.append({"key": f"{symbol} {tf}", "skip": "time budget"})
            continue
        try:
            if kind == "addons":
                res.append(R3.build_series(rt, symbol, tf, cfg, cache))
            else:
                res.extend(gate_pair(rt, symbol, tf, kind, cfg, cache))
        except Exception as exc:
            log.exception("%s %s %s", kind, symbol, tf)
            res.append({"key": f"{symbol} {tf}", "error": error_text(exc, 300), "kind": kind})
    return res


def gate_pair(rt, symbol: str, tf: str, gate: str, cfg: dict, cache: dict) -> list[dict[str, Any]]:
    """Fast base models with and without the gated inputs (everything else as the live bundle), both replayed."""
    from . import research_engine as RE, research_v3 as R3
    from .features.dataset import HTF_OF
    from .ml import trainer
    live = trainer.load_bundle(symbol, tf, rt.db) or {}
    frames = cache.get(symbol) or RE._series_frames(rt, symbol, tf)
    cache[symbol] = frames
    fr = frames[tf]
    btc = None if symbol == "BTC/USDT" else rt.frame("BTC/USDT", tf)
    htf_live = frames.get(live.get("uses_htf")) if live.get("uses_htf") else None
    deriv_live = rt.deriv_frame(symbol) if any(c.startswith(("fund_", "prem", "deriv_", "oi_chg", "ls_", "taker_", "crowd_")) for c in live.get("feature_names") or []) else None
    out = []
    for flag in ("on", "off"):
        if gate == "deriv_gate":
            htf, deriv = htf_live, (rt.deriv_frame(symbol) if flag == "on" else None)
        else:
            htf, deriv = (frames.get(HTF_OF.get(tf)) if flag == "on" else None), deriv_live
        t0 = time.time()
        b = trainer.train_bundle(symbol, tf, fr, btc, fast=True, htf=htf, deriv=deriv)
        r = R3.build_series(rt, symbol, tf, {**cfg, "skip_pieces": True}, cache, bundle=b, key=f"{symbol} {tf}|{flag}")
        r["gate"], r["train_seconds"] = gate, round(time.time() - t0, 1)
        out.append(r)
    return out


def run(db_url: str, budget_s: float = 14400, symbols: list[str] | None = None, tfs: list[str] | None = None,
        workers: int | None = None) -> dict[str, Any]:
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor

    from . import research_v3 as R3
    from .data import derivs
    from .db import Database, loads
    from .services.runtime import Runtime
    t0 = time.time()
    db = Database(db_url)
    ex = db.one("SELECT exchange, COUNT(*) AS n FROM market_data GROUP BY exchange ORDER BY n DESC LIMIT 1")
    exchange = ex["exchange"] if ex else "binance"

    class _Prov:
        name = exchange
    rt = Runtime(db, _Prov())
    tfs = tfs or list(MODEL_TIMEFRAMES)
    syms = symbols or [r["symbol"] for r in db.query("SELECT DISTINCT symbol FROM model_versions WHERE active = 1 ORDER BY symbol")]
    watch = set(rt.symbols()) or set(__import__("app.worker", fromlist=["TEST_COINS"]).TEST_COINS)
    far = 10 ** 15                                      # no holdout here: the direction reference uses all rows
    cfg = {"cuts": {tf: far for tf in tfs}, "entry_rules": {tf: R3.stored_entry_rule(db, tf) for tf in tfs}, "symbols": syms,
           "stress": True, "pipe_only": True}
    gates = []
    for prefix, gname in (("deriv_gate2|", "deriv_gate"), ("htf_gate1|", "htf_gate")):
        for r in db.query("SELECT key, value FROM app_settings WHERE key LIKE ?", (prefix + "%",)):
            v = loads(r["value"], {}) or {}
            _, s, tf = r["key"].split("|")
            if v.get("on") and tf in tfs and s in syms:
                gates.append((gname, s, tf))
    deadline = t0 + budget_s * 0.8
    tasks = [("addons", s, [tf for tf in ("3d", "1d", "12h", "4h", "1h", "15m") if tf in tfs], cfg, deadline) for s in syms]
    tasks += [(g, s, [tf], cfg, deadline) for g, s, tf in gates]
    nw = workers or max(1, min(os.cpu_count() or 1, 4))
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(nw, mp_context=mp.get_context("fork"), initializer=R3._init_worker,
                             initargs=(db_url, exchange)) as pool:
        for res in pool.map(_job, tasks):
            results.extend(res)
    t1 = time.time()
    ok = [r for r in results if "recs" in r]
    addon = [r for r in ok if "gate" not in r]
    gate_res = {g: [r for r in ok if r.get("gate") == g] for g in ("deriv_gate", "htf_gate")}
    win = market_windows(rt.candles("BTC/USDT", "1d"), rt.candles("BTC/USDT", "1h"), derivs.load_all(db, "BTC/USDT"))
    per_tf = {}
    for tf in tfs:
        ser = [r for r in addon if r["tf"] == tf]
        if not ser:
            continue
        try:
            per_tf[tf] = evaluate_tf(tf, ser, gate_res, win, rt.frame("BTC/USDT", tf), watch)
        except Exception as exc:
            log.exception("stress %s", tf)
            per_tf[tf] = {"error": error_text(exc, 400)}
    hm = holm_all(per_tf)
    for tf, v in per_tf.items():
        for name, cells in (v.get("variants") or {}).items():
            if isinstance(cells, dict):
                for w in STRESS + ("normal",):
                    if isinstance(cells.get(w), dict):
                        cells[w]["p_holm"] = hm.get(f"{tf}|{name}|{w}")
    return {"engine_version": ENGINE_VERSION, "method": (__doc__ or "").strip(), "exploratory": True,
            "note": "full out-of-sample history: overlaps the v3 development AND holdout periods; crash days are rare",
            "windows": {k: (len(v) if isinstance(v, list) else v) for k, v in win.items() if k != "btc_drop_days"},
            "btc_drop_days": len(win["btc_drop_days"]), "gated_series": [f"{g} {s} {tf}" for g, s, tf in gates],
            "gate_runs": {g: [{k: r.get(k) for k in ("key", "train_seconds", "pipe_calls")} for r in v] for g, v in gate_res.items()},
            "per_timeframe": per_tf, "holm_tests": len(hm), "verdicts": verdicts(per_tf, hm),
            "series": {r["key"]: {"pipe_calls": r.get("pipe_calls"), "crossfit": (r.get("old_pieces") or {}).get("crossfit"),
                                  "error": (r.get("old_pieces") or {}).get("error")} for r in addon},
            "skipped": [{k: r.get(k) for k in ("key", "skip", "error", "kind")} for r in results if "recs" not in r],
            "seconds": {"series": round(t1 - t0, 1), "total": round(time.time() - t0, 1)}, "workers": nw}
