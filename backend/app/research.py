"""Read-only research on the recorded calls (audit v1, phases 1b and 3). Never writes to the database.

  python -m app.research giveback [--db sqlite:///./data/crypto_ai.db] [--out results/giveback.json]
  python -m app.research compare  [--db ...] [--out results/compare.json]
  python -m app.research engine   [--db ...] [--out results/engine.json] [--budget 14400]  (v2.6, see research_engine.py)
  python -m app.research horizon  [--db ...] [--out results/horizon.json] [--budget 14400] (time limit 30/60/90/none,
                                  see research_horizon.py)
  python -m app.research scalp15  [--db ...] [--out results/scalp15.json] [--budget 14400] (15m grade-A near-TP1 restart
                                  proposal with leverage / liquidation, see research_scalp15.py)

giveback  every closed call ever recorded (and separately those since record_since), replayed from publication on the
          stored 15m candles with the CURRENT rules: how many reached +0.5R / +0.8R / TP1 (1R) and still ended stopped
          or at break-even, average best open profit vs realised R, total R given back; by timeframe and grade.
compare   the same calls on identical candles, standard rules vs managed exits (give-back / ATR trail / time stop),
          after costs. The first 70 % (chronological) tune GIVEBACK_ARM_R x GIVEBACK_FRAC x TRAIL_ATR_K by expectancy;
          the last 30 % are an untouched test set. The verdict says plainly when the new rules are not better there.
Output: JSON on stdout and in --out.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from .config import ENGINE_VERSION, settings
from .data.base import tf_ms
from .db import Database, dumps, loads
from .engine import manage as M

HORIZON_BARS = 30
CLOSED = ("STOPPED", "TP1", "TP2", "TP3", "EXPIRED")
GRID = {"giveback_arm_r": (0.4, 0.6, 0.8), "giveback_frac": (0.4, 0.5, 0.6), "trail_atr_k": (1.5, 2.0, 3.0)}
TUNE_SHARE = 0.7


# ---- data access (read-only) ------------------------------------------------------------------------------------

def load_signals(db: Database) -> list[dict[str, Any]]:
    rows = db.query("SELECT * FROM signals WHERE side != 0 AND entry IS NOT NULL AND stop IS NOT NULL "
                    "AND tp1 IS NOT NULL ORDER BY created_at")
    for r in rows:
        p = loads(r.get("payload"), {}) or {}
        r["grade"] = p.get("grade") or "-"
        r["runner"] = p.get("runner") or {}
    return rows


def candle_loader(db: Database) -> Callable[[str, str], pd.DataFrame]:
    cache: dict[tuple[str, str], pd.DataFrame] = {}

    def get(symbol: str, tf: str) -> pd.DataFrame:
        if (symbol, tf) not in cache:
            rows = db.query("SELECT exchange, ts, open, high, low, close FROM market_data WHERE symbol = ? AND timeframe = ? "
                            "ORDER BY ts", (symbol, tf))
            df = pd.DataFrame(rows, columns=["exchange", "ts", "open", "high", "low", "close"])
            if not df.empty and df["exchange"].nunique() > 1:      # several sources: the one with the most candles
                best = df["exchange"].value_counts().idxmax()
                df = df[df["exchange"] == best]
            cache[(symbol, tf)] = df.drop(columns=["exchange"]).reset_index(drop=True)
        return cache[(symbol, tf)]
    return get


def _atr(own: pd.DataFrame, before_ts: int, n: int = 14) -> float | None:
    if own is None or own.empty:
        return None
    d = own[own["ts"] < before_ts].tail(n + 1)
    if len(d) < 2:
        return None
    pc = d["close"].shift(1)
    tr = pd.concat([d["high"] - d["low"], (d["high"] - pc).abs(), (d["low"] - pc).abs()], axis=1).max(axis=1).iloc[1:]
    return float(tr.mean()) if len(tr) else None


def replay(sig: dict[str, Any], candles: Callable[[str, str], pd.DataFrame], params: dict[str, Any]) -> dict[str, Any] | None:
    """Follow one recorded call from publication (candles opened at/after created_at) under `params`."""
    step = tf_ms(sig["timeframe"])
    created = int(sig["created_at"])
    end = created + step * HORIZON_BARS
    p15 = candles(sig["symbol"], "15m")
    path = p15[(p15["ts"] >= created) & (p15["ts"] < end)] if p15 is not None and len(p15) else p15
    pms = tf_ms("15m")
    if path is None or path.empty:
        return None
    side, entry = int(sig["side"]), float(sig["entry"])
    first_is_fill = False
    if sig.get("decision") == "BUY ON PULLBACK" and sig.get("fill_status") is not None:
        idx = M.find_fill(side, entry, path, until_ts=created + settings.fill_window_bars * step)
        if idx is None:
            return {"not_filled": True}
        path, first_is_fill = path.iloc[idx:], True
    atr = sig.get("atr") or _atr(candles(sig["symbol"], sig["timeframe"]), int(sig["bar_ts"]) + step)
    if not atr:
        atr = abs(entry - float(sig["stop"])) / 1.5
    run = sig.get("runner") or {}
    complete = int(path["ts"].iloc[-1]) + pms >= end
    res = M.follow(side, entry, float(sig["stop"]), [sig["tp1"], sig["tp2"], sig["tp3"]], path,
                   runner_target=run.get("target") if run.get("on") else None, atr=atr, params=params,
                   complete=complete, first_is_fill=first_is_fill, start_ts=int(path["ts"].iloc[0]), bar_ms=step,
                   path_ms=pms)
    if res["status"] == "OPEN":
        return None                                     # not finished on the stored candles: not judged
    res["risk_pct"] = abs(entry - float(sig["stop"])) / entry * 100
    return res


# ---- statistics ---------------------------------------------------------------------------------------------------

def stats(rs: list[float], rets: list[float]) -> dict[str, Any]:
    """rs: per-trade R after costs; rets: per-trade % after costs. Drawdown on the sequential equal-risk R curve."""
    n = len(rs)
    if not n:
        return {"n": 0, "win_rate": None, "expectancy_r": None, "expectancy_pct": None, "max_drawdown_r": None,
                "profit_factor": None, "total_r": 0.0}
    r = np.array(rs, float)
    eq = np.cumsum(r)
    dd = float(np.max(np.maximum.accumulate(np.concatenate([[0.0], eq])) - np.concatenate([[0.0], eq])))
    gains, losses = r[r > 0].sum(), -r[r <= 0].sum()
    return {"n": n, "win_rate": float((r > 0).mean()), "expectancy_r": float(r.mean()),
            "expectancy_pct": float(np.mean(rets)), "max_drawdown_r": dd,
            "profit_factor": float(gains / losses) if losses > 0 else None, "total_r": float(r.sum())}


def run_rules(sigs: list[dict[str, Any]], candles, params: dict[str, Any], cost_pct: float) -> dict[str, Any]:
    rs, rets, exits = [], [], {}
    for s in sigs:
        res = replay(s, candles, params)
        if not res or res.get("not_filled"):
            continue
        net = res["return_pct"] - cost_pct
        rs.append(net / res["risk_pct"] if res["risk_pct"] else 0.0)
        rets.append(net)
        exits[res["exit_reason"] or "none"] = exits.get(res["exit_reason"] or "none", 0) + 1
    return {**stats(rs, rets), "exit_reasons": exits}


# ---- reports -------------------------------------------------------------------------------------------------------

def giveback_report(sigs: list[dict[str, Any]], candles, since: int = 0) -> dict[str, Any]:
    params = {"managed": False}

    def block(xs: list[dict[str, Any]]) -> dict[str, Any]:
        n = 0
        reached = {"0.5R": 0, "0.8R": 0, "1R_tp1": 0}
        bad_after = {"0.5R": 0, "0.8R": 0, "1R_tp1": 0}
        peaks, real, given = [], [], 0.0
        for s in xs:
            res = replay(s, candles, params)
            if not res or res.get("not_filled"):
                continue
            n += 1
            rr = res["return_r"] or 0.0
            peaks.append(res["peak_r"])
            real.append(rr)
            given += max(0.0, res["peak_r"] - rr)
            bad = res["exit_reason"] in ("stop", "break_even")
            for k, lvl in (("0.5R", 0.5), ("0.8R", 0.8), ("1R_tp1", 1.0)):
                if res["peak_r"] >= lvl - 1e-12:
                    reached[k] += 1
                    bad_after[k] += int(bad)
        return {"n": n,
                "reached_then_stopped_or_break_even": {k: {"count": bad_after[k], "share_of_all": bad_after[k] / n if n else None,
                                                           "share_of_reached": bad_after[k] / reached[k] if reached[k] else None,
                                                           "reached": reached[k]} for k in reached},
                "avg_peak_r": float(np.mean(peaks)) if peaks else None,
                "avg_realised_r": float(np.mean(real)) if real else None,
                "total_r_given_back": float(given)}

    def split(xs: list[dict[str, Any]]) -> dict[str, Any]:
        return {"all": block(xs),
                "by_timeframe": {tf: block([s for s in xs if s["timeframe"] == tf]) for tf in sorted({s["timeframe"] for s in xs})},
                "by_grade": {g: block([s for s in xs if s["grade"] == g]) for g in sorted({s["grade"] for s in xs})}}

    closed = [s for s in sigs if s["status"] in CLOSED or s["status"] == "OPEN"]
    return {"rules": "current (managed exits off): 50/25/25, stop first in a candle, break-even after TP1, TP1 after TP2",
            "followed_from": "publication (first 15m candle opened at or after created_at)",
            "ever": split(closed), "since_record": split([s for s in closed if int(s["created_at"]) >= since]),
            "record_since": since}


def compare_report(sigs: list[dict[str, Any]], candles, cost_pct: float) -> dict[str, Any]:
    closed = sorted([s for s in sigs if s["status"] in CLOSED or s["status"] == "OPEN"], key=lambda s: s["created_at"])
    k = int(len(closed) * TUNE_SHARE)
    tune, test = closed[:k], closed[k:]
    base = {"managed": True, "time_stop_bars": settings.time_stop_bars, "time_stop_min_r": settings.time_stop_min_r}
    grid = []
    for arm, frac, trail in itertools.product(GRID["giveback_arm_r"], GRID["giveback_frac"], GRID["trail_atr_k"]):
        p = {**base, "giveback_arm_r": arm, "giveback_frac": frac, "trail_atr_k": trail}
        st = run_rules(tune, candles, p, cost_pct)
        grid.append({"params": {"giveback_arm_r": arm, "giveback_frac": frac, "trail_atr_k": trail},
                     "expectancy_r": st["expectancy_r"], "n": st["n"]})
    scored = [g for g in grid if g["expectancy_r"] is not None]
    best = max(scored, key=lambda g: g["expectancy_r"])["params"] if scored else \
        {"giveback_arm_r": 0.6, "giveback_frac": 0.5, "trail_atr_k": 2.0}
    newp = {**base, **best}
    old = {"managed": False}
    out = {"cost_pct_round_trip": cost_pct, "split": {"tuning": len(tune), "test": len(test), "tune_share": TUNE_SHARE},
           "chosen_on_tuning_set": best, "grid": grid,
           "tuning": {"old": run_rules(tune, candles, old, cost_pct), "new": run_rules(tune, candles, newp, cost_pct)},
           "test": {"old": run_rules(test, candles, old, cost_pct), "new": run_rules(test, candles, newp, cost_pct)}}
    o, n = out["test"]["old"], out["test"]["new"]
    if not o["n"] or not n["n"]:
        verdict, better = "Not enough closed calls with stored candles in the test set to judge.", False
    else:
        better = (n["expectancy_r"] or -9) > (o["expectancy_r"] or -9) and (n["max_drawdown_r"] or 0) <= (o["max_drawdown_r"] or 0) * 1.1
        verdict = (f"Managed exits {'ARE' if better else 'are NOT'} better on the untouched test set: expectancy "
                   f"{n['expectancy_r']:+.3f}R vs {o['expectancy_r']:+.3f}R, max drawdown {n['max_drawdown_r']:.2f}R vs "
                   f"{o['max_drawdown_r']:.2f}R over {n['n']} calls (after {cost_pct:.2f}% costs).")
    out["new_is_better_on_test"] = bool(better)
    out["verdict"] = verdict
    out["recommendation"] = ("keep MANAGED_EXITS off" if not better else
                             f"MANAGED_EXITS=1 with GIVEBACK_ARM_R={best['giveback_arm_r']}, GIVEBACK_FRAC={best['giveback_frac']}, "
                             f"TRAIL_ATR_K={best['trail_atr_k']} (owner decision)")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.research")
    ap.add_argument("command", choices=["giveback", "compare", "engine", "horizon", "scalp15"])
    ap.add_argument("--db", default=settings.database_url)
    ap.add_argument("--out", default=None, help="also write the JSON to this file")
    ap.add_argument("--cost-pct", type=float, default=settings.research_cost_pct)
    ap.add_argument("--budget", type=float, default=14400, help="engine: seconds before remaining series are skipped")
    ap.add_argument("--symbols", default=None, help="engine: comma-separated symbols (default: all with an active model)")
    ap.add_argument("--timeframes", default=None, help="engine: comma-separated timeframes")
    ap.add_argument("--plan", default="uniform", help="horizon: uniform (30/60/90/none) or proposal (per timeframe)")
    a = ap.parse_args(argv)
    path = a.db.replace("sqlite:///", "")
    if a.db.startswith("sqlite:///") and not Path(path).exists():
        out = {"ok": False, "command": a.command, "reason": f"no engine state found at {path} (state cache not restored)"}
    else:
        tmp = None
        if a.db.startswith("sqlite:///") and path != ":memory:":
            # opening a Database creates / migrates tables: work on a private copy so the engine state is never touched
            import shutil
            import sqlite3
            import tempfile
            tmp = Path(tempfile.mkdtemp(prefix="research-")) / "copy.db"
            src = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
            dst = sqlite3.connect(str(tmp))
            src.backup(dst)
            src.close()
            dst.close()
            a.db = f"sqlite:///{tmp}"
        if a.command == "engine":
            from . import research_engine
            body = research_engine.run(a.db, a.budget, a.cost_pct,
                                       [x for x in (a.symbols or "").split(",") if x] or None,
                                       [x for x in (a.timeframes or "").split(",") if x] or None)
            out = {"ok": True, "command": a.command, **body}
        elif a.command == "horizon":
            from . import research_horizon
            body = research_horizon.run(a.db, a.budget, a.cost_pct,
                                        [x for x in (a.symbols or "").split(",") if x] or None,
                                        [x for x in (a.timeframes or "").split(",") if x] or None, a.plan)
            out = {"ok": True, "command": a.command, **body}
        elif a.command == "scalp15":
            from . import research_scalp15
            body = research_scalp15.run(a.db, a.budget, a.cost_pct, [x for x in (a.symbols or "").split(",") if x] or None)
            out = {"ok": True, "command": a.command, **body}
        else:
            db = Database(a.db)
            sigs = load_signals(db)
            candles = candle_loader(db)
            since = int(db.get_setting("record_since", 0) or 0)
            body = giveback_report(sigs, candles, since) if a.command == "giveback" else compare_report(sigs, candles, a.cost_pct)
            out = {"ok": True, "command": a.command, "engine_version": ENGINE_VERSION, "signals_in_db": len(sigs), **body}
    text = json.dumps(json.loads(dumps(out)), indent=1)
    print(text)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
