"""v2.78 market-turn study (read-only; owner, 23 Nov 2026: "detect a market turn, skip signals for some time and close the
trades we can still win - train the AI for this").

Same unseen calls as every study (research_caps.collect: walk-forward out-of-sample test calls of every series with the live
guards, honest entry, record exits, costs + funding), baseline = today's live pipeline (same-side limit 12 + the
capital-protection package: drift, abnormal volatility, 3R day / 6R week loss stop). Each variant changes two things:

* PAUSE  - no new call against a fresh turn (an event on the other side within the last `pause_h` hours);
* CLOSE  - a running call is closed at the close of the hour the turn is detected: all of them (`close_all`), or only the
           ones that are in profit after costs at that moment (`close_profit`; losing ones keep their stop).

Turn detectors (all causal, from candles closed before the moment they act):
* `btc_break`  BTC 1h closes above the highest high of the previous 48 hours (up turn) / below the lowest low (down turn);
* `btc_regime` BTC 4h trend regime (EMA50 +- 0.5 ATR with slope) switches into trend_up / trend_down;
* `coin_break` the call's own coin closes a 4h candle beyond its previous 12-candle (2-day) range against the call;
* `ai`         an AI model (gradient boosting) trained ONLY on BTC hours before the test period starts: probability that BTC
               moves +2 % (up turn) / -2 % (down turn) over the next 24 h, from returns, trend distance, slope, RSI,
               breakouts, volatility and market breadth (share of watchlist coins above their 4h EMA21). An event = a
               probability in the top 10 % of its own training scores (fixed before the test, never tuned on it).
Primary variant (declared before running): ai + pause 24 h + close_profit. Every variant is judged by research_verdict
(PASS = better in both halves, drawdown <= 15 % deeper, week-block bootstrap >= 80 %, >= 100 calls affected).
python -m app.research_turn --budget 14400 --out x.json"""
from __future__ import annotations

import argparse
import json
import time
from typing import Any

import numpy as np
import pandas as pd

H = 3_600_000
DAY = 24 * H
PRIMARY = "ai|pause24|close_profit"


# ---- re-follow one call, closed at time T -------------------------------------------------------------------------------
def early(t: dict[str, Any], T: int) -> dict[str, Any] | None:
    """The trade closed at the close of the last candle that closed by T (targets / stop hit before T count as usual).
    None when the entry had not filled by T (then the call would not have been taken)."""
    from .config import settings
    from .engine.futures import DEFAULT_FUNDING_RATE
    from .ml import series_policy as SP
    from .ml import series_sim as S
    from .data.base import tf_ms
    ctx, paths, pl, mode = t["_sim"]
    j = int(t["j"])
    step = tf_ms(ctx.tf)
    start = int(ctx.decision_ts[j])
    end = min(start + SP.HORIZON_BARS * step, T)
    if end <= start:
        return None
    w = paths.window(start, end)
    if w is None:
        return None
    ts, hi, lo, cl, ms = w
    op = getattr(paths, "last_open", None)
    bar = ms or step
    keep = ts + bar <= T                                  # only candles closed by T
    if not keep.any():
        return None
    ts, hi, lo, cl = ts[keep], hi[keep], lo[keep], cl[keep]
    op = op[:len(keep)][keep] if op is not None and len(op) == len(keep) else None
    window = max(1, int(round(settings.fill_window_bars * step / bar)))
    side = int(t["side"])
    f = S.fill(mode, side, float(ctx.close[j]), float(ctx.atr[j]), pl, hi, lo, cl, window, 0.0)
    if f is None:
        return None
    i0, entry, first = f
    stop = pl["stop"]
    if side * (entry - stop) <= 0:
        return None
    out = S.follow(side, entry, stop, S.ladder(side, entry, stop), hi[i0:], lo[i0:], cl[i0:], first_is_fill=first,
                   complete=True, open_=op[i0:] if op is not None else None)
    if out is None:
        return None
    closed = int(ts[i0 + out.exit_idx]) + bar
    r = out.net_r(settings.research_cost_pct)
    hours = max(0.0, (closed - int(t["ts"])) / H)
    fund = side * hours * DEFAULT_FUNDING_RATE / 8 * 100
    r -= fund / out.risk_pct if out.risk_pct else 0.0
    return {"r": float(r), "closed_ts": closed, "status": out.status, "early": True}


# ---- turn events ----------------------------------------------------------------------------------------------------------
def _ema(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def _atr(h, l, c, n=14):
    prev = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - prev), abs(l - prev)))
    return pd.Series(tr).rolling(n, min_periods=1).mean().to_numpy()


def btc_frames(rt: Any) -> tuple[pd.DataFrame, pd.DataFrame]:
    h1 = rt.candles("BTC/USDT", "1h").reset_index(drop=True)
    h4 = rt.candles("BTC/USDT", "4h").reset_index(drop=True)
    return h1, h4


def events_break(h1: pd.DataFrame, look: int = 48) -> tuple[np.ndarray, np.ndarray]:
    c, h, l = (h1[k].to_numpy(float) for k in ("close", "high", "low"))
    hh = pd.Series(h).shift(1).rolling(look).max().to_numpy()
    ll = pd.Series(l).shift(1).rolling(look).min().to_numpy()
    close_ts = h1["ts"].to_numpy(np.int64) + H
    return close_ts[c > hh], close_ts[c < ll]


def events_regime(h4: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    c, h, l = (h4[k].to_numpy(float) for k in ("close", "high", "low"))
    ema, atr = _ema(c, 50), _atr(h, l, c)
    slope = ema - np.r_[ema[:6], ema[:-6]]
    up = (c > ema + 0.5 * atr) & (slope > 0)
    dn = (c < ema - 0.5 * atr) & (slope < 0)
    close_ts = h4["ts"].to_numpy(np.int64) + 4 * H
    up_ev = up & ~np.r_[False, up[:-1]]
    dn_ev = dn & ~np.r_[False, dn[:-1]]
    return close_ts[up_ev], close_ts[dn_ev]


def breadth_hourly(rt: Any, syms: list[str], hours: np.ndarray) -> np.ndarray:
    """Share of watchlist coins whose last closed 4h candle closed above its EMA21, at each hour close in `hours`."""
    acc = np.zeros(len(hours))
    cnt = np.zeros(len(hours))
    for s in syms:
        try:
            d = rt.candles(s, "4h")
        except Exception:
            continue
        if d is None or len(d) < 60:
            continue
        c = d["close"].to_numpy(float)
        above = (c > _ema(c, 21)).astype(float)
        cts = d["ts"].to_numpy(np.int64) + 4 * H
        i = np.searchsorted(cts, hours, side="right") - 1
        ok = i >= 21
        acc[ok] += above[i[ok]]
        cnt[ok] += 1
    return np.where(cnt > 0, acc / np.maximum(cnt, 1), np.nan)


def ai_features(h1: pd.DataFrame, breadth: np.ndarray) -> pd.DataFrame:
    c, h, l = (h1[k].to_numpy(float) for k in ("close", "high", "low"))
    s = pd.Series(c)
    atr = _atr(h, l, c, 24)
    f = pd.DataFrame(index=h1.index)
    for n in (1, 4, 12, 24, 72):
        f[f"ret{n}"] = s.pct_change(n).to_numpy()
    for n in (21, 55, 200):
        e = _ema(c, n)
        f[f"dist_ema{n}"] = (c - e) / np.maximum(atr, 1e-9)
        f[f"slope_ema{n}"] = (e - np.r_[e[:12], e[:-12]]) / np.maximum(atr, 1e-9)
    d = s.diff()
    up, dn = d.clip(lower=0).rolling(14).mean(), (-d.clip(upper=0)).rolling(14).mean()
    f["rsi14"] = (100 - 100 / (1 + up / dn.replace(0, np.nan))).to_numpy()
    for n in (24, 72):
        hh = pd.Series(h).shift(1).rolling(n).max().to_numpy()
        ll = pd.Series(l).shift(1).rolling(n).min().to_numpy()
        f[f"pos{n}"] = (c - ll) / np.maximum(hh - ll, 1e-9)
    f["vol_ratio"] = pd.Series(atr).to_numpy() / np.maximum(pd.Series(atr).rolling(24 * 7).mean().to_numpy(), 1e-9)
    f["breadth"] = breadth
    f["breadth_chg12"] = pd.Series(breadth).diff(12).to_numpy()
    return f


def ai_events(h1: pd.DataFrame, feats: pd.DataFrame, test_start: int, move: float = 0.02, horizon: int = 24,
              q: float = 0.90) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Train on hours whose 24 h outcome was known before the test began; events in the test period = score above the
    q-quantile of the training scores."""
    from sklearn.ensemble import HistGradientBoostingClassifier
    c = h1["close"].to_numpy(float)
    close_ts = h1["ts"].to_numpy(np.int64) + H
    fwd = pd.Series(c).shift(-horizon).to_numpy() / c - 1
    y_up = (fwd >= move).astype(int)
    y_dn = (fwd <= -move).astype(int)
    X = feats.to_numpy(float)
    ok = np.isfinite(X).all(axis=1) & np.isfinite(fwd)
    train = ok & (close_ts + horizon * H < test_start)
    info: dict[str, Any] = {"train_hours": int(train.sum()), "test_start": int(test_start)}
    out = []
    for name, y in (("up", y_up), ("down", y_dn)):
        if train.sum() < 2000 or y[train].sum() < 50:
            out.append(np.array([], np.int64))
            info[name] = {"skipped": "too little training data"}
            continue
        m = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15, l2_regularization=1.0,
                                           random_state=7)
        m.fit(X[train], y[train])
        p_tr = m.predict_proba(X[train])[:, 1]
        thr = float(np.quantile(p_tr, q))
        live = np.isfinite(X).all(axis=1) & (close_ts >= test_start - 3 * DAY)
        p = np.full(len(X), np.nan)
        p[live] = m.predict_proba(X[live])[:, 1]
        ev = close_ts[live & (p >= thr)]
        # how good is the score on the test hours whose outcome is known (honest check)
        tst = ok & (close_ts >= test_start)
        hit = None
        if tst.sum() and (p[tst] >= thr).sum():
            hit = float(y[tst][p[tst] >= thr].mean())
        info[name] = {"base_rate_train": float(y[train].mean()), "threshold": thr, "events_test": int((ev >= test_start).sum()),
                      "precision_test": hit, "base_rate_test": float(y[tst].mean()) if tst.sum() else None}
        out.append(ev)
    return out[0], out[1], info


def coin_breaks(rt: Any, sym: str, cache: dict, look: int = 12) -> tuple[np.ndarray, np.ndarray]:
    if sym not in cache:
        try:
            d = rt.candles(sym, "4h").reset_index(drop=True)
            cache[sym] = events_break(d.assign(ts=d["ts"]), look) if len(d) > look + 2 else (np.array([], np.int64),) * 2
            # events_break assumes 1h close times: shift to 4h closes
            up, dn = cache[sym]
            cache[sym] = (up + 3 * H, dn + 3 * H)
        except Exception:
            cache[sym] = (np.array([], np.int64), np.array([], np.int64))
    return cache[sym]


# ---- apply a variant --------------------------------------------------------------------------------------------------------
def _first_after(ev: np.ndarray, a: int, b: int) -> int | None:
    i = int(np.searchsorted(ev, a, side="right"))
    return int(ev[i]) if i < len(ev) and ev[i] < b else None


def _recent(ev: np.ndarray, t: int, hours: float) -> bool:
    i = int(np.searchsorted(ev, t, side="right"))
    return i > 0 and ev[i - 1] > t - hours * H


def apply_variant(trades: list[dict[str, Any]], against, pause_h: float | None, close: str | None) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """against(t) -> sorted event times that go against trade t. Returns the modified trades (before the live limits)."""
    out, n_pause, n_close, n_kept_loss = [], 0, 0, 0
    for t in trades:
        ev = against(t)
        if pause_h and len(ev) and _recent(ev, int(t["ts"]), pause_h):
            n_pause += 1
            continue
        if close and len(ev):
            T = _first_after(ev, int(t["ts"]), int(t["closed_ts"]))
            if T is not None:
                e = early(t, T)
                if e is not None and (close == "close_all" or e["r"] > 0):
                    out.append({**t, **e})
                    n_close += 1
                    continue
                if e is not None:
                    n_kept_loss += 1
        out.append(t)
    return out, {"paused": n_pause, "closed_early": n_close, "losing_left_to_stop": n_kept_loss}


def live_pipeline(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from .research_ideas import _cap
    from .research_risk import loss_stop
    calm = [t for t in trades if not t.get("drift_block") and not t.get("volatile")]
    return loss_stop(_cap(calm, 12, False), 3, 6)


def _affected(base, new) -> int:
    """Calls that differ: taken in one and not the other, or the same call with another result (closed early)."""
    kb = {(t["sym"], t["tf"], int(t["ts"])): t["r"] for t in base}
    kn = {(t["sym"], t["tf"], int(t["ts"])): t["r"] for t in new}
    return len(set(kb) ^ set(kn)) + sum(1 for k in set(kb) & set(kn) if abs(kb[k] - kn[k]) > 1e-9)


def _slim(v: dict[str, Any]) -> dict[str, Any]:
    return {k: v.get(k) for k in ("verdict", "reason", "base", "new", "affected", "bootstrap_better_share",
                                  "bootstrap_gain_r_5_50_95")} | {"halves": {h: {"base": x["base"].get("total_r"), "new": x["new"].get("total_r")}
                                                                              for h, x in (v.get("halves") or {}).items()}}


def run(db_url: str, budget_s: float) -> dict[str, Any]:
    from .research_caps import collect
    from .research_risk import regime_of
    from .research_v265 import _hook
    from .research_verdict import verdict
    trades, skipped, t0, rt = collect(db_url, budget_s, hook=_hook, keep_sim=True)
    cache: dict = {}
    for t in trades:
        t["volatile"] = regime_of(rt, t["sym"], int(t["ts"]), cache).endswith("_volatile")
    if not trades:
        return {"ok": False, "reason": "no test calls", "skipped": skipped[:20]}
    test_start = min(int(t["ts"]) for t in trades)
    h1, h4 = btc_frames(rt)
    syms = sorted({t["sym"] for t in trades})
    br = breadth_hourly(rt, syms, h1["ts"].to_numpy(np.int64) + H)
    feats = ai_features(h1, br)
    ev = {"btc_break": events_break(h1), "btc_regime": events_regime(h4)}
    up_ai, dn_ai, ai_info = ai_events(h1, feats, test_start)
    ev["ai"] = (up_ai, dn_ai)
    ccache: dict = {}

    def against_fn(kind: str):
        if kind == "coin_break":
            return lambda t: coin_breaks(rt, t["sym"], ccache)[0 if t["side"] < 0 else 1]
        up, dn = ev[kind]
        return lambda t: (up if t["side"] < 0 else dn)

    base = live_pipeline(trades)
    results: dict[str, Any] = {}
    for kind in ("ai", "btc_break", "btc_regime", "coin_break"):
        for pause_h in (None, 12, 24):
            for close in (None, "close_profit", "close_all"):
                if pause_h is None and close is None:
                    continue
                if kind == "coin_break" and pause_h:          # a coin break pauses only that coin's own new calls
                    pass
                name = f"{kind}|{'pause' + str(pause_h) if pause_h else 'nopause'}|{close or 'noclose'}"
                mod, counts = apply_variant(trades, against_fn(kind), pause_h, close)
                new = live_pipeline(mod)
                v = verdict(base, new, affected=_affected(base, new))
                by_tf = {}
                for tf in sorted({t["tf"] for t in base}):
                    b = [t for t in base if t["tf"] == tf]
                    n = [t for t in new if t["tf"] == tf]
                    if b:
                        vv = verdict(b, n)
                        by_tf[tf] = {"verdict": vv.get("verdict"), "base_r": vv["base"].get("total_r"), "new_r": vv["new"].get("total_r")}
                results[name] = {**_slim(v), "counts": counts, "by_tf": by_tf}
    # side split of the primary (did it help shorts in up-turns, longs in down-turns?)
    pm, _ = apply_variant(trades, against_fn("ai"), 24, "close_profit")
    pn = live_pipeline(pm)
    side_split = {}
    for sd, nm in ((-1, "short"), (1, "long")):
        b = [t for t in base if t["side"] == sd]
        n = [t for t in pn if t["side"] == sd]
        side_split[nm] = {"base_r": round(sum(t["r"] for t in b), 2), "new_r": round(sum(t["r"] for t in n), 2), "n_base": len(b), "n_new": len(n)}
    ranked = sorted(((k, v) for k, v in results.items()), key=lambda kv: -((kv[1].get("new") or {}).get("total_r") or -1e9))
    return {"ok": True, "calls": len(trades), "base_calls": len(base), "test_start": test_start,
            "seconds": round(time.time() - t0, 1), "skipped_n": len(skipped), "skipped": skipped[:10],
            "primary": PRIMARY, "primary_result": results.get(PRIMARY), "primary_by_side": side_split, "ai_model": ai_info,
            "events_in_test": {k: {"up": int((np.asarray(v[0]) >= test_start).sum()), "down": int((np.asarray(v[1]) >= test_start).sum())}
                               for k, v in ev.items()},
            "passes": [k for k, v in results.items() if v.get("verdict") == "PASS"],
            "top5_by_total_r": [{"variant": k, "verdict": v.get("verdict"), "total_r": (v.get("new") or {}).get("total_r"),
                                 "max_dd": (v.get("new") or {}).get("max_dd_r")} for k, v in ranked[:5]],
            "variants": results}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="sqlite:///./data/crypto_ai.db")
    ap.add_argument("--budget", type=float, default=14400)
    ap.add_argument("--out", default="-")
    a = ap.parse_args()
    s = json.dumps(run(a.db, a.budget), indent=1, default=str)
    print(s) if a.out == "-" else open(a.out, "w").write(s)
