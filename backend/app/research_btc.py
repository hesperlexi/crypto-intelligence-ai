"""Adaptive BTC volatility study (read-only; owner, 24 Nov 2026, brief "Advanced market intelligence, adaptive BTC
volatility & capital flow"). Same unseen calls and verdict as every study; baseline = today's live pipeline incl. the
liquidity-sweep guard.

GUARDS (no new call against a BTC shock). BTC shock = BTC's return over the last W hours (closed 1h candles) measured in
its own normal size: z = ret_W / std of all W-hour returns over the previous 30 days (adaptive, no fixed %).
  shock|W|z  : no SHORT within H hours after an up-shock z >= k, no LONG after a down-shock z <= -k.
  lev|W|z    : the same, only when the shock is SPOT-LED (BTC funding over the last 24 h not crowded: |funding z| < 2);
               a leverage-led shock (crowded funding) is left alone. Funding is live data (no publication lag).
OPPORTUNITY (15-minute strategies, standalone and added to the live calls):
  recovery     : BTC fell >= 2.5 sd in 4 h; within 8 h a 15m candle closes above the high of the 3 before it and above
                 the 4 h low by 0.5 ATR -> LONG the 3 coins that fell least during the drop; stop = coin's low of the
                 last 4 h - 0.1 ATR; 1 / 1.75 / 2.5R ladder, 24 h limit.
  continuation : BTC 1h return >= 2 sd and the next 15m candle closes further that way -> trade the 3 coins with the
                 strongest 1h move the same way; stop 1.5 ATR(15m); 12 h limit.
  exhaustion   : BTC 4h return >= 3 sd, then two 15m candles fail to make a new extreme and close back by 0.5 ATR ->
                 trade BTC the other way; stop 0.1 ATR beyond the extreme; 12 h limit.
  One trade per coin per event, 12 h cooldown per type; 0.15 % costs + funding; followed on 15m candles (same engine
  as the record). No future data: every input is a closed candle before the entry.
python -m app.research_btc --budget 14400 --out x.json"""
from __future__ import annotations

import argparse
import json
import time
from typing import Any

import numpy as np

H = 3_600_000
M15 = 900_000
COST = 0.15


def btc_z(rt, hours: int) -> tuple[np.ndarray, np.ndarray]:
    """(close times, z of the W-hour return) on closed 1h candles; std over the previous 30 days."""
    d = rt.candles("BTC/USDT", "1h")
    c = d["close"].to_numpy(float)
    ts = d["ts"].to_numpy(np.int64) + H
    r = np.full(len(c), np.nan)
    r[hours:] = c[hours:] / c[:-hours] - 1
    z = np.full(len(c), np.nan)
    win = 30 * 24
    for i in range(win + hours, len(c)):
        sd = np.nanstd(r[i - win:i])
        if sd > 0:
            z[i] = r[i] / sd
    return ts, z


def funding_z(rt) -> tuple[np.ndarray, np.ndarray]:
    rows = rt.db.query("SELECT ts, value FROM derivs WHERE symbol = 'BTC/USDT' AND kind = 'funding_1h' ORDER BY ts")
    ts = np.array([int(r["ts"]) for r in rows], np.int64)
    v = np.array([float(r["value"] or 0) for r in rows])
    z = np.full(len(v), np.nan)
    for i in range(24 * 30, len(v)):
        last = v[i - 23:i + 1].mean()
        base = v[i - 24 * 30:i]
        sd = base.std()
        if sd > 0:
            z[i] = (last - base.mean()) / sd
    return ts, z


def _last_before(ts: np.ndarray, vals: np.ndarray, t: int) -> float | None:
    i = int(np.searchsorted(ts, t, side="right")) - 1
    return None if i < 0 or not np.isfinite(vals[i]) else float(vals[i])


def shocks(ts: np.ndarray, z: np.ndarray, k: float) -> tuple[np.ndarray, np.ndarray]:
    up = ts[np.where(z >= k)[0]]
    dn = ts[np.where(z <= -k)[0]]
    return up, dn


def _recent(ev: np.ndarray, t: int, hours: float) -> bool:
    i = int(np.searchsorted(ev, t, side="right")) - 1
    return i >= 0 and t - int(ev[i]) <= hours * H


# ------------------------------------------------------------------------------------------------ 15m opportunity
class Bars:
    def __init__(self, rt, syms):
        self.d = {}
        for s in syms:
            try:
                x = rt.candles(s, "15m")
                if x is not None and len(x) > 500:
                    self.d[s] = {k: x[k].to_numpy(np.int64 if k == "ts" else float) for k in ("ts", "open", "high", "low", "close")}
            except Exception:
                pass

    def atr(self, s, i, n=14):
        a = self.d[s]
        lo = max(1, i - n + 1)
        h, l, c = a["high"][lo:i + 1], a["low"][lo:i + 1], a["close"][lo - 1:i]
        tr = np.maximum(h - l, np.maximum(abs(h - c), abs(l - c)))
        return float(tr.mean()) if len(tr) else None

    def idx(self, s, t):
        """index of the last 15m candle closed by t"""
        return int(np.searchsorted(self.d[s]["ts"], t - M15, side="right")) - 1


def follow(B: Bars, s: str, i: int, side: int, stop: float, hours: float) -> dict[str, Any] | None:
    from .engine.futures import DEFAULT_FUNDING_RATE
    from .ml import series_sim as S
    a = B.d[s]
    entry = float(a["close"][i])
    if side * (entry - stop) <= entry * 0.003:
        return None
    j = min(len(a["ts"]), i + 1 + int(hours * 4))
    if j - (i + 1) < 4:
        return None
    hi, lo, cl, op = a["high"][i + 1:j], a["low"][i + 1:j], a["close"][i + 1:j], a["open"][i + 1:j]
    out = S.follow(side, entry, stop, S.ladder(side, entry, stop), hi, lo, cl, complete=True, open_=op)
    if out is None:
        return None
    t_in = int(a["ts"][i]) + M15
    closed = int(a["ts"][i + 1 + out.exit_idx]) + M15
    r = out.net_r(COST) - (side * (closed - t_in) / H * DEFAULT_FUNDING_RATE / 8 * 100) / out.risk_pct
    return {"r": float(r), "closed_ts": closed, "status": out.status, "ts": t_in}


def opportunities(rt, syms: list[str], t_from: int, t_to: int) -> dict[str, list[dict[str, Any]]]:
    B = Bars(rt, syms)
    if "BTC/USDT" not in B.d:
        return {}
    b = B.d["BTC/USDT"]
    c = b["close"]
    n = len(c)
    r4 = np.full(n, np.nan)
    r4[16:] = c[16:] / c[:-16] - 1
    r1 = np.full(n, np.nan)
    r1[4:] = c[4:] / c[:-4] - 1
    win = 30 * 96

    def z_at(r, i):
        if i < win + 16:
            return np.nan
        sd = np.nanstd(r[i - win:i:4])
        return r[i] / sd if sd > 0 else np.nan

    alts = [s for s in B.d if s != "BTC/USDT"]
    out = {"recovery": [], "continuation": [], "exhaustion": []}
    cool = {"recovery": 0, "continuation": 0, "exhaustion": 0}
    i = win + 20
    while i < n - 100:
        t = int(b["ts"][i]) + M15
        if not (t_from <= t <= t_to):
            i += 1
            continue
        z4, z1 = z_at(r4, i), z_at(r1, i)
        # ---- recovery
        if t >= cool["recovery"] and np.isfinite(z4) and z4 <= -2.5:
            low_i = i - 16 + int(np.argmin(b["low"][i - 16:i + 1]))
            low = b["low"][low_i]
            for k in range(i + 1, min(n - 1, i + 32)):
                a_ = B.atr("BTC/USDT", k) or 0
                if c[k] > b["high"][k - 3:k].max() and c[k] > low + 0.5 * a_:
                    tk = int(b["ts"][k]) + M15
                    ranked = []
                    for s in alts:
                        j0, j1 = B.idx(s, int(b["ts"][i - 16]) + M15), B.idx(s, tk)
                        if j0 < 20 or j1 <= j0:
                            continue
                        x = B.d[s]
                        dd = x["low"][j0:j1 + 1].min() / x["close"][j0] - 1
                        ranked.append((dd, s, j1))
                    for dd, s, j1 in sorted(ranked, reverse=True)[:3]:
                        x = B.d[s]
                        stop = x["low"][max(0, j1 - 16):j1 + 1].min() - 0.1 * (B.atr(s, j1) or 0)
                        f = follow(B, s, j1, 1, stop, 24)
                        if f:
                            out["recovery"].append({"sym": s, "tf": "opp-rec", "side": 1, **f})
                    cool["recovery"] = tk + 12 * H
                    break
        # ---- continuation
        if t >= cool["continuation"] and np.isfinite(z1) and abs(z1) >= 2 and i + 1 < n:
            side = 1 if z1 > 0 else -1
            if side * (c[i + 1] - c[i]) > 0:
                tk = int(b["ts"][i + 1]) + M15
                ranked = []
                for s in alts:
                    j = B.idx(s, tk)
                    if j < 20:
                        continue
                    x = B.d[s]
                    ranked.append((side * (x["close"][j] / x["close"][j - 4] - 1), s, j))
                for mv, s, j in sorted(ranked, reverse=True)[:3]:
                    a_ = B.atr(s, j) or 0
                    f = follow(B, s, j, side, B.d[s]["close"][j] - side * 1.5 * a_, 12)
                    if f:
                        out["continuation"].append({"sym": s, "tf": "opp-cont", "side": side, **f})
                cool["continuation"] = tk + 12 * H
        # ---- exhaustion
        if t >= cool["exhaustion"] and np.isfinite(z4) and abs(z4) >= 3 and i + 3 < n:
            side0 = 1 if z4 > 0 else -1
            ext = b["high"][i - 16:i + 1].max() if side0 > 0 else b["low"][i - 16:i + 1].min()
            a_ = B.atr("BTC/USDT", i) or 0
            k = i + 2
            no_new = (b["high"][i + 1:k + 1].max() < ext) if side0 > 0 else (b["low"][i + 1:k + 1].min() > ext)
            back = side0 * (ext - c[k]) >= 0.5 * a_
            if no_new and back:
                f = follow(B, "BTC/USDT", k, -side0, ext + side0 * 0.1 * a_, 12)
                if f:
                    out["exhaustion"].append({"sym": "BTC/USDT", "tf": "opp-exh", "side": -side0, **f})
                cool["exhaustion"] = int(b["ts"][k]) + M15 + 12 * H
        i += 1
    return out


def run(db_url: str, budget_s: float) -> dict[str, Any]:
    from .research_caps import collect
    from .research_risk import regime_of
    from .research_sweep import _recent as srecent, sweeps
    from .research_turn import _affected, _slim, live_pipeline
    from .research_v265 import _hook
    from .research_verdict import curve, verdict
    trades, skipped, t0, rt = collect(db_url, budget_s, hook=_hook)
    if not trades:
        return {"ok": False, "reason": "no test calls"}
    cache: dict = {}
    for t in trades:
        t["volatile"] = regime_of(rt, t["sym"], int(t["ts"]), cache).endswith("_volatile")
    syms = sorted({t["sym"] for t in trades} | {"BTC/USDT"})
    sw = {s: sweeps(rt, s) for s in syms}

    def st(sym, side):
        x = sw.get(sym)
        return np.array(sorted(e["ts"] for e in (x or {}).get("events", []) if e["side"] == side), np.int64)

    plain = {(s, sd): st(s, sd) for s in syms for sd in (1, -1)}
    live_now = [t for t in trades if not srecent(plain[(t["sym"], -int(t["side"]))], int(t["ts"]), 6)]
    base = live_pipeline(live_now)
    fts, fz = funding_z(rt)
    res: dict[str, Any] = {}
    for W in (12, 24):
        zts, z = btc_z(rt, W)
        for k in (1.5, 2.0, 2.5):
            up, dn = shocks(zts, z, k)
            for Hh in (6, 12, 24):
                for mode in ("shock", "lev"):
                    kept = []
                    for t in live_now:
                        tt, sd = int(t["ts"]), int(t["side"])
                        ev = up if sd < 0 else dn                     # an up-shock stands against shorts
                        if _recent(ev, tt, Hh):
                            if mode == "lev":
                                fzv = _last_before(fts, fz, tt)
                                if fzv is not None and abs(fzv) >= 2:
                                    kept.append(t)                    # leverage-led: leave it
                                    continue
                            continue
                        kept.append(t)
                    new = live_pipeline(kept)
                    v = verdict(base, new, affected=_affected(base, new))
                    res[f"{mode}|{W}h|z{k:g}|{Hh}h"] = {**_slim(v), "blocked": len(live_now) - len(kept)}
    # BTC condition split of the baseline (what the live calls did during shocks)
    zts, z = btc_z(rt, 24)
    split: dict[str, list] = {}
    for t in base:
        zv = _last_before(zts, z, int(t["ts"]))
        key = "unknown" if zv is None else ("up-shock" if zv >= 2 else "down-shock" if zv <= -2 else "normal")
        split.setdefault(f"{key}|{'long' if t['side'] > 0 else 'short'}", []).append(t)
    test_start = min(int(t["ts"]) for t in trades)
    test_end = max(int(t["ts"]) for t in trades)
    opp = opportunities(rt, syms, test_start, test_end)
    opp_res = {}
    for name, lst in opp.items():
        lst = sorted(lst, key=lambda x: x["ts"])
        mid = test_start + (test_end - test_start) // 2
        opp_res[name] = {"all": curve(lst), "first_half": curve([x for x in lst if x["ts"] < mid]),
                         "second_half": curve([x for x in lst if x["ts"] >= mid]),
                         "long": curve([x for x in lst if x["side"] > 0]), "short": curve([x for x in lst if x["side"] < 0])}
        if lst:
            new = live_pipeline(live_now + lst)
            v = verdict(base, new, affected=_affected(base, new))
            res[f"add|{name}"] = {**_slim(v), "added": len(lst)}
    ranked = sorted(res.items(), key=lambda kv: -((kv[1].get("new") or {}).get("total_r") or -1e9))
    return {"ok": True, "calls": len(trades), "base": curve(base), "test_start": test_start, "test_end": test_end,
            "seconds": round(time.time() - t0, 1), "baseline_btc_split": {k: curve(v) for k, v in split.items()},
            "opportunity": opp_res, "variants": res, "top": [k for k, _ in ranked[:12]],
            "passes": [k for k, v in res.items() if v.get("verdict") == "PASS"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=14400)
    ap.add_argument("--out", required=True)
    ap.add_argument("--db", default="sqlite:///./data/crypto_ai.db")
    a = ap.parse_args()
    out = run(a.db, a.budget)
    with open(a.out, "w") as f:
        json.dump(out, f, default=str)


if __name__ == "__main__":
    main()
